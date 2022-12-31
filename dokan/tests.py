from decimal import Decimal
from io import StringIO
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils import timezone
from rest_framework.authtoken.models import Token

from .accounts import build_email_verification_token, ensure_customer_profile
from .models import (
    Brand,
    Category,
    CustomerProfile,
    EmailNotification,
    InventoryReservation,
    Item,
    LoginActivity,
    Order,
    OrderItem,
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


User = get_user_model()
GIF_IMAGE_BYTES = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00"
    b"\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00"
    b"\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


def run_email_queue(*, limit: int = 25) -> str:
    output = StringIO()
    call_command("process_email_queue", limit=limit, stdout=output)
    return output.getvalue()


class StorefrontTests(TestCase):
    def setUp(self):
        self.category = Category.objects.get(slug="apparel")
        self.brand = Brand.objects.get(slug="redstore")
        self.item = Item.objects.create(
            title="Redstore Tee",
            slug="redstore-tee",
            sku="RS-TEE-001",
            category=Item.Department.APPAREL,
            catalog_category=self.category,
            brand=self.brand,
            label=Item.ProductLabel.FEATURED,
            price=Decimal("49.99"),
            discount_price=Decimal("39.99"),
            short_description="Performance cotton tee.",
            description="A flexible tee built for daily wear.",
            image_url="images/product-1.jpg",
            stock=12,
            featured=True,
            attributes={"material": "cotton", "fit": "regular"},
            tags=["tee", "training"],
        )

    def test_home_page_renders_dynamic_catalog(self):
        response = self.client.get(reverse("store:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Featured Products")
        self.assertContains(response, "Redstore Performance Tee")

    def test_catalog_page_supports_search(self):
        response = self.client.get(reverse("store:catalog"), {"q": "tee"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Redstore Tee")

    def test_product_api_returns_structured_data(self):
        response = self.client.get(reverse("store:api-product-detail", args=[self.item.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["product"]["sku"], "RS-TEE-001")


class CartFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="birat", password="strong-pass-123")
        self.category = Category.objects.get(slug="footwear")
        self.brand = Brand.objects.get(slug="hrx")
        self.item = Item.objects.create(
            title="HRX Runner",
            slug="hrx-runner",
            sku="RS-HRX-001",
            category=Item.Department.FOOTWEAR,
            catalog_category=self.category,
            brand=self.brand,
            label=Item.ProductLabel.NEW,
            price=Decimal("120.00"),
            short_description="Lightweight running shoe.",
            description="Cushioned sole and knit upper.",
            image_url="images/product-2.jpg",
            stock=8,
            attributes={"fit": "regular"},
            tags=["runner", "shoe"],
        )

    def _checkout_payload(self, payment_method: str) -> dict:
        return {
            "shipping_full_name": "Birat Khadka",
            "shipping_phone_number": "9800000000",
            "shipping_street_address": "Boudha Road",
            "shipping_apartment_address": "Apartment 4",
            "shipping_city": "Kathmandu",
            "shipping_state": "Bagmati",
            "shipping_country": "Nepal",
            "shipping_postal_code": "44600",
            "same_billing_address": "on",
            "payment_method": payment_method,
        }

    def test_add_to_cart_creates_active_order(self):
        self.client.login(username="birat", password="strong-pass-123")
        response = self.client.post(
            reverse("store:add-to-cart", kwargs={"slug": self.item.slug}),
            {"quantity": 2},
        )
        self.assertEqual(response.status_code, 302)

        order = Order.objects.get(user=self.user, status=Order.Status.CART)
        self.assertEqual(order.total_items, 2)

    def test_checkout_places_order_and_updates_stock(self):
        self.client.login(username="birat", password="strong-pass-123")
        self.client.post(
            reverse("store:add-to-cart", kwargs={"slug": self.item.slug}),
            {"quantity": 2},
        )

        response = self.client.post(
            reverse("store:checkout"),
            self._checkout_payload(Order.PaymentMethod.CASH),
        )

        self.assertRedirects(response, reverse("store:order-history"))
        order = Order.objects.get(user=self.user, status=Order.Status.PLACED)
        self.assertEqual(order.total_items, 2)
        self.assertEqual(order.payment_status, Order.PaymentStatus.PENDING)
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 6)
        self.assertEqual(order.status_events.count(), 1)
        self.assertTrue(
            EmailNotification.objects.filter(
                order=order,
                kind=EmailNotification.Kind.ORDER_PLACED,
                delivery_state=EmailNotification.DeliveryState.SKIPPED,
            ).exists()
        )

    def test_repeat_purchase_of_same_item_creates_second_order(self):
        self.client.login(username="birat", password="strong-pass-123")
        for _ in range(2):
            self.client.post(
                reverse("store:add-to-cart", kwargs={"slug": self.item.slug}),
                {"quantity": 1},
            )
            response = self.client.post(
                reverse("store:checkout"),
                self._checkout_payload(Order.PaymentMethod.CASH),
            )
            self.assertRedirects(response, reverse("store:order-history"))

        self.assertEqual(
            Order.objects.filter(user=self.user, status=Order.Status.PLACED).count(),
            2,
        )
        self.assertEqual(
            OrderItem.objects.filter(user=self.user, item=self.item, ordered=True).count(),
            2,
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 6)

    @mock.patch("dokan.views.create_stripe_checkout_session")
    def test_stripe_checkout_redirects_to_gateway_and_marks_order_pending(self, session_mock):
        session_mock.return_value = SimpleNamespace(
            id="cs_test_123",
            url="https://checkout.stripe.com/pay/cs_test_123",
            status="open",
        )
        self.client.login(username="birat", password="strong-pass-123")
        self.client.post(
            reverse("store:add-to-cart", kwargs={"slug": self.item.slug}),
            {"quantity": 2},
        )

        response = self.client.post(
            reverse("store:checkout"),
            self._checkout_payload(Order.PaymentMethod.STRIPE),
        )

        self.assertRedirects(
            response,
            "https://checkout.stripe.com/pay/cs_test_123",
            fetch_redirect_response=False,
        )
        order = Order.objects.get(user=self.user, status=Order.Status.PAYMENT_PENDING)
        self.assertEqual(order.payment_status, Order.PaymentStatus.PENDING)
        self.assertEqual(order.payment_session_id, "cs_test_123")
        self.assertEqual(order.payment_provider, "stripe")
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 6)
        self.assertEqual(order.inventory_reservations.filter(status=InventoryReservation.Status.ACTIVE).count(), 1)
        self.assertEqual(order.inventory_reservations.first().quantity, 2)

    @mock.patch("dokan.views.create_stripe_checkout_session")
    def test_cancelled_stripe_checkout_releases_reservations_and_reopens_cart(self, session_mock):
        session_mock.return_value = SimpleNamespace(
            id="cs_test_123",
            url="https://checkout.stripe.com/pay/cs_test_123",
            status="open",
        )
        self.client.login(username="birat", password="strong-pass-123")
        self.client.post(
            reverse("store:add-to-cart", kwargs={"slug": self.item.slug}),
            {"quantity": 2},
        )
        self.client.post(
            reverse("store:checkout"),
            self._checkout_payload(Order.PaymentMethod.STRIPE),
        )

        pending_order = Order.objects.get(user=self.user, status=Order.Status.PAYMENT_PENDING)
        cancel_response = self.client.get(
            reverse("store:payment-cancel", args=[pending_order.reference])
        )

        self.assertRedirects(cancel_response, reverse("store:checkout"))
        pending_order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(pending_order.status, Order.Status.CART)
        self.assertEqual(self.item.stock, 8)
        self.assertEqual(
            pending_order.inventory_reservations.filter(
                status=InventoryReservation.Status.RELEASED
            ).count(),
            1,
        )

    @mock.patch("dokan.views.construct_stripe_event")
    @mock.patch("dokan.views.create_stripe_checkout_session")
    def test_stripe_webhook_finalizes_paid_order(self, session_mock, construct_event_mock):
        session_mock.return_value = SimpleNamespace(
            id="cs_test_123",
            url="https://checkout.stripe.com/pay/cs_test_123",
            status="open",
        )
        self.client.login(username="birat", password="strong-pass-123")
        self.client.post(
            reverse("store:add-to-cart", kwargs={"slug": self.item.slug}),
            {"quantity": 2},
        )
        self.client.post(
            reverse("store:checkout"),
            self._checkout_payload(Order.PaymentMethod.STRIPE),
        )

        order = Order.objects.get(user=self.user, status=Order.Status.PAYMENT_PENDING)
        construct_event_mock.return_value = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_123",
                    "payment_intent": "pi_test_123",
                    "payment_status": "paid",
                    "metadata": {"order_reference": order.reference},
                }
            },
        }

        webhook_response = self.client.post(
            reverse("store:stripe-webhook"),
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="signature",
        )

        self.assertEqual(webhook_response.status_code, 200)
        order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PLACED)
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(order.payment_reference, "pi_test_123")
        self.assertEqual(order.status_events.filter(status=Order.Status.PLACED).count(), 1)
        self.assertEqual(self.item.stock, 6)
        self.assertEqual(
            order.inventory_reservations.filter(
                status=InventoryReservation.Status.FULFILLED
            ).count(),
            1,
        )
        self.assertTrue(
            EmailNotification.objects.filter(
                order=order,
                kind=EmailNotification.Kind.PAYMENT_RECEIVED,
            ).exists()
        )


