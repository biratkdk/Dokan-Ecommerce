import random

from django.conf import settings
from django.db import migrations
from django.utils import timezone


def _get_user_model(apps):
    app_label, model_name = settings.AUTH_USER_MODEL.split(".")
    return apps.get_model(app_label, model_name)


# Affinity groups describe which products tend to sell together in the same
# basket. They are used to generate structured (not purely random) historical
# order data so the item-based collaborative filtering model in
# dokan/intelligence.py has a real co-purchase signal to learn from and
# `evaluate_recommendations` has something meaningful to score against a
# popularity baseline.
AFFINITY_GROUPS = [
    ["redstore-performance-tee", "urban-flex-trousers", "core-active-polo"],
    ["hrx-velocity-runner", "city-sprint-sneakers", "core-active-polo"],
    ["puma-blue-motion-tee", "puma-blue-everyday-tee", "classic-street-shirt"],
    ["marshall-pulse-speaker", "noise-matrix-smartwatch", "mi-power-bank-max"],
    ["fossil-steel-watch", "classic-street-shirt", "urban-flex-trousers"],
]

TRAINING_USERNAMES = [f"training_shopper_{index:02d}" for index in range(1, 13)]


def seed_training_orders(apps, schema_editor):
    Item = apps.get_model("dokan", "Item")
    Order = apps.get_model("dokan", "Order")
    OrderItem = apps.get_model("dokan", "OrderItem")
    OrderStatusEvent = apps.get_model("dokan", "OrderStatusEvent")
    User = _get_user_model(apps)

    rng = random.Random(2022)

    item_lookup = {}
    for group in AFFINITY_GROUPS:
        for slug in group:
            if slug not in item_lookup:
                item_lookup[slug] = Item.objects.filter(slug=slug).first()
    item_lookup = {slug: item for slug, item in item_lookup.items() if item is not None}
    if not item_lookup:
        return

    usable_groups = [
        [slug for slug in group if slug in item_lookup]
        for group in AFFINITY_GROUPS
    ]
    usable_groups = [group for group in usable_groups if len(group) >= 2]
    if not usable_groups:
        return

    users = []
    for username in TRAINING_USERNAMES:
        user, _ = User.objects.get_or_create(
            username=username,
            defaults={"email": f"{username}@example.com", "is_active": True},
        )
        users.append(user)

    order_index = 0
    for user in users:
        orders_for_user = rng.randint(3, 5)
        for _ in range(orders_for_user):
            group = rng.choice(usable_groups)
            basket_size = rng.randint(2, min(3, len(group)))
            basket_slugs = rng.sample(group, basket_size)

            order_index += 1
            reference = f"TRN{order_index:04d}"
            days_ago = rng.randint(15, 300)
            order = Order.objects.create(
                user=user,
                reference=reference,
                status="delivered",
                payment_method="card_on_delivery",
                payment_status="paid",
                customer_note="Seeded historical order for recommendation model training.",
                estimated_delivery_days=4,
                placed_at=timezone.now() - timezone.timedelta(days=days_ago),
                paid_at=timezone.now() - timezone.timedelta(days=days_ago),
            )
            for slug in basket_slugs:
                order_item = OrderItem.objects.create(
                    user=user,
                    item=item_lookup[slug],
                    ordered=True,
                    quantity=rng.randint(1, 2),
                )
                order.items.add(order_item)
            OrderStatusEvent.objects.create(
                order=order,
                status="delivered",
                note="Seeded delivery event for training order.",
                actor="redstore-system",
            )


def unseed_training_orders(apps, schema_editor):
    Order = apps.get_model("dokan", "Order")
    User = _get_user_model(apps)

    Order.objects.filter(reference__startswith="TRN").delete()
    User.objects.filter(username__in=TRAINING_USERNAMES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("dokan", "0010_emailnotification_attempt_count_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_training_orders, unseed_training_orders),
    ]
