from decimal import Decimal

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import migrations
from django.utils import timezone


CATEGORY_MAP = {
    "APP": {"name": "Apparel", "slug": "apparel", "description": "Fashion and training wear."},
    "FTW": {"name": "Footwear", "slug": "footwear", "description": "Sneakers, runners, and casual shoes."},
    "ACC": {"name": "Accessories", "slug": "accessories", "description": "Wearables and carry accessories."},
    "ELC": {"name": "Electronics", "slug": "electronics", "description": "Gadgets and connected devices."},
}

BRANDS = [
    {"name": "Redstore", "slug": "redstore", "origin_country": "Nepal", "founded_year": 2022, "is_featured": True},
    {"name": "HRX", "slug": "hrx", "origin_country": "India", "founded_year": 2013, "is_featured": True},
    {"name": "Puma", "slug": "puma", "origin_country": "Germany", "founded_year": 1948, "is_featured": True},
    {"name": "Marshall", "slug": "marshall", "origin_country": "United Kingdom", "founded_year": 1962, "is_featured": False},
    {"name": "Noise", "slug": "noise", "origin_country": "India", "founded_year": 2014, "is_featured": False},
    {"name": "Xiaomi", "slug": "xiaomi", "origin_country": "China", "founded_year": 2010, "is_featured": False},
    {"name": "Fossil", "slug": "fossil", "origin_country": "United States", "founded_year": 1984, "is_featured": False},
]


def _get_user_model(apps):
    app_label, model_name = settings.AUTH_USER_MODEL.split(".")
    return apps.get_model(app_label, model_name)


def _infer_brand(title: str) -> str:
    lowered = title.lower()
    if "hrx" in lowered:
        return "hrx"
    if "puma" in lowered:
        return "puma"
    if "marshall" in lowered:
        return "marshall"
    if "noise" in lowered:
        return "noise"
    if lowered.startswith("mi "):
        return "xiaomi"
    if "fossil" in lowered:
        return "fossil"
    return "redstore"


def _build_attributes(item):
    if item.category == "APP":
        return {"fit": "regular", "fabric": "breathable blend", "season": "all-season"}
    if item.category == "FTW":
        return {"sole": "cushioned", "fit": "regular", "usage": "daily run"}
    if item.category == "ACC":
        return {"type": "wearable accessory", "battery": "all-day", "warranty": "1 year"}
    return {"connectivity": "wireless", "warranty": "1 year", "usage": "daily"}


def _build_tags(item):
    base = [item.get("slug", "").replace("-", " "), item.get("title", "").split(" ")[0]]
    return [tag for tag in " ".join(base).lower().replace("-", " ").split() if tag]


def _item_attributes_from_instance(item):
    if item.category == "APP":
        return {"fit": "regular", "fabric": "breathable blend", "season": "all-season"}
    if item.category == "FTW":
        return {"sole": "cushioned", "fit": "regular", "usage": "daily run"}
    if item.category == "ACC":
        return {"type": "wearable accessory", "battery": "all-day", "warranty": "1 year"}
    return {"connectivity": "wireless", "warranty": "1 year", "usage": "daily"}


def _item_tags_from_instance(item):
    return [token for token in item.slug.replace("-", " ").split() if token]