class BrowseEnhancementTests(TestCase):
    def setUp(self):
        self.category = Category.objects.get(slug="accessories")
        self.brand = Brand.objects.get(slug="noise")
        self.first_item = Item.objects.create(
            title="Noise Matrix Smartwatch Lite",
            slug="noise-matrix-smartwatch-lite",
            sku="RS-NOI-101",
            category=Item.Department.ACCESSORIES,
            catalog_category=self.category,
            brand=self.brand,
            label=Item.ProductLabel.BESTSELLER,
            price=Decimal("149.00"),
            short_description="AMOLED smartwatch.",
            description="Tracks activity and notifications.",
            image_url="images/product-10.jpg",
            stock=8,
            attributes={"display": "AMOLED", "battery": "7 days"},
            tags=["watch", "fitness"],
        )
        self.second_item = Item.objects.create(
            title="Noise Fit Earbuds",
            slug="noise-fit-earbuds",
            sku="RS-NOI-102",
            category=Item.Department.ACCESSORIES,
            catalog_category=self.category,
            brand=self.brand,
            price=Decimal("79.00"),
            short_description="Wireless earbuds.",
            description="Compact buds with strong call clarity.",
            image_url="images/product-11.jpg",
            stock=12,
            attributes={"battery": "24 hours", "connectivity": "bluetooth"},
            tags=["audio", "wireless"],
        )

    def test_recently_viewed_products_surface_on_homepage(self):
        self.client.get(reverse("store:product-detail", args=[self.first_item.slug]))
        response = self.client.get(reverse("store:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recently Viewed")
        self.assertContains(response, "Noise Matrix Smartwatch Lite")

    def test_compare_page_and_api_return_selected_products(self):
        self.client.post(reverse("store:toggle-compare", args=[self.first_item.slug]), {"next": reverse("store:catalog")})
        self.client.post(reverse("store:toggle-compare", args=[self.second_item.slug]), {"next": reverse("store:catalog")})

        compare_response = self.client.get(reverse("store:compare"))
        self.assertEqual(compare_response.status_code, 200)
        self.assertContains(compare_response, "Noise Matrix Smartwatch Lite")
        self.assertContains(compare_response, "Noise Fit Earbuds")

        api_response = self.client.get(reverse("store:api-compare"))
        self.assertEqual(api_response.status_code, 200)
        payload = api_response.json()
        self.assertEqual(payload["compare_count"], 2)
        self.assertEqual(len(payload["compare_items"]), 2)


class ReturnRequestTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="returns_user", password="strong-pass-123")
        self.category = Category.objects.get(slug="footwear")
        self.brand = Brand.objects.get(slug="hrx")
        self.item = Item.objects.create(
            title="HRX Recover Runner",
            slug="hrx-recover-runner",
            sku="RS-HRX-200",
            category=Item.Department.FOOTWEAR,
            catalog_category=self.category,
            brand=self.brand,
            price=Decimal("110.00"),
            short_description="Recovery runner.",
            description="Soft sole and stable arch support.",
            image_url="images/product-3.jpg",
            stock=10,
            attributes={"sole": "soft foam"},
            tags=["runner"],
        )
        self.order_item = OrderItem.objects.create(
            user=self.user,
            item=self.item,
            ordered=True,
            quantity=2,
        )
        self.order = Order.objects.create(
            user=self.user,
            status=Order.Status.DELIVERED,
            payment_method=Order.PaymentMethod.CASH,
            payment_status=Order.PaymentStatus.PAID,
            payment_provider="manual",
            placed_at=timezone.now(),
            paid_at=timezone.now(),
        )
        self.order.items.add(self.order_item)

    def test_return_request_submission_creates_request(self):
        self.client.login(username="returns_user", password="strong-pass-123")
        response = self.client.post(
            reverse("store:return-request", args=[self.order.reference, self.order_item.id]),
            {
                "quantity": 1,
                "reason": ReturnRequest.Reason.SIZE_ISSUE,
                "details": "The fit is tighter than expected.",
            },
        )
        self.assertRedirects(response, reverse("store:order-history"))
        return_request = ReturnRequest.objects.get(order=self.order, order_item=self.order_item)
        self.assertEqual(return_request.status, ReturnRequest.Status.REQUESTED)
        self.assertTrue(
            EmailNotification.objects.filter(
                order=self.order,
                kind=EmailNotification.Kind.RETURN_REQUESTED,
            ).exists()
        )

    def test_order_tracking_api_includes_return_requests(self):
        ReturnRequest.objects.create(
            user=self.user,
            order=self.order,
            order_item=self.order_item,
            quantity=1,
            reason=ReturnRequest.Reason.DEFECTIVE,
            details="The midsole separated after first use.",
        )
        self.client.login(username="returns_user", password="strong-pass-123")
        response = self.client.get(reverse("store:api-order-tracking", args=[self.order.reference]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["order"]["return_requests"]), 1)


class ReviewWishlistApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="reviewer", password="strong-pass-123")
        self.category = Category.objects.get(slug="accessories")
        self.brand = Brand.objects.get(slug="noise")
        self.item = Item.objects.create(
            title="Noise Matrix Smartwatch Lite Plus",
            slug="noise-matrix-smartwatch-lite-plus",
            sku="RS-NOI-111",
            category=Item.Department.ACCESSORIES,
            catalog_category=self.category,
            brand=self.brand,
            label=Item.ProductLabel.BESTSELLER,
            price=Decimal("149.00"),
            short_description="AMOLED smartwatch.",
            description="Tracks activity and notifications.",
            image_url="images/product-10.jpg",
            stock=8,
            attributes={"display": "AMOLED"},
            tags=["watch", "fitness"],
        )

    def test_review_submission_creates_review(self):
        self.client.login(username="reviewer", password="strong-pass-123")
        response = self.client.post(
            reverse("store:submit-review", args=[self.item.slug]),
            {
                "rating": 5,
                "title": "Excellent",
                "comment": "Very solid smartwatch for the price.",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ProductReview.objects.filter(item=self.item, user=self.user).exists())

    def test_wishlist_toggle_creates_wishlist_item(self):
        self.client.login(username="reviewer", password="strong-pass-123")
        response = self.client.post(reverse("store:toggle-wishlist", args=[self.item.slug]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(WishlistItem.objects.filter(item=self.item, user=self.user).exists())

    def test_analytics_api_returns_dashboard_payload(self):
        response = self.client.get(reverse("store:api-analytics-overview"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("trending_items", response.json())


class ReliabilityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ops", password="strong-pass-123")
        self.category = Category.objects.get(slug="electronics")
        self.brand, _ = Brand.objects.get_or_create(
            slug="boat",
            defaults={"name": "boAt", "origin_country": "India"},
        )

    def test_health_endpoints_return_ok(self):
        response = self.client.get(reverse("store:health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

        api_response = self.client.get(reverse("store:api-health"))
        self.assertEqual(api_response.status_code, 200)
        self.assertEqual(api_response.json()["application"], "redstore")

    def test_cleanup_pending_payments_reopens_stale_orders(self):
        item = Item.objects.create(
            title="boAt Reserve Speaker",
            slug="boat-reserve-speaker",
            sku="RS-BOAT-301",
            category=Item.Department.ELECTRONICS,
            catalog_category=self.category,
            brand=self.brand,
            price=Decimal("90.00"),
            short_description="Compact bluetooth speaker.",
            description="Used to validate stale payment cleanup.",
            image_url="images/product-8.jpg",
            stock=5,
            reorder_level=2,
        )
        warehouse = Warehouse.objects.get(code="CENTRAL")
        stock_level = StockLevel.objects.get(item=item, warehouse=warehouse)
        stock_level.reserved = 1
        stock_level.save(update_fields=["reserved", "updated_at"])
        item.stock = 4
        item.save(update_fields=["stock", "updated_at"])
        order_item = OrderItem.objects.create(
            user=self.user,
            item=item,
            quantity=1,
            ordered=False,
        )
        order = Order.objects.create(
            user=self.user,
            status=Order.Status.PAYMENT_PENDING,
            payment_method=Order.PaymentMethod.STRIPE,
            payment_status=Order.PaymentStatus.PENDING,
            payment_provider="stripe",
            placed_at=timezone.now() - timezone.timedelta(minutes=90),
        )
        order.items.add(order_item)
        InventoryReservation.objects.create(
            order=order,
            order_item=order_item,
            item=item,
            warehouse=warehouse,
            quantity=1,
            status=InventoryReservation.Status.ACTIVE,
            expires_at=timezone.now() - timezone.timedelta(minutes=60),
        )
        output = StringIO()
        call_command("cleanup_pending_payments", minutes=30, stdout=output)
        order.refresh_from_db()
        stock_level.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CART)
        self.assertEqual(order.payment_status, Order.PaymentStatus.FAILED)
        self.assertEqual(stock_level.reserved, 0)
        self.assertEqual(item.stock, 5)
        self.assertEqual(
            order.inventory_reservations.filter(
                status=InventoryReservation.Status.EXPIRED
            ).count(),
            1,
        )
        self.assertIn("Reopened 1 stale payment-pending orders.", output.getvalue())

    def test_release_expired_reservations_command_reopens_pending_order(self):
        item = Item.objects.create(
            title="boAt Reserve Headset",
            slug="boat-reserve-headset",
            sku="RS-BOAT-302",
            category=Item.Department.ELECTRONICS,
            catalog_category=self.category,
            brand=self.brand,
            price=Decimal("70.00"),
            short_description="Compact wireless headset.",
            description="Used to validate reservation expiry cleanup.",
            image_url="images/product-9.jpg",
            stock=3,
            reorder_level=1,
        )
        warehouse = Warehouse.objects.get(code="CENTRAL")
        stock_level = StockLevel.objects.get(item=item, warehouse=warehouse)
        stock_level.reserved = 2
        stock_level.save(update_fields=["reserved", "updated_at"])
        item.stock = 1
        item.save(update_fields=["stock", "updated_at"])
        order_item = OrderItem.objects.create(
            user=self.user,
            item=item,
            quantity=2,
            ordered=False,
        )
        order = Order.objects.create(
            user=self.user,
            status=Order.Status.PAYMENT_PENDING,
            payment_method=Order.PaymentMethod.STRIPE,
            payment_status=Order.PaymentStatus.PENDING,
            payment_provider="stripe",
            placed_at=timezone.now(),
        )
        order.items.add(order_item)
        InventoryReservation.objects.create(
            order=order,
            order_item=order_item,
            item=item,
            warehouse=warehouse,
            quantity=2,
            status=InventoryReservation.Status.ACTIVE,
            expires_at=timezone.now() - timezone.timedelta(minutes=5),
        )

        output = StringIO()
        call_command("release_expired_reservations", stdout=output)

        order.refresh_from_db()
        stock_level.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CART)
        self.assertEqual(order.payment_status, Order.PaymentStatus.FAILED)
        self.assertEqual(stock_level.reserved, 0)
        self.assertEqual(item.stock, 3)
        self.assertEqual(
            order.inventory_reservations.filter(
                status=InventoryReservation.Status.EXPIRED
            ).count(),
            1,
        )
        self.assertIn("reopened 1 payment-pending orders", output.getvalue().lower())


class AdminDashboardTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="Strong-pass-12345",
        )

    def test_admin_analytics_dashboard_renders(self):
        self.client.login(username="admin", password="Strong-pass-12345")
        response = self.client.get(reverse("admin:redstore-analytics"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Store analytics")
        self.assertContains(response, "Gross Revenue")


class AuthenticationTests(TestCase):
    def test_signup_creates_user_and_logs_them_in(self):
        response = self.client.post(
            reverse("store:signup"),
            {
                "username": "new-user",
                "email": "user@example.com",
                "password1": "Strong-pass-12345",
                "password2": "Strong-pass-12345",
            },
        )

        self.assertRedirects(response, reverse("store:home"))
        self.assertTrue(User.objects.filter(username="new-user").exists())
        user = User.objects.get(username="new-user")
        self.assertTrue(CustomerProfile.objects.filter(user=user).exists())
        self.assertEqual(LoginActivity.objects.filter(user=user).count(), 1)
        notification = EmailNotification.objects.get(
            user=user,
            kind=EmailNotification.Kind.VERIFY_EMAIL,
        )
        self.assertEqual(
            notification.delivery_state,
            EmailNotification.DeliveryState.PENDING,
        )
        self.assertEqual(len(mail.outbox), 0)
        run_email_queue()
        notification.refresh_from_db()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            notification.delivery_state,
            EmailNotification.DeliveryState.SENT,
        )


class PasswordResetFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="recover-user",
            email="recover@example.com",
            password="Strong-pass-12345",
        )

    def test_password_reset_request_and_confirmation_flow(self):
        response = self.client.post(
            reverse("store:password-reset"),
            {"email": self.user.email},
        )

        self.assertRedirects(response, reverse("store:password-reset-done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("account/reset", mail.outbox[0].body)

        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        confirm_url = reverse("store:password-reset-confirm", args=[uid, token])
        confirm_response = self.client.get(confirm_url)
        self.assertIn(confirm_response.status_code, {200, 302})

        post_url = confirm_response.url if confirm_response.status_code == 302 else confirm_url
        completion_response = self.client.post(
            post_url,
            {
                "new_password1": "Even-Stronger-12345",
                "new_password2": "Even-Stronger-12345",
            },
        )

        self.assertRedirects(
            completion_response,
            reverse("store:password-reset-complete"),
        )
        self.assertTrue(
            self.client.login(
                username=self.user.username,
                password="Even-Stronger-12345",
            )
        )


class AccountSettingsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="settings-user",
            email="settings@example.com",
            password="Strong-pass-12345",
            first_name="Settings",
        )
        self.profile = ensure_customer_profile(self.user)
        self.profile.email_verified = True
        self.profile.save(update_fields=["email_verified", "updated_at"])

    def test_account_settings_profile_update_marks_email_unverified(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("store:account-profile-update"),
            {
                "user-username": "settings-user",
                "user-email": "new-settings@example.com",
                "user-first_name": "Birat",
                "user-last_name": "Khadka",
                "profile-phone_number": "9800001111",
                "profile-company_name": "Redstore Labs",
                "profile-job_title": "Analyst",
                "profile-preferred_contact_channel": CustomerProfile.PreferredContactChannel.CHAT,
                "profile-marketing_opt_in": "on",
            },
        )

        self.assertRedirects(response, reverse("store:account-settings"))
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.user.first_name, "Birat")
        self.assertEqual(self.user.email, "new-settings@example.com")
        self.assertFalse(self.profile.email_verified)
        self.assertEqual(self.profile.phone_number, "9800001111")
        self.assertEqual(self.profile.company_name, "Redstore Labs")
        notification = EmailNotification.objects.get(
            user=self.user,
            kind=EmailNotification.Kind.VERIFY_EMAIL,
        )
        self.assertEqual(
            notification.delivery_state,
            EmailNotification.DeliveryState.PENDING,
        )
        self.assertEqual(len(mail.outbox), 0)
        run_email_queue()
        notification.refresh_from_db()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            notification.delivery_state,
            EmailNotification.DeliveryState.SENT,
        )

    def test_account_settings_password_change_keeps_session_valid(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("store:account-password-change"),
            {
                "old_password": "Strong-pass-12345",
                "new_password1": "Even-Stronger-12345",
                "new_password2": "Even-Stronger-12345",
            },
        )

        self.assertRedirects(response, reverse("store:account-settings"))
        self.assertTrue(
            self.client.login(
                username=self.user.username,
                password="Even-Stronger-12345",
            )
        )

    def test_account_settings_address_book_flow(self):
        self.client.force_login(self.user)
        create_response = self.client.post(
            reverse("store:account-address-add"),
            {
                "address-full_name": "Birat Khadka",
                "address-phone_number": "9800002222",
                "address-street_address": "Boudha Road",
                "address-apartment_address": "Apt 7",
                "address-city": "Kathmandu",
                "address-state": "Bagmati",
                "address-country": "Nepal",
                "address-postal_code": "44600",
                "address-address_type": "shipping",
                "address-default": "on",
            },
        )
        self.assertRedirects(create_response, reverse("store:account-settings"))
        address = self.user.addresses.get()
        self.assertTrue(address.default)

        second_response = self.client.post(
            reverse("store:account-address-add"),
            {
                "address-full_name": "Birat Office",
                "address-phone_number": "9800003333",
                "address-street_address": "Pulchowk",
                "address-apartment_address": "",
                "address-city": "Lalitpur",
                "address-state": "Bagmati",
                "address-country": "Nepal",
                "address-postal_code": "44700",
                "address-address_type": "shipping",
                "address-default": "on",
            },
        )
        self.assertRedirects(second_response, reverse("store:account-settings"))
        self.assertEqual(self.user.addresses.filter(default=True, address_type="shipping").count(), 1)


class SecuritySupportAndAssistantTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="secure-user",
            email="secure@example.com",
            password="Strong-pass-12345",
        )
        self.staff_user = User.objects.create_superuser(
            username="support-admin",
            email="support@example.com",
            password="Strong-pass-12345",
        )
        self.category = Category.objects.get(slug="footwear")
        self.brand = Brand.objects.get(slug="hrx")
        self.item = Item.objects.create(
            title="Trail Runner Pro",
            slug="trail-runner-pro",
            sku="RS-TRAIL-001",
            category=Item.Department.FOOTWEAR,
            catalog_category=self.category,
            brand=self.brand,
            price=Decimal("130.00"),
            short_description="Trail running shoe.",
            description="Designed for distance, grip, and stable trail running.",
            image_url="images/product-2.jpg",
            stock=9,
            attributes={"fit": "regular", "usage": "trail running"},
            tags=["runner", "shoe", "trail"],
        )
        self.order_item = OrderItem.objects.create(
            user=self.user,
            item=self.item,
            ordered=True,
            quantity=1,
        )
        self.order = Order.objects.create(
            user=self.user,
            status=Order.Status.DELIVERED,
            payment_method=Order.PaymentMethod.CASH,
            payment_status=Order.PaymentStatus.PAID,
            payment_provider="manual",
            placed_at=timezone.now(),
            paid_at=timezone.now(),
        )
        self.order.items.add(self.order_item)

    def test_verify_email_view_marks_profile_verified(self):
        token = build_email_verification_token(self.user)

        response = self.client.get(reverse("store:verify-email", args=[token]))

        self.assertRedirects(response, reverse("store:login"))
        profile = CustomerProfile.objects.get(user=self.user)
        self.assertTrue(profile.email_verified)
        self.assertIsNotNone(profile.email_verified_at)

    def test_login_view_records_activity_and_security_api(self):
        response = self.client.post(
            reverse("store:login"),
            {"username": "secure-user", "password": "Strong-pass-12345"},
        )

        self.assertRedirects(response, reverse("store:home"))
        self.assertEqual(LoginActivity.objects.filter(user=self.user).count(), 1)

        api_response = self.client.get(reverse("store:api-account-security"))
        self.assertEqual(api_response.status_code, 200)
        payload = api_response.json()
        self.assertFalse(payload["profile"]["email_verified"])
        self.assertEqual(len(payload["recent_logins"]), 1)

    def test_support_thread_flow_and_reply_email(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("store:support-threads"),
            {
                "subject": "Need help with delivered order",
                "category": SupportThread.Category.RETURN,
                "priority": SupportThread.Priority.NORMAL,
                "order": self.order.pk,
                "message": "I need help with the return process for this runner.",
            },
        )

        thread = SupportThread.objects.get(user=self.user)
        self.assertRedirects(response, reverse("store:support-thread-detail", args=[thread.pk]))
        self.assertEqual(thread.status, SupportThread.Status.AWAITING_SUPPORT)
        self.assertEqual(thread.messages.count(), 1)
        self.assertTrue(thread.auto_reply_snapshot)

        self.client.force_login(self.staff_user)
        reply_response = self.client.post(
            reverse("store:support-thread-detail", args=[thread.pk]),
            {"message": "Please submit the return request form and we will review it today."},
        )

        self.assertRedirects(reply_response, reverse("store:support-thread-detail", args=[thread.pk]))
        thread.refresh_from_db()
        self.assertEqual(thread.status, SupportThread.Status.AWAITING_CUSTOMER)
        self.assertEqual(
            SupportMessage.objects.filter(thread=thread, sender_role=SupportMessage.SenderRole.SUPPORT).count(),
            1,
        )
        notification = EmailNotification.objects.get(
            support_thread=thread,
            kind=EmailNotification.Kind.SUPPORT_REPLY,
        )
        self.assertEqual(
            notification.delivery_state,
            EmailNotification.DeliveryState.PENDING,
        )
        self.assertEqual(len(mail.outbox), 0)
        run_email_queue()
        notification.refresh_from_db()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            notification.delivery_state,
            EmailNotification.DeliveryState.SENT,
        )

    def test_assistant_and_catalog_apis_return_ranked_ai_signals(self):
        catalog_response = self.client.get(reverse("store:api-catalog"), {"q": "trail runner"})
        self.assertEqual(catalog_response.status_code, 200)
        self.assertTrue(catalog_response.json()["search_matches"])
        self.assertIn("score", catalog_response.json()["search_matches"][0])

        assistant_response = self.client.get(
            reverse("store:api-ai-assistant"),
            {"q": "payment pending order"},
        )
        self.assertEqual(assistant_response.status_code, 200)
        self.assertTrue(assistant_response.json()["support_suggestions"])


class AdvancedApiV2Tests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="api-user",
            email="api-user@example.com",
            password="Strong-pass-12345",
        )
        self.inventory_user = User.objects.create_user(
            username="inventory-user",
            email="inventory-user@example.com",
            password="Strong-pass-12345",
        )
        Group.objects.get(name="Inventory Manager").user_set.add(self.inventory_user)
        self.profile = ensure_customer_profile(self.user)
        self.category = Category.objects.get(slug="electronics")
        self.brand, _ = Brand.objects.get_or_create(
            slug="boat",
            defaults={"name": "boAt", "origin_country": "India"},
        )
        self.item = Item.objects.create(
            title="boAt Controller Speaker",
            slug="boat-controller-speaker",
            sku="RS-BOAT-401",
            category=Item.Department.ELECTRONICS,
            catalog_category=self.category,
            brand=self.brand,
            price=Decimal("99.00"),
            short_description="Controller speaker.",
            description="Inventory and API validation item.",
            image_url="images/product-8.jpg",
            stock=6,
            reorder_level=2,
            tags=["speaker"],
        )

    def test_v2_account_profile_and_address_endpoints(self):
        self.client.force_login(self.user)

        profile_response = self.client.patch(
            reverse("store:api-v2-account-profile"),
            data='{"username":"api-user","email":"api-updated@example.com","first_name":"Api","last_name":"User","phone_number":"9800011111","company_name":"Redstore Ops","job_title":"Lead","preferred_contact_channel":"chat","marketing_opt_in":true}',
            content_type="application/json",
        )
        self.assertEqual(profile_response.status_code, 200)
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.user.email, "api-updated@example.com")
        self.assertEqual(self.profile.phone_number, "9800011111")

        address_response = self.client.post(
            reverse("store:api-v2-account-addresses"),
            data='{"full_name":"API User","phone_number":"9800011111","street_address":"Boudha","apartment_address":"","city":"Kathmandu","state":"Bagmati","country":"Nepal","postal_code":"44600","address_type":"shipping","default":true}',
            content_type="application/json",
        )
        self.assertEqual(address_response.status_code, 201)
        address_id = address_response.json()["address"]["id"]

        default_response = self.client.post(
            reverse("store:api-v2-account-address-default", args=[address_id]),
        )
        self.assertEqual(default_response.status_code, 200)
        self.assertTrue(default_response.json()["address"]["default"])

        access_response = self.client.get(reverse("store:api-v2-account-access"))
        self.assertEqual(access_response.status_code, 200)
        self.assertIn("capabilities", access_response.json())

    def test_v2_account_password_endpoint(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("store:api-v2-account-password"),
            data='{"old_password":"Strong-pass-12345","new_password1":"Even-Stronger-12345","new_password2":"Even-Stronger-12345"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            self.client.login(
                username="api-user",
                password="Even-Stronger-12345",
            )
        )

    def test_v2_inventory_endpoints_are_permission_protected_and_expose_reservations(self):
        warehouse = Warehouse.objects.get(code="CENTRAL")
        stock_level = StockLevel.objects.get(item=self.item, warehouse=warehouse)
        stock_level.reserved = 2
        stock_level.save(update_fields=["reserved", "updated_at"])
        self.item.stock = 4
        self.item.save(update_fields=["stock", "updated_at"])

        order_item = OrderItem.objects.create(
            user=self.user,
            item=self.item,
            quantity=2,
            ordered=False,
        )
        order = Order.objects.create(
            user=self.user,
            status=Order.Status.PAYMENT_PENDING,
            payment_method=Order.PaymentMethod.STRIPE,
            payment_status=Order.PaymentStatus.PENDING,
            payment_provider="stripe",
            placed_at=timezone.now(),
        )
        order.items.add(order_item)
        InventoryReservation.objects.create(
            order=order,
            order_item=order_item,
            item=self.item,
            warehouse=warehouse,
            quantity=2,
            status=InventoryReservation.Status.ACTIVE,
            expires_at=timezone.now() + timezone.timedelta(minutes=30),
        )

        self.client.force_login(self.user)
        forbidden_response = self.client.get(reverse("store:api-v2-inventory-overview"))
        self.assertEqual(forbidden_response.status_code, 403)

        self.client.force_login(self.inventory_user)
        overview_response = self.client.get(reverse("store:api-v2-inventory-overview"))
        self.assertEqual(overview_response.status_code, 200)
        self.assertEqual(overview_response.json()["meta"]["active_reservations"], 1)

        warehouses_response = self.client.get(
            reverse("store:api-v2-inventory-warehouses"),
            {"include_stock": "true"},
        )
        self.assertEqual(warehouses_response.status_code, 200)
        self.assertEqual(warehouses_response.json()["results"][0]["code"], "CENTRAL")

        reservations_response = self.client.get(
            reverse("store:api-v2-inventory-active-reservations")
        )
        self.assertEqual(reservations_response.status_code, 200)
        self.assertEqual(reservations_response.json()["meta"]["count"], 1)

        order_reservations_response = self.client.get(
            reverse("store:api-v2-order-reservations", args=[order.reference])
        )
        self.assertEqual(order_reservations_response.status_code, 200)
        self.assertEqual(len(order_reservations_response.json()["reservations"]), 1)

    def test_v2_token_auth_can_issue_and_revoke_tokens(self):
        response = self.client.post(
            reverse("store:api-v2-auth-token"),
            data='{"username":"inventory-user","password":"Strong-pass-12345"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        token_key = response.json()["token"]
        self.assertTrue(Token.objects.filter(user=self.inventory_user, key=token_key).exists())

        overview_response = self.client.get(
            reverse("store:api-v2-inventory-overview"),
            HTTP_AUTHORIZATION=f"Token {token_key}",
        )
        self.assertEqual(overview_response.status_code, 200)

        delete_response = self.client.delete(
            reverse("store:api-v2-auth-token"),
            HTTP_AUTHORIZATION=f"Token {token_key}",
        )
        self.assertEqual(delete_response.status_code, 204)
        self.assertFalse(Token.objects.filter(user=self.inventory_user).exists())

    def test_v2_inventory_mutation_endpoints_record_movements(self):
        warehouse = Warehouse.objects.get(code="CENTRAL")
        secondary_warehouse = Warehouse.objects.create(
            code="POKH",
            name="Pokhara Hub",
            city="Pokhara",
            state="Gandaki",
            country="Nepal",
            priority=2,
            is_active=True,
        )
        token = Token.objects.create(user=self.inventory_user)

        adjustment_response = self.client.post(
            reverse("store:api-v2-inventory-adjustments"),
            data=(
                '{"item":%d,"warehouse":%d,"quantity":4,"direction":"increase",'
                '"reason":"Cycle count recovery","reference":"ADJ-401"}'
            )
            % (self.item.pk, warehouse.pk),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(adjustment_response.status_code, 201)

        transfer_response = self.client.post(
            reverse("store:api-v2-inventory-transfers"),
            data=(
                '{"item":%d,"source_warehouse":%d,"destination_warehouse":%d,'
                '"quantity":3,"reason":"Balance regional inventory","reference":"TX-401"}'
            )
            % (self.item.pk, warehouse.pk, secondary_warehouse.pk),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(transfer_response.status_code, 201)

        self.item.refresh_from_db()
        source_level = StockLevel.objects.get(item=self.item, warehouse=warehouse)
        destination_level = StockLevel.objects.get(
            item=self.item,
            warehouse=secondary_warehouse,
        )
        self.assertEqual(self.item.stock, 10)
        self.assertEqual(source_level.on_hand, 7)
        self.assertEqual(destination_level.on_hand, 3)
        self.assertEqual(StockMovement.objects.filter(item=self.item).count(), 3)

        movements_response = self.client.get(
            reverse("store:api-v2-inventory-movements"),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(movements_response.status_code, 200)
        movement_codes = {
            entry["movement_type_code"]
            for entry in movements_response.json()["results"]
        }
        self.assertIn(StockMovement.MovementType.ADJUSTMENT_IN, movement_codes)
        self.assertIn(StockMovement.MovementType.TRANSFER_OUT, movement_codes)
        self.assertIn(StockMovement.MovementType.TRANSFER_IN, movement_codes)


class InventoryConsistencyAndMediaTests(TestCase):
    def setUp(self):
        self.category = Category.objects.get(slug="electronics")
        self.brand, _ = Brand.objects.get_or_create(
            slug="sony",
            defaults={"name": "Sony", "origin_country": "Japan"},
        )
        self.item = Item.objects.create(
            title="Sony Sync Speaker",
            slug="sony-sync-speaker",
            sku="RS-SONY-101",
            category=Item.Department.ELECTRONICS,
            catalog_category=self.category,
            brand=self.brand,
            price=Decimal("129.00"),
            short_description="Speaker used for inventory consistency tests.",
            description="Checks stock cache synchronization and uploaded media URLs.",
            image_url="images/product-5.jpg",
            stock=10,
            reorder_level=3,
        )

    def test_stock_level_updates_sync_item_cache_and_safety_stock(self):
        warehouse = Warehouse.objects.get(code="CENTRAL")
        stock_level = StockLevel.objects.get(item=self.item, warehouse=warehouse)
        stock_level.reserved = 4
        stock_level.save(update_fields=["reserved", "updated_at"])

        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 6)

        self.item.reorder_level = 2
        self.item.save(update_fields=["reorder_level", "updated_at"])
        stock_level.refresh_from_db()
        self.assertEqual(stock_level.safety_stock, 2)

        warehouse.is_active = False
        warehouse.save(update_fields=["is_active", "updated_at"])
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 0)

    def test_uploaded_primary_image_uses_media_url(self):
        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root, MEDIA_URL="/media/"):
                uploaded_image = SimpleUploadedFile(
                    "speaker.gif",
                    GIF_IMAGE_BYTES,
                    content_type="image/gif",
                )
                media_item = Item.objects.create(
                    title="Sony Media Speaker",
                    slug="sony-media-speaker",
                    sku="RS-SONY-102",
                    category=Item.Department.ELECTRONICS,
                    catalog_category=self.category,
                    brand=self.brand,
                    price=Decimal("149.00"),
                    short_description="Speaker with uploaded primary image.",
                    description="Used to verify media-backed product rendering.",
                    image_url="images/product-6.jpg",
                    primary_image_file=uploaded_image,
                    stock=5,
                )
                ProductImage.objects.create(
                    item=media_item,
                    image=SimpleUploadedFile(
                        "speaker-gallery.gif",
                        GIF_IMAGE_BYTES,
                        content_type="image/gif",
                    ),
                    alt_text="Gallery image",
                    sort_order=1,
                )

                self.assertTrue(media_item.primary_image.startswith("/media/products/"))
                self.assertTrue(
                    any(image.startswith("/media/products/") for image in media_item.gallery_images)
                )

                response = self.client.get(
                    reverse("store:product-detail", args=[media_item.slug])
                )
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "/media/products/")


class RoleAccessTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="customer-role",
            email="customer-role@example.com",
            password="Strong-pass-12345",
        )
        self.support_user = User.objects.create_user(
            username="support-role",
            email="support-role@example.com",
            password="Strong-pass-12345",
        )
        self.operations_user = User.objects.create_user(
            username="operations-role",
            email="operations-role@example.com",
            password="Strong-pass-12345",
        )
        self.inventory_user = User.objects.create_user(
            username="inventory-role",
            email="inventory-role@example.com",
            password="Strong-pass-12345",
        )
        self.plain_staff_user = User.objects.create_user(
            username="plain-staff",
            email="plain-staff@example.com",
            password="Strong-pass-12345",
            is_staff=True,
        )

        Group.objects.get(name="Support Team").user_set.add(self.support_user)
        Group.objects.get(name="Operations Team").user_set.add(self.operations_user)
        Group.objects.get(name="Inventory Manager").user_set.add(self.inventory_user)

        self.thread = SupportThread.objects.create(
            user=self.customer,
            subject="Delivery issue",
            category=SupportThread.Category.ORDER,
            priority=SupportThread.Priority.NORMAL,
            status=SupportThread.Status.AWAITING_SUPPORT,
        )
        SupportMessage.objects.create(
            thread=self.thread,
            author=self.customer,
            sender_role=SupportMessage.SenderRole.CUSTOMER,
            message="The order is delayed.",
        )

    def test_support_group_member_can_access_customer_thread(self):
        self.client.force_login(self.support_user)

        response = self.client.get(
            reverse("store:support-thread-detail", args=[self.thread.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Delivery issue")

    def test_operations_group_member_can_access_operations_dashboard(self):
        self.client.force_login(self.operations_user)

        response = self.client.get(reverse("store:operations-dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Store Operations Overview")

    def test_inventory_role_member_can_access_inventory_dashboard(self):
        self.client.force_login(self.inventory_user)

        response = self.client.get(reverse("store:inventory-dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Warehouse and Reservation Network")

    def test_plain_staff_without_role_cannot_access_internal_dashboards(self):
        self.client.force_login(self.plain_staff_user)

        inventory_response = self.client.get(reverse("store:inventory-dashboard"))
        operations_response = self.client.get(reverse("store:operations-dashboard"))

        self.assertEqual(inventory_response.status_code, 403)
        self.assertEqual(operations_response.status_code, 403)
