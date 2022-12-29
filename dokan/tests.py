from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .accounts import build_email_verification_token
from .models import (
    Brand,
    Category,
    CustomerProfile,
    EmailNotification,
    Item,
    LoginActivity,
    Order,
    OrderItem,
    ProductReview,
    ReturnRequest,
    SupportMessage,
    SupportThread,
    WishlistItem,
)


User = get_user_model()


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
        self.assertEqual(self.item.stock, 8)

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

    def test_health_endpoints_return_ok(self):
        response = self.client.get(reverse("store:health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

        api_response = self.client.get(reverse("store:api-health"))
        self.assertEqual(api_response.status_code, 200)
        self.assertEqual(api_response.json()["application"], "redstore")

    def test_cleanup_pending_payments_reopens_stale_orders(self):
        order = Order.objects.create(
            user=self.user,
            status=Order.Status.PAYMENT_PENDING,
            payment_method=Order.PaymentMethod.STRIPE,
            payment_status=Order.PaymentStatus.PENDING,
            payment_provider="stripe",
            placed_at=timezone.now() - timezone.timedelta(minutes=90),
        )
        output = StringIO()
        call_command("cleanup_pending_payments", minutes=30, stdout=output)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CART)
        self.assertEqual(order.payment_status, Order.PaymentStatus.FAILED)
        self.assertIn("Reopened 1 stale payment-pending orders.", output.getvalue())


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
        self.assertEqual(len(mail.outbox), 1)


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
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(
            EmailNotification.objects.filter(
                support_thread=thread,
                kind=EmailNotification.Kind.SUPPORT_REPLY,
                delivery_state=EmailNotification.DeliveryState.SENT,
            ).exists()
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
