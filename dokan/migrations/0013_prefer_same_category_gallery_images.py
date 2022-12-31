from collections import defaultdict

from django.db import migrations


# 0012 diversified the gallery images so no two products showed identical
# thumbnails, but it rotated across the *entire* catalog regardless of
# category -- so a t-shirt's gallery could show a smartwatch or a pair of
# sneakers. This prefers other products in the same department first, only
# falling back to cross-category images to fill out the remaining slots when
# a department doesn't have enough members of its own.
GALLERY_SIZE = 3


def prefer_same_category_gallery_images(apps, schema_editor):
    Item = apps.get_model("dokan", "Item")

    items = list(Item.objects.all().order_by("id"))
    if not items:
        return

    by_category: dict[str, list] = defaultdict(list)
    for item in items:
        by_category[item.category].append(item)

    all_image_urls = [item.image_url for item in items if item.image_url]

    for item in items:
        same_category = [
            other.image_url
            for other in by_category[item.category]
            if other.pk != item.pk and other.image_url
        ]

        gallery = same_category[:GALLERY_SIZE]
        if len(gallery) < GALLERY_SIZE:
            fallback_pool = [
                url for url in all_image_urls if url not in gallery and url != item.image_url
            ]
            needed = GALLERY_SIZE - len(gallery)
            gallery.extend(fallback_pool[:needed])

        item.image_gallery = gallery
        item.save(update_fields=["image_gallery"])


def revert_to_cross_category_rotation(apps, schema_editor):
    # No meaningful way to restore the exact prior rotation; leave galleries
    # as-is on reverse rather than reintroducing the duplicate-image bug.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("dokan", "0012_diversify_product_gallery_images"),
    ]

    operations = [
        migrations.RunPython(
            prefer_same_category_gallery_images, revert_to_cross_category_rotation
        ),
    ]
