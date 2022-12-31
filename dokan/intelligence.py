from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Sequence

import numpy as np
from django.core.cache import cache
from django.db.models import Count, Max
from django.utils import timezone
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .models import Item, Order, OrderItem
from .services import get_active_order


_CONTENT_MODEL_CACHE_KEY = "dokan:intelligence:content_model"
_COLLABORATIVE_MODEL_CACHE_KEY = "dokan:intelligence:collaborative_model"
_MODEL_CACHE_TIMEOUT = 300  # seconds


STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "your",
    "this",
    "that",
    "into",
    "built",
    "daily",
    "wear",
    "help",
    "need",
    "issue",
    "about",
    "please",
}

FAQ_KNOWLEDGE_BASE = [
    {
        "title": "Order tracking and delivery timelines",
        "answer": "Track the latest order status from the Orders page. Placed and processing orders usually move to shipped after payment review and stock confirmation.",
        "keywords": {"order", "track", "tracking", "delivery", "shipped", "status", "where"},
    },
    {
        "title": "Stripe and online payment support",
        "answer": "If Stripe payment stays pending, the store waits for a confirmation callback. Expired or failed sessions reopen the cart so checkout can be retried safely.",
        "keywords": {"stripe", "payment", "paid", "pending", "card", "checkout", "failed"},
    },
    {
        "title": "Returns, refund eligibility, and wrong item cases",
        "answer": "Delivered orders can open return requests from order history. Common reasons include defective item, wrong item sent, fit issue, or not as described.",
        "keywords": {"return", "refund", "exchange", "wrong", "defective", "size", "fit", "refunds"},
    },
    {
        "title": "Coupon and discount troubleshooting",
        "answer": "Coupons apply only when active, inside the valid date window, above the minimum order value, and below any usage limit.",
        "keywords": {"coupon", "discount", "promo", "offer", "code", "apply"},
    },
    {
        "title": "Account access and email verification",
        "answer": "New accounts can request email verification from the dashboard. Login activity and verification status are visible in the security section.",
        "keywords": {"account", "login", "email", "verify", "verification", "password", "security"},
    },
    {
        "title": "Product comparison, stock, and recommendations",
        "answer": "Use compare, wishlist, and recommendation flows to evaluate alternatives. Low-stock alerts and demand score help highlight popular products.",
        "keywords": {"product", "compare", "recommend", "stock", "availability", "wishlist"},
    },
]


@dataclass
class Recommendation:
    item: Item
    score: float
    reasons: list[str]


@dataclass
class CustomerSegment:
    code: str
    label: str
    confidence: float
    summary: str


@dataclass
class SearchResult:
    item: Item
    score: float
    reasons: list[str]


@dataclass
class CustomerHealth:
    retention_score: float
    churn_risk: str
    next_best_action: str
    summary: str


@dataclass
class SupportSuggestion:
    title: str
    answer: str
    confidence: float


def _tokenize_text(*parts: object) -> set[str]:
    tokens: set[str] = set()
    for chunk in " ".join(str(part or "") for part in parts).lower().replace("/", " ").replace(",", " ").split():
        cleaned = chunk.strip("()[]{}.!?-_'\"")
        if cleaned and cleaned not in STOP_WORDS and len(cleaned) > 2:
            tokens.add(cleaned)
    return tokens


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _popularity_score(item: Item) -> float:
    raw = (item.sold_units * 3) + (item.wishlist_count * 2) + max(item.view_count // 5, 0)
    return min(raw / 100.0, 1.0)


def calculate_demand_score(item: Item) -> float:
    rating_signal = (item.average_rating / 5.0) * 25.0
    wishlist_signal = min(item.wishlist_count, 20) / 20.0 * 20.0
    sales_signal = min(item.sold_units, 50) / 50.0 * 30.0
    stock_pressure = 0.0
    if item.reorder_level:
        stock_pressure = max(
            0.0,
            ((item.reorder_level * 2) - item.stock) / float(item.reorder_level * 2),
        ) * 15.0
    engagement_signal = min(item.view_count, 500) / 500.0 * 10.0
    discount_signal = 5.0 if item.has_discount else 0.0
    score = (
        rating_signal
        + wishlist_signal
        + sales_signal
        + stock_pressure
        + engagement_signal
        + discount_signal
    )
    return round(min(score, 100.0), 2)


def estimate_days_to_stockout(item: Item) -> float:
    demand_pressure = (
        (item.sold_units * 0.6)
        + (item.wishlist_count * 0.4)
        + (item.view_count * 0.02)
        + item.average_rating
    )
    daily_demand = max(0.2, demand_pressure / 30.0)
    if item.stock <= 0:
        return 0.0
    return round(item.stock / daily_demand, 1)


def _item_document(item: Item) -> str:
    """Flatten a product's text attributes into one document for TF-IDF."""
    parts = [
        item.title,
        item.short_description,
        item.description,
        item.category_name,
        item.brand_name,
        " ".join(str(tag) for tag in item.tags),
        " ".join(f"{key} {value}" for key, value in item.attributes.items()),
    ]
    return " ".join(str(part) for part in parts if part)


@dataclass
class _ContentModel:
    """A TF-IDF vector space fitted over the active catalog."""

    index: dict[int, int]
    items: list[Item]
    vectorizer: TfidfVectorizer
    matrix: "np.ndarray"


def _fit_content_model(catalog: Sequence[Item]) -> _ContentModel | None:
    items = list(catalog)
    if not items:
        return None
    documents = [_item_document(item) for item in items]
    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=1)
    matrix = vectorizer.fit_transform(documents)
    index = {item.pk: position for position, item in enumerate(items)}
    return _ContentModel(index=index, items=items, vectorizer=vectorizer, matrix=matrix)


