from __future__ import annotations

from decimal import Decimal
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg, Count, FloatField, IntegerField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Category(TimestampedModel):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    icon_name = models.CharField(max_length=40, blank=True)
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="children",
        blank=True,
        null=True,
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def display_name(self) -> str:
        if self.parent:
            return f"{self.parent.name} / {self.name}"
        return self.name


class Brand(TimestampedModel):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    origin_country = models.CharField(max_length=60, blank=True)
    founded_year = models.PositiveIntegerField(blank=True, null=True)
    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Warehouse(TimestampedModel):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=120)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100)
    priority = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["priority", "name"]
        permissions = [
            ("manage_inventory_network", "Can manage warehouses and stock network"),
            ("view_inventory_dashboard", "Can view inventory dashboard"),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class ItemQuerySet(models.QuerySet):
    def base(self) -> "ItemQuerySet":
        return self.select_related("catalog_category", "brand").prefetch_related(
            "product_images"
        )

    def active(self) -> "ItemQuerySet":
        return self.base().filter(is_active=True)

    def featured(self) -> "ItemQuerySet":
        return self.active().filter(featured=True)

    def with_metrics(self) -> "ItemQuerySet":
        return self.base().annotate(
            average_rating_value=Coalesce(
                Avg("reviews__rating", filter=Q(reviews__approved=True)),
                Value(0.0),
                output_field=FloatField(),
            ),
            review_count_value=Coalesce(
                Count("reviews", filter=Q(reviews__approved=True), distinct=True),
                Value(0),
                output_field=IntegerField(),
            ),
            wishlist_count_value=Coalesce(
                Count("wishlist_entries", distinct=True),
                Value(0),
                output_field=IntegerField(),
            ),
            sold_units_value=Coalesce(
                Sum("order_items__quantity", filter=Q(order_items__ordered=True)),
                Value(0),
                output_field=IntegerField(),
            ),
        )


class Item(TimestampedModel):
    class Department(models.TextChoices):
        APPAREL = "APP", "Apparel"
        FOOTWEAR = "FTW", "Footwear"
        ACCESSORIES = "ACC", "Accessories"
        ELECTRONICS = "ELC", "Electronics"

    class ProductLabel(models.TextChoices):
        FEATURED = "FEATURED", "Featured"
        NEW = "NEW", "New Arrival"
        SALE = "SALE", "Sale"
        BESTSELLER = "BESTSELLER", "Best Seller"

    title = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    sku = models.CharField(max_length=40, unique=True, blank=True, null=True)
    category = models.CharField(max_length=3, choices=Department.choices)
    catalog_category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        related_name="items",
        blank=True,
        null=True,
    )
    brand = models.ForeignKey(
        Brand,
        on_delete=models.SET_NULL,
        related_name="items",
        blank=True,
        null=True,
    )
    label = models.CharField(max_length=10, choices=ProductLabel.choices, blank=True)
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    discount_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
    )
    short_description = models.CharField(max_length=160)
    description = models.TextField()
    image_url = models.CharField(max_length=255, blank=True)
    image_gallery = models.JSONField(default=list, blank=True)
    primary_image_file = models.ImageField(
        upload_to="products/primary/%Y/%m",
        blank=True,
    )
    attributes = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(default=list, blank=True)
    stock = models.PositiveIntegerField(default=10)
    reorder_level = models.PositiveIntegerField(default=5)
    launch_year = models.PositiveIntegerField(default=2022)
    view_count = models.PositiveIntegerField(default=0)
    featured = models.BooleanField(default=False)
    is_trending = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    objects = ItemQuerySet.as_manager()

    class Meta:
        ordering = ["-featured", "-is_trending", "-created_at", "title"]

    def __str__(self) -> str:
        return self.title

    def clean(self) -> None:
        if self.discount_price and self.discount_price >= self.price:
            raise ValidationError(
                {"discount_price": "Discount price must be lower than the base price."}
            )

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = slugify(self.title)
        if not self.sku:
            self.sku = f"RS-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    @property
    def unit_price(self) -> Decimal:
        return self.discount_price if self.discount_price else self.price

    @property
    def has_discount(self) -> bool:
        return bool(self.discount_price and self.discount_price < self.price)

    @staticmethod
    def _resolve_asset_url(asset: str | None) -> str:
        if not asset:
            return ""
        normalized = str(asset).strip()
        if not normalized:
            return ""
        if normalized.startswith(("http://", "https://", "/")):
            return normalized
        return f"{settings.STATIC_URL.rstrip('/')}/{normalized.lstrip('/')}"

    @property
    def primary_image(self) -> str:
        if self.primary_image_file:
            return self.primary_image_file.url
        primary_upload = next(
            (image for image in self.product_images.all() if image.is_primary),
            None,
        )
        if primary_upload:
            return primary_upload.image.url
        first_upload = next(iter(self.product_images.all()), None)
        if first_upload:
            return first_upload.image.url
        return self._resolve_asset_url(self.image_url or "images/product-1.jpg")

    @property
    def gallery_images(self) -> list[str]:
        images = [self.primary_image]
        for uploaded_image in self.product_images.all():
            image_url = uploaded_image.image.url
            if image_url and image_url not in images:
                images.append(image_url)
        for image in self.image_gallery:
            resolved_image = self._resolve_asset_url(image)
            if resolved_image and resolved_image not in images:
                images.append(resolved_image)
        return images

    @property
    def brand_name(self) -> str:
        return self.brand.name if self.brand else "Redstore"

    @property
    def category_name(self) -> str:
        if self.catalog_category:
            return self.catalog_category.display_name
        return self.get_category_display()

    @property
    def average_rating(self) -> float:
        annotated = getattr(self, "average_rating_value", None)
        if annotated is not None:
            return round(float(annotated), 2)
        aggregate = self.reviews.filter(approved=True).aggregate(value=Avg("rating"))
        return round(float(aggregate["value"] or 0.0), 2)

    @property
    def review_count(self) -> int:
        annotated = getattr(self, "review_count_value", None)
        if annotated is not None:
            return int(annotated)
        return self.reviews.filter(approved=True).count()

    @property
    def wishlist_count(self) -> int:
        annotated = getattr(self, "wishlist_count_value", None)
        if annotated is not None:
            return int(annotated)
        return self.wishlist_entries.count()

    @property
    def sold_units(self) -> int:
        annotated = getattr(self, "sold_units_value", None)
        if annotated is not None:
            return int(annotated)
        aggregate = self.order_items.filter(ordered=True).aggregate(total=Sum("quantity"))
        return int(aggregate["total"] or 0)

    @property
    def reserved_units(self) -> int:
        aggregate = self.stock_levels.aggregate(total=Sum("reserved"))
        return int(aggregate["total"] or 0)

    @property
    def warehouse_count(self) -> int:
        return self.stock_levels.filter(warehouse__is_active=True).count()

    @property
    def inventory_status(self) -> str:
        if self.stock == 0:
            return "Out of stock"
        if self.stock <= self.reorder_level:
            return "Low stock"
        return "In stock"

    def get_absolute_url(self) -> str:
        return reverse("store:product-detail", kwargs={"slug": self.slug})

    def get_add_to_cart_url(self) -> str:
        return reverse("store:add-to-cart", kwargs={"slug": self.slug})

    def get_remove_from_cart_url(self) -> str:
        return reverse("store:remove-from-cart", kwargs={"slug": self.slug})


