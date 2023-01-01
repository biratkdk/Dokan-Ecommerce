from collections import defaultdict

from django.db import migrations


# 0013/0015 padded each item's gallery to a fixed size of 3 by pulling in
# photos from unrelated categories whenever a category had fewer than 3
# same-category items (e.g. a smartwatch's gallery included a t-shirt and a
# power bank). This regenerates galleries using only same-category images,
# so a product with 2 same-category peers gets a 2-image gallery instead of
# a padded-out 3-image gallery full of unrelated products.
def stop_cross_category_padding(apps, schema_editor):
    Item = apps.get_model("dokan", "Item")

    items = list(Item.objects.all().order_by("id"))
    by_category: dict[str, list] = defaultdict(list)
    for item in items:
        by_category[item.category].append(item)

    for item in items:
        same_category = [
            other.image_url
            for other in by_category[item.category]
            if other.pk != item.pk and other.image_url
        ]
        item.image_gallery = same_category
        item.save(update_fields=["image_gallery"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("dokan", "0015_fix_mismatched_product_images"),
    ]

    operations = [
        migrations.RunPython(stop_cross_category_padding, noop_reverse),
    ]