def _catalog_version_key() -> str:
    stats = Item.objects.active().aggregate(count=Count("id"), latest=Max("updated_at"))
    return f"{stats['count']}:{stats['latest'].isoformat() if stats['latest'] else 'none'}"


def _order_history_version_key() -> str:
    stats = OrderItem.objects.filter(ordered=True).aggregate(count=Count("id"), latest=Max("updated_at"))
    return f"{stats['count']}:{stats['latest'].isoformat() if stats['latest'] else 'none'}"


def _get_full_catalog_content_model() -> _ContentModel | None:
    """Content model over the whole active catalog, cached and reused across
    requests instead of being refit from scratch on every call. Cache key is
    versioned by catalog size + latest update time so edits invalidate it
    automatically instead of relying on a blind TTL.
    """
    version = _catalog_version_key()
    cached_version, cached_model = cache.get(_CONTENT_MODEL_CACHE_KEY, (None, None))
    if cached_version == version:
        return cached_model
    model = _fit_content_model(list(Item.objects.active().with_metrics()))
    cache.set(_CONTENT_MODEL_CACHE_KEY, (version, model), _MODEL_CACHE_TIMEOUT)
    return model


@dataclass
class _CollaborativeModel:
    """Item-item cosine similarity over historical order baskets (item-based CF)."""

    index: dict[int, int]
    similarity: "np.ndarray"


def _fit_collaborative_model() -> _CollaborativeModel | None:
    basket_rows = OrderItem.objects.filter(ordered=True).values_list("orders__id", "item_id")
    baskets: dict[int, set[int]] = {}
    for order_id, item_id in basket_rows:
        if order_id is None or item_id is None:
            continue
        baskets.setdefault(order_id, set()).add(item_id)

    item_ids = sorted({item_id for basket in baskets.values() for item_id in basket})
    if len(item_ids) < 2:
        return None

    index = {item_id: position for position, item_id in enumerate(item_ids)}
    size = len(item_ids)
    co_occurrence = np.zeros((size, size), dtype=float)
    appearances = np.zeros(size, dtype=float)

    for basket in baskets.values():
        positions = [index[item_id] for item_id in basket]
        for position in positions:
            appearances[position] += 1
        for row in positions:
            for column in positions:
                if row != column:
                    co_occurrence[row, column] += 1

    denominator = np.sqrt(np.outer(appearances, appearances))
    with np.errstate(divide="ignore", invalid="ignore"):
        similarity = np.where(denominator > 0, co_occurrence / denominator, 0.0)
    return _CollaborativeModel(index=index, similarity=similarity)


def _get_cached_collaborative_model() -> _CollaborativeModel | None:
    """Cached wrapper around `_fit_collaborative_model`, versioned by order
    history size + latest update so it invalidates automatically when new
    orders are placed. `evaluate_recommendations` calls the uncached function
    directly since it wants a fresh fit for evaluation.
    """
    version = _order_history_version_key()
    cached_version, cached_model = cache.get(_COLLABORATIVE_MODEL_CACHE_KEY, (None, None))
    if cached_version == version:
        return cached_model
    model = _fit_collaborative_model()
    cache.set(_COLLABORATIVE_MODEL_CACHE_KEY, (version, model), _MODEL_CACHE_TIMEOUT)
    return model