class Coupon(TimestampedModel):
    class DiscountType(models.TextChoices):
        FIXED = "fixed", "Fixed Amount"
        PERCENTAGE = "percentage", "Percentage"

    code = models.CharField(max_length=30, unique=True)
    discount_type = models.CharField(
        max_length=12,
        choices=DiscountType.choices,
        default=DiscountType.FIXED,
    )
    amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    minimum_order_value = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    valid_from = models.DateTimeField(blank=True, null=True)
    valid_until = models.DateTimeField(blank=True, null=True)
    max_uses = models.PositiveIntegerField(blank=True, null=True)
    times_used = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.code

    def is_available(self, subtotal: Decimal, *, at_time=None) -> bool:
        at_time = at_time or timezone.now()
        if not self.active:
            return False
        if self.valid_from and at_time < self.valid_from:
            return False
        if self.valid_until and at_time > self.valid_until:
            return False
        if subtotal < self.minimum_order_value:
            return False
        if self.max_uses is not None and self.times_used >= self.max_uses:
            return False
        return True

    def calculate_discount(self, subtotal: Decimal) -> Decimal:
        if not self.is_available(subtotal):
            return Decimal("0.00")
        if self.discount_type == self.DiscountType.PERCENTAGE:
            discount = subtotal * (self.amount / Decimal("100.00"))
        else:
            discount = self.amount
        return min(discount.quantize(Decimal("0.01")), subtotal)


