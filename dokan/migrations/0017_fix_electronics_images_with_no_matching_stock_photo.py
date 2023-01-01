from collections import defaultdict

from django.db import migrations


# The seed asset pack (static/images/product-1.jpg..product-12.jpg) is a
# generic apparel/footwear/watch stock-photo set with zero speaker or
# power-bank photography in it. 0015's "corrected" mapping still assigned
# "Mi Power Bank Max" to product-5.jpg (actually a pair of sneakers) and
# "Marshall Pulse Speaker" to product-7.jpg (actually a 3-pack of socks) --
# category-breaking mismatches, not just wrong-brand stock photos. There is
# no genuine electronics photo anywhere in the asset pool, so this reuses
# exclusive.png (the fitness-band image already used as the site's featured
# gadget photo) for these two items -- the only asset that actually reads as
# consumer electronics -- instead of leaving them on apparel/footwear photos.
GADGET_FALLBACK_IMAGE = "images/exclusive.png"

CORRECTED_SLUGS = ["mi-power-bank-max", "marshall-pulse-speaker"]

GALLERY_SIZE = 3


def fix_electronics_images(apps, schema_editor):
    Item = apps.get_model("dokan", "Item")

    for slug in CORRECTED_SLUGS:
        Item.objects.filter(slug=slug).update(image_url=GADGET_FALLBACK_IMAGE)

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
        ("dokan", "0016_stop_cross_category_gallery_padding"),
    ]

    operations = [
        migrations.RunPython(fix_electronics_images, noop_reverse),
    ]