def recommend_items(
    source: Item,
    *,
    pool: Iterable[Item] | None = None,
    limit: int = 4,
) -> list[Recommendation]:
    """Content-based recommendations using TF-IDF cosine similarity over product text."""
    candidates = [item for item in (pool or Item.objects.active().with_metrics()) if item.pk != source.pk]
    if not candidates:
        return []

    model = _get_full_catalog_content_model()
    if model is None or source.pk not in model.index:
        # Fall back to a direct fit if the caller passed items outside the
        # cached active-catalog model (e.g. an inactive item).
        model = _fit_content_model([source, *candidates])
    if model is None or source.pk not in model.index:
        return []

    source_vector = model.matrix[model.index[source.pk]]
    similarities = cosine_similarity(source_vector, model.matrix).flatten()

    recommendations: list[Recommendation] = []
    for candidate in candidates:
        position = model.index.get(candidate.pk)
        if position is None:
            continue
        content_score = float(similarities[position])
        category_bonus = 0.05 if candidate.catalog_category_id == source.catalog_category_id else 0.0
        brand_bonus = 0.05 if source.brand_id and candidate.brand_id == source.brand_id else 0.0
        rating_bonus = (candidate.average_rating / 5.0) * 0.05
        score = min(content_score + category_bonus + brand_bonus + rating_bonus, 1.0)
        if score <= 0:
            continue

        reasons: list[str] = []
        if content_score >= 0.35:
            reasons.append("High text similarity (TF-IDF cosine)")
        if category_bonus:
            reasons.append(f"Same category: {source.category_name}")
        if brand_bonus:
            reasons.append(f"Same brand: {source.brand_name}")
        if candidate.average_rating >= 4.0:
            reasons.append("Strong customer rating")

        recommendations.append(
            Recommendation(
                item=candidate,
                score=round(score * 100.0, 2),
                reasons=reasons[:3] or ["Similar product profile"],
            )
        )

    recommendations.sort(
        key=lambda entry: (-entry.score, -entry.item.average_rating, entry.item.title)
    )
    return recommendations[:limit]


def recommend_for_order(order: Order, *, limit: int = 4) -> list[Recommendation]:
    """Item-based collaborative filtering ("customers who bought this also bought")
    over historical co-purchase baskets, falling back to content-based similarity
    for items with no order history yet (cold start).
    """
    cart_items = [order_item.item for order_item in order.items.select_related("item")]
    if not cart_items:
        return []

    cart_item_ids = {item.pk for item in cart_items}
    pool = list(
        Item.objects.active().with_metrics().exclude(pk__in=cart_item_ids)
    )
    if not pool:
        return []

    collaborative_model = _get_cached_collaborative_model()
    pool_by_id = {item.pk: item for item in pool}
    aggregated_scores: dict[int, float] = {}
    reasons_by_item: dict[int, list[str]] = {}

    if collaborative_model is not None:
        for source in cart_items:
            source_position = collaborative_model.index.get(source.pk)
            if source_position is None:
                continue
            for candidate_id, candidate_position in collaborative_model.index.items():
                if candidate_id not in pool_by_id:
                    continue
                similarity = float(collaborative_model.similarity[source_position, candidate_position])
                if similarity <= 0:
                    continue
                if similarity > aggregated_scores.get(candidate_id, 0.0):
                    aggregated_scores[candidate_id] = similarity
                    reasons_by_item[candidate_id] = [
                        f"Frequently bought with {source.title}",
                        "Item-based collaborative filtering",
                    ]

    cold_start_sources = [item for item in cart_items if not collaborative_model or item.pk not in collaborative_model.index]
    if cold_start_sources:
        for source in cold_start_sources:
            for recommendation in recommend_items(source, pool=pool, limit=limit * 2):
                normalized = recommendation.score / 100.0
                if normalized > aggregated_scores.get(recommendation.item.pk, 0.0):
                    aggregated_scores[recommendation.item.pk] = normalized
                    reasons_by_item[recommendation.item.pk] = recommendation.reasons

    recommendations = [
        Recommendation(
            item=pool_by_id[item_id],
            score=round(score * 100.0, 2),
            reasons=reasons_by_item.get(item_id, ["Relevant cross-sell match"]),
        )
        for item_id, score in aggregated_scores.items()
        if item_id in pool_by_id
    ]
    recommendations.sort(key=lambda entry: (-entry.score, entry.item.title))
    return recommendations[:limit]


