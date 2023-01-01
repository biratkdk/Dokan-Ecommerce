from collections import defaultdict

from django.db import migrations


# Migration 0002 assigned "images/product-N.jpg" to items purely by seed
# order, with zero regard for what each photo actually shows. The result:
# a FOSSIL-branded watch photo (product-8.jpg) was sitting on a Puma tee,
# while the actual "Fossil Steel Watch" product showed a pair of Nike
# sweatpants (product-12.jpg). Smartwatch and power-bank products showed
# sneaker photos. This corrects the mapping to the closest real match
# available in the existing static/images asset pool (verified by manual
# visual inspection of each file), and re-derives the gallery rotation
# (0013's logic) so it stays consistent with the corrected primary photos.
CORRECTED_IMAGE_URL_BY_SLUG = {
    "redstore-performance-tee": "images/product-1.jpg",
    "hrx-velocity-runner": "images/product-2.jpg",
    "urban-flex-trousers": "images/product-3.jpg",
    "puma-blue-motion-tee": "images/product-4.jpg",
    "core-active-polo": "images/product-12.jpg",
    "city-sprint-sneakers": "images/product-10.jpg",
    "classic-street-shirt": "images/product-11.jpg",
    "puma-blue-everyday-tee": "images/product-6.jpg",
    "marshall-pulse-speaker": "images/product-7.jpg",
    "noise-matrix-smartwatch": "images/product-9.jpg",
    "mi-power-bank-max": "images/product-5.jpg",
    "fossil-steel-watch": "images/product-8.jpg",
}

GALLERY_SIZE = 3


def fix_images_and_regenerate_galleries(apps, schema_editor):
    Item = apps.get_model("dokan", "Item")

    items = list(Item.objects.all().order_by("id"))
    for item in items:
        corrected_url = CORRECTED_IMAGE_URL_BY_SLUG.get(item.slug)
        if corrected_url:
            item.image_url = corrected_url
            item.save(update_fields=["image_url"])

    items = list(Item.objects.all().order_by("id"))
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


def noop_reverse(apps, schema_editor):
    # No meaningful way to restore the original broken assignment; leave
    # images as corrected rather than reintroducing the mismatch bug.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("dokan", "0014_customerprofile_email_verification_attempts_and_more"),
    ]

    operations = [
        migrations.RunPython(fix_images_and_regenerate_galleries, noop_reverse),
    ]