class Address(TimestampedModel):
    class AddressType(models.TextChoices):
        SHIPPING = "shipping", "Shipping"
        BILLING = "billing", "Billing"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="addresses",
    )
    full_name = models.CharField(max_length=120)
    phone_number = models.CharField(max_length=20, blank=True)
    street_address = models.CharField(max_length=255)
    apartment_address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    country = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    address_type = models.CharField(max_length=10, choices=AddressType.choices)
    default = models.BooleanField(default=False)

    class Meta:
        ordering = ["-default", "-updated_at"]
        verbose_name_plural = "addresses"

    def __str__(self) -> str:
        return f"{self.full_name} ({self.get_address_type_display()})"

    @property
    def short_display(self) -> str:
        parts = [self.street_address, self.city, self.country]
        return ", ".join(part for part in parts if part)


class OrderItem(TimestampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="order_items",
    )
    ordered = models.BooleanField(default=False)
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="order_items",
    )
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "item"],
                condition=Q(ordered=False),
                name="unique_active_cart_item_per_user",
            )
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.quantity} x {self.item.title}"

    @property
    def total_price(self) -> Decimal:
        return self.item.unit_price * self.quantity

    @property
    def savings(self) -> Decimal:
        if not self.item.has_discount:
            return Decimal("0.00")
        return (self.item.price - self.item.unit_price) * self.quantity


class Order(TimestampedModel):
    class Status(models.TextChoices):
        CART = "cart", "Cart"
        PAYMENT_PENDING = "payment_pending", "Payment Pending"
        PLACED = "placed", "Placed"
        PROCESSING = "processing", "Processing"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"

    class PaymentMethod(models.TextChoices):
        CASH = "cash_on_delivery", "Cash on delivery"
        CARD = "card_on_delivery", "Card on delivery"
        BANK = "bank_transfer", "Bank transfer"
        STRIPE = "stripe_checkout", "Stripe Checkout"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    TAX_RATE = Decimal("0.08")
    FREE_SHIPPING_THRESHOLD = Decimal("200.00")
    STANDARD_SHIPPING = Decimal("12.00")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="orders",
    )
    reference = models.CharField(max_length=20, unique=True, blank=True)
    items = models.ManyToManyField(OrderItem, blank=True, related_name="orders")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CART,
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
    )
    payment_provider = models.CharField(max_length=30, blank=True, default="manual")
    payment_reference = models.CharField(max_length=120, blank=True)
    payment_session_id = models.CharField(max_length=120, blank=True)
    payment_failure_reason = models.CharField(max_length=255, blank=True)
    payment_payload = models.JSONField(default=dict, blank=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    shipping_address = models.ForeignKey(
        Address,
        related_name="shipping_orders",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    billing_address = models.ForeignKey(
        Address,
        related_name="billing_orders",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    coupon = models.ForeignKey(
        Coupon,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="orders",
    )
    customer_note = models.TextField(blank=True)
    estimated_delivery_days = models.PositiveIntegerField(default=5)
    coupon_usage_recorded = models.BooleanField(default=False)
    placed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [
            ("view_operations_dashboard", "Can view store operations dashboard"),
        ]

    def __str__(self) -> str:
        return f"{self.reference or 'draft'} - {self.user}"

    def save(self, *args, **kwargs) -> None:
        if not self.reference:
            self.reference = uuid.uuid4().hex[:10].upper()
        super().save(*args, **kwargs)

    @staticmethod
    def _quantize(amount: Decimal) -> Decimal:
        return amount.quantize(Decimal("0.01"))

    @property
    def total_items(self) -> int:
        return sum(order_item.quantity for order_item in self.items.all())

    @property
    def subtotal(self) -> Decimal:
        total = sum(
            (order_item.total_price for order_item in self.items.select_related("item")),
            Decimal("0.00"),
        )
        return self._quantize(total)

    @property
    def coupon_discount(self) -> Decimal:
        if not self.coupon:
            return Decimal("0.00")
        return self._quantize(self.coupon.calculate_discount(self.subtotal))

    @property
    def subtotal_after_discount(self) -> Decimal:
        return self._quantize(max(self.subtotal - self.coupon_discount, Decimal("0.00")))

    @property
    def shipping_total(self) -> Decimal:
        if self.subtotal_after_discount == Decimal("0.00"):
            return Decimal("0.00")
        if self.subtotal_after_discount >= self.FREE_SHIPPING_THRESHOLD:
            return Decimal("0.00")
        return self.STANDARD_SHIPPING

    @property
    def tax_total(self) -> Decimal:
        return self._quantize(self.subtotal_after_discount * self.TAX_RATE)

    @property
    def total(self) -> Decimal:
        return self._quantize(
            self.subtotal_after_discount + self.shipping_total + self.tax_total
        )

    @property
    def is_paid(self) -> bool:
        return self.payment_status == self.PaymentStatus.PAID


class StockLevel(TimestampedModel):
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name="stock_levels",
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="stock_levels",
    )
    on_hand = models.PositiveIntegerField(default=0)
    reserved = models.PositiveIntegerField(default=0)
    safety_stock = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["warehouse__priority", "warehouse__name", "item__title"]
        constraints = [
            models.UniqueConstraint(
                fields=["warehouse", "item"],
                name="unique_stock_level_per_warehouse_item",
            )
        ]

    def __str__(self) -> str:
        return f"{self.item.title} @ {self.warehouse.code}"

    @property
    def available_quantity(self) -> int:
        return max(self.on_hand - self.reserved, 0)


class InventoryReservation(TimestampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        FULFILLED = "fulfilled", "Fulfilled"
        RELEASED = "released", "Released"
        EXPIRED = "expired", "Expired"

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="inventory_reservations",
    )
    order_item = models.ForeignKey(
        OrderItem,
        on_delete=models.CASCADE,
        related_name="inventory_reservations",
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="inventory_reservations",
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="inventory_reservations",
    )
    quantity = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    expires_at = models.DateTimeField(blank=True, null=True)
    released_at = models.DateTimeField(blank=True, null=True)
    release_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [
            ("manage_stock_reservations", "Can manage inventory reservations"),
        ]

    def __str__(self) -> str:
        return f"{self.order.reference} - {self.item.title} ({self.quantity})"

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE


class StockMovement(TimestampedModel):
    class MovementType(models.TextChoices):
        ADJUSTMENT_IN = "adjustment_in", "Adjustment in"
        ADJUSTMENT_OUT = "adjustment_out", "Adjustment out"
        TRANSFER_OUT = "transfer_out", "Transfer out"
        TRANSFER_IN = "transfer_in", "Transfer in"
        RESERVATION_HOLD = "reservation_hold", "Reservation hold"
        RESERVATION_RELEASE = "reservation_release", "Reservation release"
        FULFILLMENT = "fulfillment", "Fulfillment"
        RETURN_RESTOCK = "return_restock", "Return restock"

    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="stock_movements",
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    related_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="related_stock_movements",
        blank=True,
        null=True,
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        related_name="stock_movements",
        blank=True,
        null=True,
    )
    reservation = models.ForeignKey(
        InventoryReservation,
        on_delete=models.SET_NULL,
        related_name="stock_movements",
        blank=True,
        null=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="stock_movements",
        blank=True,
        null=True,
    )
    movement_type = models.CharField(max_length=30, choices=MovementType.choices)
    quantity = models.PositiveIntegerField(default=1)
    on_hand_delta = models.IntegerField(default=0)
    reserved_delta = models.IntegerField(default=0)
    reference = models.CharField(max_length=80, blank=True)
    note = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self) -> str:
        return f"{self.item.title} {self.get_movement_type_display()} ({self.quantity})"