def rank_catalog_search(
    query: str,
    *,
    queryset: Sequence[Item] | Iterable[Item] | None = None,
    limit: int | None = None,
) -> list[SearchResult]:
    """Hybrid catalog search: TF-IDF/cosine semantic similarity blended with
    lexical exact/contains boosts on title, brand, and category.
    """
    normalized_query = query.strip().lower()
    if not normalized_query:
        return []

    catalog = list(queryset) if queryset is not None else list(Item.objects.active().with_metrics())
    if not catalog:
        return []

    model = _fit_content_model(catalog)
    if model is None:
        return []

    query_vector = model.vectorizer.transform([query])
    similarities = cosine_similarity(query_vector, model.matrix).flatten()

    results: list[SearchResult] = []
    for item in catalog:
        position = model.index.get(item.pk)
        if position is None:
            continue
        content_score = float(similarities[position])

        title_text = item.title.lower()
        brand_text = item.brand_name.lower()
        category_text = item.category_name.lower()

        exact_title_boost = 0.35 if normalized_query == title_text else 0.0
        title_contains_boost = 0.2 if normalized_query in title_text else 0.0
        brand_boost = 0.1 if normalized_query in brand_text else 0.0
        category_boost = 0.08 if normalized_query in category_text else 0.0
        popularity = _popularity_score(item) * 0.05
        rating_score = (item.average_rating / 5.0) * 0.05
        availability_score = 0.05 if item.stock > 0 else 0.0

        score = min(
            content_score
            + exact_title_boost
            + title_contains_boost
            + brand_boost
            + category_boost
            + popularity
            + rating_score
            + availability_score,
            1.0,
        )

        if score <= 0:
            continue

        reasons: list[str] = []
        if exact_title_boost:
            reasons.append("Exact title match")
        elif title_contains_boost:
            reasons.append("Title keyword match")
        if brand_boost:
            reasons.append(f"Brand match: {item.brand_name}")
        if category_boost:
            reasons.append(f"Category match: {item.category_name}")
        if content_score >= 0.2:
            reasons.append("TF-IDF semantic similarity")
        if item.stock > 0:
            reasons.append(item.inventory_status)

        results.append(
            SearchResult(
                item=item,
                score=round(score * 100.0, 2),
                reasons=reasons[:3] or ["Relevant catalog match"],
            )
        )

    results.sort(key=lambda entry: (-entry.score, -entry.item.average_rating, entry.item.title))
    return results[:limit] if limit else results


def classify_customer(user) -> CustomerSegment | None:
    if not user or not user.is_authenticated:
        return None

    orders = list(
        Order.objects.filter(user=user)
        .exclude(status=Order.Status.CART)
        .prefetch_related("items__item")
    )
    order_count = len(orders)
    lifetime_value = sum((order.total for order in orders), Decimal("0.00"))
    avg_order_value = float(lifetime_value / order_count) if order_count else 0.0
    wishlist_count = user.wishlist_items.count()

    if order_count == 0 and wishlist_count == 0:
        return CustomerSegment(
            code="new_explorer",
            label="New Explorer",
            confidence=0.74,
            summary="Browsing behaviour is still light, so discovery-oriented recommendations fit best.",
        )

    if avg_order_value >= 170.0 or float(lifetime_value) >= 500.0:
        return CustomerSegment(
            code="premium_buyer",
            label="Premium Buyer",
            confidence=0.82,
            summary="Order value patterns suggest this customer responds well to premium catalog recommendations.",
        )

    if order_count >= 3:
        return CustomerSegment(
            code="loyal_repeat",
            label="Loyal Repeat Customer",
            confidence=0.87,
            summary="This customer has repeat purchase behaviour and is likely to convert on curated cross-sells.",
        )

    if wishlist_count >= 3:
        return CustomerSegment(
            code="intent_researcher",
            label="Intent Researcher",
            confidence=0.79,
            summary="Wishlist-heavy activity suggests high intent with a comparison-driven buying pattern.",
        )

    return CustomerSegment(
        code="value_focused",
        label="Value Focused Shopper",
        confidence=0.71,
        summary="The behaviour pattern leans toward discounted or balanced-price items with clear utility.",
    )


