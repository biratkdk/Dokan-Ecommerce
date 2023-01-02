from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Category, Item


class ItemSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.8

    def items(self):
        return Item.objects.active()

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return obj.get_absolute_url()


class CategorySitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.6

    def items(self):
        return Category.objects.filter(is_active=True)

    def location(self, obj):
        return f"{reverse('store:catalog')}?category={obj.slug}"


class StaticViewSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.5

    def items(self):
        return ["store:home", "store:catalog", "store:insights", "store:compare"]

    def location(self, item):
        return reverse(item)


sitemaps = {
    "products": ItemSitemap,
    "categories": CategorySitemap,
    "static": StaticViewSitemap,
}
