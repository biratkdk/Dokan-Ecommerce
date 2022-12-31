from django.db import migrations


# All 12 seeded catalog items were given the exact same three gallery
# thumbnails ("images/gallery-1.jpg", "-2.jpg", "-3.jpg") by migration 0004,
# so every product detail page showed identical extra photos. This assigns
# each item a distinct rotation of the other seeded product images instead.
PRODUCT_IMAGE_COUNT = 12
GALLERY_OFFSETS = (3, 6, 9)


def diversify_gallery_images(apps, schema_editor):
    Item = apps.get_model("dokan", "Item")

    items = list(Item.objects.all().order_by("id"))
    for position, item in enumerate(items):
        gallery = [
            f"images/product-{((position + offset) % PRODUCT_IMAGE_COUNT) + 1}.jpg"
            for offset in GALLERY_OFFSETS
        ]
        item.image_gallery = gallery
        item.save(update_fields=["image_gallery"])


def revert_gallery_images(apps, schema_editor):
    Item = apps.get_model("dokan", "Item")
    Item.objects.update(
        image_gallery=["images/gallery-1.jpg", "images/gallery-2.jpg", "images/gallery-3.jpg"]
    )


class Migration(migrations.Migration):
    dependencies = [
        ("dokan", "0011_seed_recommendation_training_data"),
    ]

    operations = [
        migrations.RunPython(diversify_gallery_images, revert_gallery_images),
    ]
