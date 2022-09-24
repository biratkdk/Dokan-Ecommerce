from __future__ import annotations

from .models import Item


COMPARE_SESSION_KEY = "compare_item_ids"
RECENTLY_VIEWED_SESSION_KEY = "recently_viewed_item_ids"
MAX_COMPARE_ITEMS = 4
MAX_RECENTLY_VIEWED_ITEMS = 8


def _normalized_ids(values) -> list[int]:
    normalized = []
    seen = set()
    for value in values or []:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed in seen:
            continue
        normalized.append(parsed)
        seen.add(parsed)
    return normalized


def _save_ids(request, key: str, ids: list[int]) -> None:
    request.session[key] = ids
    request.session.modified = True


def get_compare_ids(request) -> list[int]:
    return _normalized_ids(request.session.get(COMPARE_SESSION_KEY, []))


def get_compare_items(request):
    ids = get_compare_ids(request)
    items_by_id = {
        item.pk: item
        for item in Item.objects.active().with_metrics().filter(pk__in=ids)
    }
    return [items_by_id[item_id] for item_id in ids if item_id in items_by_id]


def is_in_compare(request, item: Item) -> bool:
    return item.pk in get_compare_ids(request)


def toggle_compare_item(request, item: Item) -> dict:
    compare_ids = get_compare_ids(request)
    added = item.pk not in compare_ids
    trimmed = False

    if added:
        compare_ids.append(item.pk)
        if len(compare_ids) > MAX_COMPARE_ITEMS:
            compare_ids = compare_ids[-MAX_COMPARE_ITEMS:]
            trimmed = True
    else:
        compare_ids = [item_id for item_id in compare_ids if item_id != item.pk]

    _save_ids(request, COMPARE_SESSION_KEY, compare_ids)
    return {
        "added": added,
        "count": len(compare_ids),
        "trimmed": trimmed,
    }


def clear_compare_items(request) -> None:
    _save_ids(request, COMPARE_SESSION_KEY, [])


def register_recently_viewed_item(request, item: Item) -> None:
    recent_ids = _normalized_ids(request.session.get(RECENTLY_VIEWED_SESSION_KEY, []))
    recent_ids = [item_id for item_id in recent_ids if item_id != item.pk]
    recent_ids.insert(0, item.pk)
    _save_ids(request, RECENTLY_VIEWED_SESSION_KEY, recent_ids[:MAX_RECENTLY_VIEWED_ITEMS])


def get_recently_viewed_items(request, *, limit: int = 4, exclude_item: Item | None = None):
    ids = _normalized_ids(request.session.get(RECENTLY_VIEWED_SESSION_KEY, []))
    if exclude_item:
        ids = [item_id for item_id in ids if item_id != exclude_item.pk]
    ids = ids[:limit]
    items_by_id = {
        item.pk: item
        for item in Item.objects.active().with_metrics().filter(pk__in=ids)
    }
    return [items_by_id[item_id] for item_id in ids if item_id in items_by_id]
