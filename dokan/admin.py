from django.contrib import admin
from django.template.response import TemplateResponse
from django.urls import path

from .admin_dashboard import build_admin_dashboard
from .models import (
    Address,
    Brand,
    Category,
    Coupon,
    CustomerProfile,
    EmailNotification,
    InventoryReservation,
    Item,
    LoginActivity,
    Order,
    OrderItem,
    OrderStatusEvent,
    ProductImage,
    ProductReview,
    ReturnRequest,
    StockLevel,
    StockMovement,
    SupportMessage,
    SupportThread,
    Warehouse,
    WishlistItem,
)


def analytics_dashboard_view(request):
    request.current_app = admin.site.name
    context = {
        **admin.site.each_context(request),
        "title": "Store analytics",
        "subtitle": "Operations dashboard",
        **build_admin_dashboard(),
    }
    return TemplateResponse(request, "admin/analytics_dashboard.html", context)


_default_get_urls = admin.site.get_urls


def _get_admin_urls():
    custom_urls = [
        path(
            "analytics/",
            admin.site.admin_view(analytics_dashboard_view),
            name="redstore-analytics",
        ),
    ]
    return custom_urls + _default_get_urls()


admin.site.get_urls = _get_admin_urls
admin.site.index_template = "admin/redstore_index.html"
admin.site.site_header = "Redstore administration"
admin.site.site_title = "Redstore admin"
admin.site.index_title = "Store operations"


class ProductReviewInline(admin.TabularInline):
    model = ProductReview
    extra = 0
    fields = ("user", "rating", "title", "verified_purchase", "approved")


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0
    fields = ("image", "alt_text", "sort_order", "is_primary")


class StockLevelInline(admin.TabularInline):
    model = StockLevel
    extra = 0
    fields = ("warehouse", "on_hand", "reserved", "safety_stock", "updated_at")
    readonly_fields = ("warehouse", "on_hand", "reserved", "safety_stock", "updated_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "is_active", "sort_order")
    list_filter = ("is_active",)
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "description")


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "origin_country", "founded_year", "is_featured", "is_active")
    list_filter = ("is_featured", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "description", "origin_country")


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "sku",
        "catalog_category",
        "brand",
        "price",
        "discount_price",
        "stock",
        "reserved_units",
        "warehouse_count",
        "featured",
        "is_trending",
        "is_active",
    )
    list_filter = ("catalog_category", "brand", "featured", "is_trending", "is_active")
    prepopulated_fields = {"slug": ("title",)}
    search_fields = ("title", "sku", "short_description", "description")
    inlines = [ProductImageInline, ProductReviewInline, StockLevelInline]

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if obj and obj.stock_levels.exists():
            readonly_fields.append("stock")
        return readonly_fields


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("item", "user", "quantity", "ordered", "updated_at")
    list_filter = ("ordered",)
    search_fields = ("item__title", "user__username")


class OrderStatusEventInline(admin.TabularInline):
    model = OrderStatusEvent
    extra = 0
    fields = ("status", "note", "actor", "created_at")
    readonly_fields = ("created_at",)


class ReturnRequestInline(admin.TabularInline):
    model = ReturnRequest
    extra = 0
    fields = ("order_item", "quantity", "reason", "status", "created_at")
    readonly_fields = ("created_at",)


class InventoryReservationInline(admin.TabularInline):
    model = InventoryReservation
    extra = 0
    fields = ("order_item", "item", "warehouse", "quantity", "status", "expires_at", "released_at")
    readonly_fields = fields
    can_delete = False


class SupportMessageInline(admin.TabularInline):
    model = SupportMessage
    extra = 0
    fields = ("author", "sender_role", "message", "created_at")
    readonly_fields = ("created_at",)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "user",
        "status",
        "payment_method",
        "payment_status",
        "payment_provider",
        "placed_at",
        "estimated_delivery_days",
    )
    list_filter = ("status", "payment_method", "payment_status", "payment_provider")
    search_fields = ("reference", "user__username", "payment_reference", "payment_session_id")
    filter_horizontal = ("items",)
    inlines = [OrderStatusEventInline, ReturnRequestInline, InventoryReservationInline]
    readonly_fields = ("payment_reference", "payment_session_id", "paid_at", "payment_payload")


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ("full_name", "user", "address_type", "default", "country", "phone_number")
    list_filter = ("address_type", "default", "country")
    search_fields = ("full_name", "user__username", "street_address", "city", "phone_number")


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ("code", "discount_type", "amount", "minimum_order_value", "times_used", "active")
    list_filter = ("discount_type", "active")
    search_fields = ("code",)