def assess_customer_health(user) -> CustomerHealth | None:
    if not user or not user.is_authenticated:
        return None

    orders = list(
        Order.objects.filter(user=user)
        .exclude(status=Order.Status.CART)
        .order_by("-placed_at", "-created_at")
    )
    active_order = get_active_order(user)
    wishlist_count = user.wishlist_items.count()

    if not orders and not active_order:
        return CustomerHealth(
            retention_score=32.0,
            churn_risk="high",
            next_best_action="Drive first-order conversion with category discovery and an onboarding coupon.",
            summary="No completed purchases yet, so the customer is still early in the acquisition funnel.",
        )

    most_recent_order = orders[0] if orders else None
    recency_days = 120
    if most_recent_order:
        anchor = most_recent_order.placed_at or most_recent_order.created_at
        recency_days = max((timezone.now() - anchor).days, 0)

    order_count = len(orders)
    lifetime_value = sum((order.total for order in orders), Decimal("0.00"))
    cart_signal = active_order.total_items if active_order else 0

    recency_score = max(0.0, 1.0 - (recency_days / 120.0)) * 35.0
    frequency_score = min(order_count / 5.0, 1.0) * 25.0
    value_score = min(float(lifetime_value) / 600.0, 1.0) * 25.0
    engagement_score = min((wishlist_count + cart_signal) / 8.0, 1.0) * 15.0
    retention_score = round(recency_score + frequency_score + value_score + engagement_score, 2)

    if retention_score >= 70.0 and recency_days <= 30:
        churn_risk = "low"
        next_best_action = "Offer premium cross-sell bundles and early access to new arrivals."
        summary = "Purchase recency and repeat activity suggest a stable retained customer."
    elif retention_score >= 45.0 and recency_days <= 60:
        churn_risk = "medium"
        next_best_action = "Use replenishment reminders or targeted product recommendations to keep momentum."
        summary = "The customer is still engaged, but retention needs follow-up nudges before interest drops."
    else:
        churn_risk = "high"
        next_best_action = "Trigger a win-back flow with discount messaging, support outreach, or wishlist reminders."
        summary = "Recency and order frequency indicate a higher probability of churn without intervention."

    return CustomerHealth(
        retention_score=min(retention_score, 100.0),
        churn_risk=churn_risk,
        next_best_action=next_best_action,
        summary=summary,
    )


def suggest_support_answers(
    query: str,
    *,
    order: Order | None = None,
    limit: int = 3,
) -> list[SupportSuggestion]:
    query_tokens = _tokenize_text(query)
    if order:
        query_tokens |= _tokenize_text(order.get_status_display(), order.payment_method)

    suggestions: list[SupportSuggestion] = []
    for article in FAQ_KNOWLEDGE_BASE:
        article_tokens = set(article["keywords"])
        overlap = _jaccard_similarity(query_tokens, article_tokens)
        keyword_hits = len(query_tokens & article_tokens)
        context_boost = 0.0
        if order and "payment" in article["keywords"] and order.status == Order.Status.PAYMENT_PENDING:
            context_boost += 0.18
        if order and "return" in article["keywords"] and order.status == Order.Status.DELIVERED:
            context_boost += 0.18
        if order and "order" in article["keywords"] and order.status in {
            Order.Status.PLACED,
            Order.Status.PROCESSING,
            Order.Status.SHIPPED,
        }:
            context_boost += 0.12

        confidence = min((overlap * 0.7) + (keyword_hits * 0.08) + context_boost, 0.99)
        if confidence <= 0:
            continue
        suggestions.append(
            SupportSuggestion(
                title=article["title"],
                answer=article["answer"],
                confidence=round(confidence, 2),
            )
        )

    suggestions.sort(key=lambda suggestion: (-suggestion.confidence, suggestion.title))
    return suggestions[:limit]


def build_storefront_insights(*, user=None, limit: int = 4) -> dict:
    catalog = list(Item.objects.active().with_metrics())
    ranked_by_demand = sorted(
        catalog,
        key=lambda item: (-calculate_demand_score(item), item.title),
    )
    top_rated = sorted(
        catalog,
        key=lambda item: (-item.average_rating, -item.review_count, item.title),
    )
    low_stock = sorted(
        [item for item in catalog if item.stock <= item.reorder_level],
        key=lambda item: (estimate_days_to_stockout(item), item.stock, item.title),
    )
    value_picks = sorted(
        [item for item in catalog if item.has_discount],
        key=lambda item: (
            -calculate_demand_score(item),
            -float(item.price - item.unit_price),
            item.title,
        ),
    )

    personalized = []
    if user and user.is_authenticated:
        active_order = get_active_order(user)
        if active_order:
            personalized = recommend_for_order(active_order, limit=limit)

    return {
        "trending_items": ranked_by_demand[:limit],
        "top_rated_items": top_rated[:limit],
        "low_stock_items": low_stock[:limit],
        "value_picks": value_picks[:limit],
        "customer_segment": classify_customer(user),
        "customer_health": assess_customer_health(user),
        "personalized_recommendations": personalized,
    }
