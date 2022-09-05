from decimal import Decimal

from django.db import migrations


ITEMS = [
    {
        "title": "Redstore Performance Tee",
        "slug": "redstore-performance-tee",
        "category": "APP",
        "label": "FEATURED",
        "price": Decimal("49.99"),
        "discount_price": Decimal("39.99"),
        "short_description": "Breathable cotton tee for everyday training.",
        "description": "A lightweight tee designed for gym sessions, daily wear, and the kind of fit that works across seasons.",
        "image_url": "images/product-1.jpg",
        "stock": 18,
        "featured": True,
    },
    {
        "title": "HRX Velocity Runner",
        "slug": "hrx-velocity-runner",
        "category": "FTW",
        "label": "FEATURED",
        "price": Decimal("129.99"),
        "discount_price": Decimal("109.99"),
        "short_description": "Responsive trainers with an all-day comfort sole.",
        "description": "Built with a stable base, cushioned midsole, and flexible upper for long walks or quick city miles.",
        "image_url": "images/product-2.jpg",
        "stock": 10,
        "featured": True,
    },
    {
        "title": "Urban Flex Trousers",
        "slug": "urban-flex-trousers",
        "category": "APP",
        "label": "NEW",
        "price": Decimal("74.99"),
        "discount_price": Decimal("64.99"),
        "short_description": "Clean tapered trousers with stretch comfort.",
        "description": "Smart enough for work, relaxed enough for weekends, with fabric that moves naturally throughout the day.",
        "image_url": "images/product-3.jpg",
        "stock": 14,
        "featured": True,
    },
    {
        "title": "Puma Blue Motion Tee",
        "slug": "puma-blue-motion-tee",
        "category": "APP",
        "label": "SALE",
        "price": Decimal("44.99"),
        "discount_price": Decimal("34.99"),
        "short_description": "Soft blend fabric with bold everyday styling.",
        "description": "This casual performance tee brings a sport-inspired look with a lightweight, breathable finish.",
        "image_url": "images/product-4.jpg",
        "stock": 21,
        "featured": True,
    },
    {
        "title": "Core Active Polo",
        "slug": "core-active-polo",
        "category": "APP",
        "label": "NEW",
        "price": Decimal("58.00"),
        "discount_price": Decimal("49.00"),
        "short_description": "Sharper than a tee, lighter than a formal shirt.",
        "description": "A structured polo with breathable fabric and a polished finish for a casual-smart wardrobe.",
        "image_url": "images/product-5.jpg",
        "stock": 15,
        "featured": False,
    },
    {
        "title": "City Sprint Sneakers",
        "slug": "city-sprint-sneakers",
        "category": "FTW",
        "label": "NEW",
        "price": Decimal("119.00"),
        "discount_price": Decimal("99.00"),
        "short_description": "Street-ready sneakers with lightweight support.",
        "description": "Balanced cushioning, confident grip, and a shape that works with joggers, denim, or shorts.",
        "image_url": "images/product-6.jpg",
        "stock": 11,
        "featured": False,
    },
    {
        "title": "Classic Street Shirt",
        "slug": "classic-street-shirt",
        "category": "APP",
        "label": "SALE",
        "price": Decimal("62.50"),
        "discount_price": Decimal("49.50"),
        "short_description": "Relaxed fit and clean graphic details.",
        "description": "An easy layer that pairs bold color with a simple silhouette built for daily wear.",
        "image_url": "images/product-7.jpg",
        "stock": 16,
        "featured": False,
    },
    {
        "title": "Puma Blue Everyday Tee",
        "slug": "puma-blue-everyday-tee",
        "category": "APP",
        "label": "SALE",
        "price": Decimal("39.99"),
        "discount_price": Decimal("29.99"),
        "short_description": "A reliable everyday tee with a cleaner cut.",
        "description": "Soft, versatile, and easy to pair with denim, joggers, or layered fits.",
        "image_url": "images/product-8.jpg",
        "stock": 20,
        "featured": False,
    },
    {
        "title": "Marshall Pulse Speaker",
        "slug": "marshall-pulse-speaker",
        "category": "ELC",
        "label": "NEW",
        "price": Decimal("189.00"),
        "discount_price": Decimal("169.00"),
        "short_description": "Compact speaker with room-filling sound.",
        "description": "Wireless playback, balanced tuning, and a compact format built for desks, shelves, and workspaces.",
        "image_url": "images/product-9.jpg",
        "stock": 8,
        "featured": False,
    },
    {
        "title": "Noise Matrix Smartwatch",
        "slug": "noise-matrix-smartwatch",
        "category": "ACC",
        "label": "FEATURED",
        "price": Decimal("149.00"),
        "discount_price": Decimal("129.00"),
        "short_description": "AMOLED smartwatch with fitness tracking.",
        "description": "Tracks activity, keeps notifications in view, and delivers a bright wearable display for everyday use.",
        "image_url": "images/product-10.jpg",
        "stock": 12,
        "featured": False,
    },
    {
        "title": "Mi Power Bank Max",
        "slug": "mi-power-bank-max",
        "category": "ACC",
        "label": "NEW",
        "price": Decimal("59.00"),
        "discount_price": Decimal("49.00"),
        "short_description": "High-capacity backup power for travel days.",
        "description": "Fast charging support, compact body, and enough battery to keep multiple devices running on the move.",
        "image_url": "images/product-11.jpg",
        "stock": 25,
        "featured": False,
    },
    {
        "title": "Fossil Steel Watch",
        "slug": "fossil-steel-watch",
        "category": "ACC",
        "label": "SALE",
        "price": Decimal("210.00"),
        "discount_price": Decimal("179.00"),
        "short_description": "Premium steel watch with a clean modern dial.",
        "description": "A dressed-up accessory that still fits everyday use, with durable materials and an understated finish.",
        "image_url": "images/product-12.jpg",
        "stock": 7,
        "featured": False,
    },
]


def seed_store_data(apps, schema_editor):
    Item = apps.get_model("dokan", "Item")
    Coupon = apps.get_model("dokan", "Coupon")

    for item_data in ITEMS:
        Item.objects.update_or_create(slug=item_data["slug"], defaults=item_data)

    Coupon.objects.update_or_create(
        code="WELCOME10",
        defaults={"amount": Decimal("10.00"), "active": True},
    )


def unseed_store_data(apps, schema_editor):
    Item = apps.get_model("dokan", "Item")
    Coupon = apps.get_model("dokan", "Coupon")

    slugs = [item["slug"] for item in ITEMS]
    Item.objects.filter(slug__in=slugs).delete()
    Coupon.objects.filter(code="WELCOME10").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("dokan", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_store_data, unseed_store_data),
    ]