class ProductImage(TimestampedModel):
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="product_images",
    )
    image = models.ImageField(upload_to="products/gallery/%Y/%m")
    alt_text = models.CharField(max_length=160, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ["sort_order", "pk"]

    def __str__(self) -> str:
        return f"{self.item.title} image {self.pk}"


class ProductReviewQuerySet(models.QuerySet):
    def approved(self) -> "ProductReviewQuerySet":
        return self.filter(approved=True)


class ProductReview(TimestampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="product_reviews",
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    title = models.CharField(max_length=120)
    comment = models.TextField()
    verified_purchase = models.BooleanField(default=False)
    approved = models.BooleanField(default=True)

    objects = ProductReviewQuerySet.as_manager()

    class Meta:
        ordering = ["-verified_purchase", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "item"],
                name="unique_review_per_user_item",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} review for {self.item}"


class WishlistItem(TimestampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wishlist_items",
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="wishlist_entries",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "item"],
                name="unique_wishlist_item_per_user",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} wishlist {self.item}"


class OrderStatusEvent(TimestampedModel):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="status_events",
    )
    status = models.CharField(max_length=20, choices=Order.Status.choices)
    note = models.CharField(max_length=255, blank=True)
    actor = models.CharField(max_length=150, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.order.reference} -> {self.status}"


