from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Sequence

from django.utils import timezone

from .models import Item, Order
from .services import get_active_order


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


def _tokenize_item(item: Item) -> set[str]:
    item_parts: list[object] = [
        item.title,
        item.short_description,
        item.description,
        item.category_name,
        item.brand_name,
        item.sku,
    ]
    item_parts.extend(str(tag) for tag in item.tags)
    for key, value in item.attributes.items():
        item_parts.append(key)
        item_parts.append(value)
    return _tokenize_text(*item_parts)


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _price_similarity(source: Item, candidate: Item) -> float:
    source_price = float(source.unit_price)
    candidate_price = float(candidate.unit_price)
    denominator = max(source_price, candidate_price, 1.0)
    gap = abs(source_price - candidate_price) / denominator
    return max(0.0, 1.0 - gap)


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


def recommend_items(
    source: Item,
    *,
    pool: Iterable[Item] | None = None,
    limit: int = 4,
) -> list[Recommendation]:
    pool = pool or Item.objects.active().with_metrics().exclude(pk=source.pk)
    source_tokens = _tokenize_item(source)
    recommendations: list[Recommendation] = []

    for candidate in pool:
        if candidate.pk == source.pk:
            continue

        candidate_tokens = _tokenize_item(candidate)
        category_score = (
            1.0
            if candidate.catalog_category_id == source.catalog_category_id
            else 0.4
            if candidate.category == source.category
            else 0.0
        )
        brand_score = 1.0 if source.brand_id and candidate.brand_id == source.brand_id else 0.0
        token_score = _jaccard_similarity(source_tokens, candidate_tokens)
        price_score = _price_similarity(source, candidate)
        popularity = _popularity_score(candidate)
        rating_score = candidate.average_rating / 5.0
        discount_bonus = 0.05 if candidate.has_discount else 0.0

        score = (
            category_score * 0.32
            + brand_score * 0.18
            + token_score * 0.18
            + price_score * 0.16
            + popularity * 0.08
            + rating_score * 0.08
            + discount_bonus
        )

        reasons: list[str] = []
        if category_score >= 1.0:
            reasons.append(f"Same category: {source.category_name}")
        if brand_score >= 1.0:
            reasons.append(f"Same brand: {source.brand_name}")
        if token_score >= 0.2:
            reasons.append("Similar product attributes and keywords")
        if price_score >= 0.7:
            reasons.append("Comparable price range")
        if candidate.average_rating >= 4.0:
            reasons.append("Strong customer rating")

        recommendations.append(
            Recommendation(
                item=candidate,
                score=round(score * 100.0, 2),
                reasons=reasons[:3] or ["Good portfolio fit for this product"],
            )
        )

    recommendations.sort(
        key=lambda entry: (-entry.score, -entry.item.average_rating, entry.item.title)
    )
    return recommendations[:limit]


def recommend_for_order(order: Order, *, limit: int = 4) -> list[Recommendation]:
    cart_items = [order_item.item for order_item in order.items.select_related("item")]
    if not cart_items:
        return []

    pool = list(
        Item.objects.active().with_metrics().exclude(pk__in=[item.pk for item in cart_items])
    )
    aggregated: dict[int, Recommendation] = {}

    for source in cart_items:
        for recommendation in recommend_items(source, pool=pool, limit=limit * 2):
            existing = aggregated.get(recommendation.item.pk)
            if not existing or recommendation.score > existing.score:
                aggregated[recommendation.item.pk] = recommendation

    return sorted(
        aggregated.values(),
        key=lambda entry: (-entry.score, entry.item.title),
    )[:limit]


def rank_catalog_search(
    query: str,
    *,
    queryset: Sequence[Item] | Iterable[Item] | None = None,
    limit: int | None = None,
) -> list[SearchResult]:
    query_tokens = _tokenize_text(query)
    if not query_tokens:
        return []

    catalog = queryset or Item.objects.active().with_metrics()
    results: list[SearchResult] = []
    normalized_query = query.lower()

    for item in catalog:
        item_tokens = _tokenize_item(item)
        token_score = _jaccard_similarity(query_tokens, item_tokens)
        title_text = item.title.lower()
        brand_text = item.brand_name.lower()
        category_text = item.category_name.lower()
        description_text = f"{item.short_description} {item.description}".lower()

        exact_title_boost = 1.0 if normalized_query == title_text else 0.0
        title_contains_boost = 0.7 if normalized_query in title_text else 0.0
        brand_boost = 0.45 if normalized_query in brand_text else 0.0
        category_boost = 0.35 if normalized_query in category_text else 0.0
        description_boost = 0.2 if normalized_query in description_text else 0.0
        popularity = _popularity_score(item)
        rating_score = item.average_rating / 5.0
        availability_score = 0.15 if item.stock > 0 else 0.0
        discount_bonus = 0.05 if item.has_discount else 0.0

        score = (
            exact_title_boost * 0.35
            + title_contains_boost * 0.22
            + brand_boost * 0.12
            + category_boost * 0.08
            + description_boost * 0.05
            + token_score * 0.22
            + popularity * 0.06
            + rating_score * 0.05
            + availability_score
            + discount_bonus
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
        if token_score >= 0.2:
            reasons.append("Description and attribute similarity")
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