def seed_advanced_entities(apps, schema_editor):
    Category = apps.get_model("dokan", "Category")
    Brand = apps.get_model("dokan", "Brand")
    Item = apps.get_model("dokan", "Item")
    Address = apps.get_model("dokan", "Address")
    Coupon = apps.get_model("dokan", "Coupon")
    Order = apps.get_model("dokan", "Order")
    OrderItem = apps.get_model("dokan", "OrderItem")
    OrderStatusEvent = apps.get_model("dokan", "OrderStatusEvent")
    ProductReview = apps.get_model("dokan", "ProductReview")
    WishlistItem = apps.get_model("dokan", "WishlistItem")
    User = _get_user_model(apps)

    category_lookup = {}
    for sort_order, (legacy_code, payload) in enumerate(CATEGORY_MAP.items(), start=1):
        category, _ = Category.objects.update_or_create(
            slug=payload["slug"],
            defaults={
                "name": payload["name"],
                "description": payload["description"],
                "sort_order": sort_order,
                "is_active": True,
            },
        )
        category_lookup[legacy_code] = category

    brand_lookup = {}
    for payload in BRANDS:
        brand, _ = Brand.objects.update_or_create(
            slug=payload["slug"],
            defaults=payload,
        )
        brand_lookup[payload["slug"]] = brand

    view_scores = [185, 160, 142, 138, 122, 108, 94, 88, 134, 176, 116, 83]
    trending_slugs = {
        "redstore-performance-tee",
        "hrx-velocity-runner",
        "noise-matrix-smartwatch",
        "mi-power-bank-max",
    }

    for index, item in enumerate(Item.objects.all().order_by("id"), start=1):
        brand_slug = _infer_brand(item.title)
        item.catalog_category = category_lookup.get(item.category)
        item.brand = brand_lookup.get(brand_slug)
        item.sku = item.sku or f"RS-2022-{index:03d}"
        item.image_gallery = ["images/gallery-1.jpg", "images/gallery-2.jpg", "images/gallery-3.jpg"]
        item.attributes = _item_attributes_from_instance(item)
        item.tags = _item_tags_from_instance(item)
        item.reorder_level = 5 if item.category != "FTW" else 3
        item.launch_year = 2022
        item.view_count = view_scores[index - 1] if index <= len(view_scores) else 60
        item.is_trending = item.slug in trending_slugs
        item.save()

    Coupon.objects.filter(code="WELCOME10").update(
        discount_type="fixed",
        minimum_order_value=Decimal("80.00"),
        active=True,
        valid_from=timezone.now() - timezone.timedelta(days=30),
        valid_until=timezone.now() + timezone.timedelta(days=365),
        max_uses=500,
    )

    demo_users = [
        {"username": "demo_buyer", "email": "demo_buyer@example.com"},
        {"username": "campus_shopper", "email": "campus_shopper@example.com"},
        {"username": "gadget_hunter", "email": "gadget_hunter@example.com"},
    ]
    user_lookup = {}
    for payload in demo_users:
        user, _ = User.objects.update_or_create(
            username=payload["username"],
            defaults={
                "email": payload["email"],
                "password": make_password("demo12345"),
                "is_active": True,
            },
        )
        user_lookup[payload["username"]] = user

    address_lookup = {}
    for username, city, country in (
        ("demo_buyer", "Kathmandu", "Nepal"),
        ("campus_shopper", "Pokhara", "Nepal"),
        ("gadget_hunter", "Lalitpur", "Nepal"),
    ):
        user = user_lookup[username]
        shipping, _ = Address.objects.update_or_create(
            user=user,
            address_type="shipping",
            street_address=f"{city} Main Street",
            defaults={
                "full_name": user.username.replace("_", " ").title(),
                "phone_number": "9800000000",
                "apartment_address": "Block A",
                "city": city,
                "state": "Bagmati",
                "country": country,
                "postal_code": "44600",
                "default": True,
            },
        )
        billing, _ = Address.objects.update_or_create(
            user=user,
            address_type="billing",
            street_address=f"{city} Main Street",
            defaults={
                "full_name": user.username.replace("_", " ").title(),
                "phone_number": "9800000000",
                "apartment_address": "Block A",
                "city": city,
                "state": "Bagmati",
                "country": country,
                "postal_code": "44600",
                "default": True,
            },
        )
        address_lookup[username] = {"shipping": shipping, "billing": billing}

    order_specs = [
        {
            "reference": "RST2022A01",
            "user": "demo_buyer",
            "status": "delivered",
            "payment_method": "cash_on_delivery",
            "items": [
                ("redstore-performance-tee", 2),
                ("puma-blue-motion-tee", 1),
            ],
            "events": [
                ("placed", "Order received by Redstore."),
                ("processing", "Packed and moved to warehouse dispatch."),
                ("shipped", "Shipment handed to delivery partner."),
                ("delivered", "Delivered successfully."),
            ],
        },
        {
            "reference": "RST2022A02",
            "user": "campus_shopper",
            "status": "shipped",
            "payment_method": "card_on_delivery",
            "items": [
                ("hrx-velocity-runner", 1),
                ("city-sprint-sneakers", 1),
            ],
            "events": [
                ("placed", "Order confirmed."),
                ("processing", "Quality check completed."),
                ("shipped", "Package is in transit."),
            ],
        },
        {
            "reference": "RST2022A03",
            "user": "gadget_hunter",
            "status": "delivered",
            "payment_method": "bank_transfer",
            "items": [
                ("noise-matrix-smartwatch", 1),
                ("mi-power-bank-max", 2),
            ],
            "events": [
                ("placed", "Order created via direct transfer."),
                ("processing", "Payment reconciled and order packed."),
                ("shipped", "Shipment dispatched."),
                ("delivered", "Delivery completed."),
            ],
        },
    ]

    for order_spec in order_specs:
        user = user_lookup[order_spec["user"]]
        coupon = Coupon.objects.filter(code="WELCOME10").first()
        order, _ = Order.objects.update_or_create(
            reference=order_spec["reference"],
            defaults={
                "user": user,
                "status": order_spec["status"],
                "payment_method": order_spec["payment_method"],
                "shipping_address": address_lookup[order_spec["user"]]["shipping"],
                "billing_address": address_lookup[order_spec["user"]]["billing"],
                "coupon": coupon,
                "customer_note": "Seeded historical order for analytics.",
                "estimated_delivery_days": 4,
                "placed_at": timezone.now() - timezone.timedelta(days=10),
            },
        )
        order.items.clear()
        for slug, quantity in order_spec["items"]:
            item = Item.objects.get(slug=slug)
            order_item, _ = OrderItem.objects.update_or_create(
                user=user,
                item=item,
                ordered=True,
                defaults={"quantity": quantity},
            )
            order.items.add(order_item)
        OrderStatusEvent.objects.filter(order=order).delete()
        for status, note in order_spec["events"]:
            OrderStatusEvent.objects.create(
                order=order,
                status=status,
                note=note,
                actor="redstore-system",
            )

    review_specs = [
        ("demo_buyer", "redstore-performance-tee", 5, "Great daily tee", "Comfortable fit and good value for money."),
        ("demo_buyer", "puma-blue-motion-tee", 4, "Solid fit", "Good color, easy to style, and light for daily wear."),
        ("campus_shopper", "hrx-velocity-runner", 5, "Excellent runners", "Comfortable sole and stable fit for long walks."),
        ("gadget_hunter", "noise-matrix-smartwatch", 4, "Useful smartwatch", "Display is sharp and notifications work well."),
        ("gadget_hunter", "mi-power-bank-max", 5, "Reliable backup", "Very handy for travel days and charges quickly."),
    ]
    for username, item_slug, rating, title, comment in review_specs:
        ProductReview.objects.update_or_create(
            user=user_lookup[username],
            item=Item.objects.get(slug=item_slug),
            defaults={
                "rating": rating,
                "title": title,
                "comment": comment,
                "verified_purchase": True,
                "approved": True,
            },
        )

    wishlist_specs = [
        ("demo_buyer", "noise-matrix-smartwatch"),
        ("campus_shopper", "fossil-steel-watch"),
        ("campus_shopper", "mi-power-bank-max"),
        ("gadget_hunter", "hrx-velocity-runner"),
    ]
    for username, item_slug in wishlist_specs:
        WishlistItem.objects.update_or_create(
            user=user_lookup[username],
            item=Item.objects.get(slug=item_slug),
        )


def unseed_advanced_entities(apps, schema_editor):
    Category = apps.get_model("dokan", "Category")
    Brand = apps.get_model("dokan", "Brand")
    Order = apps.get_model("dokan", "Order")
    ProductReview = apps.get_model("dokan", "ProductReview")
    WishlistItem = apps.get_model("dokan", "WishlistItem")
    User = _get_user_model(apps)

    ProductReview.objects.filter(
        user__username__in=["demo_buyer", "campus_shopper", "gadget_hunter"]
    ).delete()
    WishlistItem.objects.filter(
        user__username__in=["demo_buyer", "campus_shopper", "gadget_hunter"]
    ).delete()
    Order.objects.filter(reference__in=["RST2022A01", "RST2022A02", "RST2022A03"]).delete()
    User.objects.filter(username__in=["demo_buyer", "campus_shopper", "gadget_hunter"]).delete()
    Brand.objects.filter(slug__in=["redstore", "hrx", "puma", "marshall", "noise", "xiaomi", "fossil"]).delete()
    Category.objects.filter(slug__in=["apparel", "footwear", "accessories", "electronics"]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("dokan", "0003_brand_alter_item_options_address_phone_number_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_advanced_entities, unseed_advanced_entities),
    ]