class ReturnRequest(TimestampedModel):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        RECEIVED = "received", "Received"
        REFUNDED = "refunded", "Refunded"

    class Reason(models.TextChoices):
        DEFECTIVE = "defective", "Defective item"
        WRONG_ITEM = "wrong_item", "Wrong item sent"
        SIZE_ISSUE = "size_issue", "Size or fit issue"
        NOT_AS_DESCRIBED = "not_as_described", "Not as described"
        CHANGED_MIND = "changed_mind", "Changed mind"
        OTHER = "other", "Other"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="return_requests",
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="return_requests",
    )
    order_item = models.ForeignKey(
        OrderItem,
        on_delete=models.CASCADE,
        related_name="return_requests",
    )
    quantity = models.PositiveIntegerField(default=1)
    reason = models.CharField(max_length=30, choices=Reason.choices)
    details = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.REQUESTED,
    )
    resolution_note = models.TextField(blank=True)
    processed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.order.reference} return for {self.order_item.item.title}"


class CustomerProfile(TimestampedModel):
    class PreferredContactChannel(models.TextChoices):
        EMAIL = "email", "Email"
        CHAT = "chat", "Chat"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_profile",
    )
    email_verified = models.BooleanField(default=False)
    email_verified_at = models.DateTimeField(blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True)
    company_name = models.CharField(max_length=120, blank=True)
    job_title = models.CharField(max_length=120, blank=True)
    marketing_opt_in = models.BooleanField(default=True)
    preferred_contact_channel = models.CharField(
        max_length=10,
        choices=PreferredContactChannel.choices,
        default=PreferredContactChannel.EMAIL,
    )
    loyalty_score = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["user__username"]
        permissions = [
            ("manage_customer_accounts", "Can manage customer accounts"),
        ]

    def __str__(self) -> str:
        return f"{self.user} profile"


class LoginActivity(TimestampedModel):
    class Status(models.TextChoices):
        SUCCESS = "success", "Success"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="login_activities",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SUCCESS,
    )
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user} login {self.get_status_display()}"


class SupportThread(TimestampedModel):
    class Category(models.TextChoices):
        ORDER = "order", "Order"
        PAYMENT = "payment", "Payment"
        RETURN = "return", "Return"
        PRODUCT = "product", "Product"
        ACCOUNT = "account", "Account"
        TECHNICAL = "technical", "Technical"
        GENERAL = "general", "General"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        AWAITING_SUPPORT = "awaiting_support", "Awaiting support"
        AWAITING_CUSTOMER = "awaiting_customer", "Awaiting customer"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="support_threads",
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="support_threads",
    )
    subject = models.CharField(max_length=160)
    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.GENERAL,
    )
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.NORMAL,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    latest_customer_message_at = models.DateTimeField(blank=True, null=True)
    latest_support_message_at = models.DateTimeField(blank=True, null=True)
    auto_reply_snapshot = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        permissions = [
            ("manage_support_threads", "Can manage all support threads"),
        ]

    def __str__(self) -> str:
        return f"{self.subject} ({self.get_status_display()})"


class SupportMessage(TimestampedModel):
    class SenderRole(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        SUPPORT = "support", "Support"
        SYSTEM = "system", "System"

    thread = models.ForeignKey(
        SupportThread,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="support_messages",
    )
    sender_role = models.CharField(
        max_length=20,
        choices=SenderRole.choices,
    )
    message = models.TextField()

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.thread.subject} [{self.get_sender_role_display()}]"


class EmailNotification(TimestampedModel):
    class Kind(models.TextChoices):
        VERIFY_EMAIL = "verify_email", "Verify email"
        ORDER_PLACED = "order_placed", "Order placed"
        PAYMENT_RECEIVED = "payment_received", "Payment received"
        RETURN_REQUESTED = "return_requested", "Return requested"
        SUPPORT_REPLY = "support_reply", "Support reply"

    class DeliveryState(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="email_notifications",
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="email_notifications",
    )
    support_thread = models.ForeignKey(
        SupportThread,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="email_notifications",
    )
    kind = models.CharField(max_length=30, choices=Kind.choices)
    recipient_email = models.EmailField()
    subject = models.CharField(max_length=160)
    delivery_state = models.CharField(
        max_length=20,
        choices=DeliveryState.choices,
        default=DeliveryState.PENDING,
    )
    text_body = models.TextField(blank=True)
    html_body = models.TextField(blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(blank=True, null=True)
    error_message = models.CharField(max_length=255, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    sent_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} -> {self.recipient_email}"