@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
    list_display = ("item", "user", "rating", "verified_purchase", "approved", "created_at")
    list_filter = ("approved", "verified_purchase", "rating")
    search_fields = ("item__title", "user__username", "title", "comment")


@admin.register(WishlistItem)
class WishlistItemAdmin(admin.ModelAdmin):
    list_display = ("user", "item", "created_at")
    search_fields = ("user__username", "item__title")


@admin.register(ReturnRequest)
class ReturnRequestAdmin(admin.ModelAdmin):
    list_display = ("order", "order_item", "user", "quantity", "reason", "status", "created_at")
    list_filter = ("status", "reason")
    search_fields = ("order__reference", "user__username", "order_item__item__title", "details")


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "email_verified",
        "email_verified_at",
        "preferred_contact_channel",
        "marketing_opt_in",
        "loyalty_score",
    )
    list_filter = ("email_verified", "preferred_contact_channel", "marketing_opt_in")
    search_fields = ("user__username", "user__email")


@admin.register(LoginActivity)
class LoginActivityAdmin(admin.ModelAdmin):
    list_display = ("user", "status", "ip_address", "created_at")
    list_filter = ("status",)
    search_fields = ("user__username", "user__email", "ip_address", "user_agent")
    readonly_fields = ("created_at", "updated_at")


@admin.register(SupportThread)
class SupportThreadAdmin(admin.ModelAdmin):
    list_display = ("subject", "user", "category", "priority", "status", "order", "updated_at")
    list_filter = ("category", "priority", "status")
    search_fields = ("subject", "user__username", "user__email", "order__reference")
    inlines = [SupportMessageInline]


@admin.register(SupportMessage)
class SupportMessageAdmin(admin.ModelAdmin):
    list_display = ("thread", "author", "sender_role", "created_at")
    list_filter = ("sender_role",)
    search_fields = ("thread__subject", "author__username", "message")
    readonly_fields = ("created_at", "updated_at")


@admin.register(EmailNotification)
class EmailNotificationAdmin(admin.ModelAdmin):
    list_display = ("kind", "recipient_email", "delivery_state", "order", "support_thread", "sent_at")
    list_filter = ("kind", "delivery_state")
    search_fields = ("recipient_email", "subject", "order__reference", "support_thread__subject")
    readonly_fields = ("payload", "sent_at", "created_at", "updated_at")


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "city", "country", "priority", "is_active")
    list_filter = ("is_active", "country")
    search_fields = ("code", "name", "city", "state", "country")


@admin.register(StockLevel)
class StockLevelAdmin(admin.ModelAdmin):
    list_display = ("item", "warehouse", "on_hand", "reserved", "available_quantity", "safety_stock", "updated_at")
    list_filter = ("warehouse",)
    search_fields = ("item__title", "item__sku", "warehouse__code", "warehouse__name")
    readonly_fields = (
        "item",
        "warehouse",
        "on_hand",
        "reserved",
        "available_quantity",
        "safety_stock",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ("item", "sort_order", "is_primary", "created_at")
    list_filter = ("is_primary",)
    search_fields = ("item__title", "item__sku", "alt_text")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        "item",
        "warehouse",
        "movement_type",
        "quantity",
        "on_hand_delta",
        "reserved_delta",
        "reference",
        "created_at",
    )
    list_filter = ("movement_type", "warehouse")
    search_fields = (
        "item__title",
        "item__sku",
        "warehouse__code",
        "reference",
        "note",
        "order__reference",
    )
    readonly_fields = (
        "item",
        "warehouse",
        "related_warehouse",
        "order",
        "reservation",
        "actor",
        "movement_type",
        "quantity",
        "on_hand_delta",
        "reserved_delta",
        "reference",
        "note",
        "metadata",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(InventoryReservation)
class InventoryReservationAdmin(admin.ModelAdmin):
    list_display = ("order", "item", "warehouse", "quantity", "status", "expires_at", "released_at")
    list_filter = ("status", "warehouse")
    search_fields = ("order__reference", "item__title", "item__sku", "warehouse__code")
    readonly_fields = ("created_at", "updated_at")
