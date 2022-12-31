from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.views import LoginView
from django.core import signing
from django.core.exceptions import ImproperlyConfigured, PermissionDenied, ValidationError
from django.db.models import Q
from django.db.models.functions import Coalesce
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import DetailView, FormView, ListView, TemplateView, View

from .accounts import (
    ensure_customer_profile,
    mark_email_unverified,
    mark_email_verified,
    record_login_activity,
    resolve_email_verification_token,
)
from .admin_dashboard import build_admin_dashboard, build_inventory_dashboard
from .forms import (
    AddToCartForm,
    AccountIdentityForm,
    AccountPasswordChangeForm,
    AddressBookForm,
    ApplyCouponForm,
    CheckoutForm,
    CustomerProfileSettingsForm,
    InventoryAdjustmentForm,
    InventoryTransferForm,
    LoginForm,
    ReturnRequestForm,
    ReviewForm,
    SignUpForm,
    SupportMessageForm,
    SupportThreadForm,
)
from .intelligence import (
    assess_customer_health,
    build_storefront_insights,
    classify_customer,
    rank_catalog_search,
    recommend_for_order,
    recommend_items,
    suggest_support_answers,
)
from .models import Address, Brand, Category, EmailNotification, Item, Order, OrderItem, SupportThread
from .notifications import (
    send_email_verification_email,
    send_order_placed_email,
    send_payment_received_email,
    send_return_requested_email,
    send_support_reply_email,
)
from .payments import (
    construct_stripe_event,
    create_stripe_checkout_session,
    is_stripe_enabled,
    retrieve_stripe_checkout_session,
    stripe_object_to_payload,
)
from .permissions import (
    can_manage_inventory_network,
    can_manage_support_threads,
    can_view_inventory_dashboard,
    can_view_operations_dashboard,
    user_role_labels,
)
from .session_features import (
    get_compare_items,
    get_recently_viewed_items,
    is_in_compare,
    register_recently_viewed_item,
    toggle_compare_item,
)
from .services import (
    adjust_stock_level,
    add_item_to_cart,
    apply_coupon_to_order,
    attach_payment_session,
    decrease_item_quantity,
    finalize_paid_order,
    get_active_order,
    place_order,
    prepare_order_for_online_payment,
    register_item_view,
    remove_item_from_cart,
    reopen_order_for_checkout,
    submit_return_request,
    submit_review,
    transfer_stock,
    toggle_wishlist,
)
from .support import create_support_thread, post_support_message, resolve_support_thread, support_queryset_for_user


User = get_user_model()


def build_account_settings_context(
    request: HttpRequest,
    *,
    user_form=None,
    profile_form=None,
    password_form=None,
    address_form=None,
    editing_address: Address | None = None,
) -> dict:
    profile = ensure_customer_profile(request.user)
    if editing_address is None:
        edit_id = request.GET.get("edit", "").strip()
        if edit_id:
            editing_address = get_object_or_404(
                Address.objects.filter(user=request.user),
                pk=edit_id,
            )

    return {
        "profile": profile,
        "user_form": user_form or AccountIdentityForm(instance=request.user, prefix="user"),
        "profile_form": profile_form
        or CustomerProfileSettingsForm(instance=profile, prefix="profile"),
        "password_form": password_form or AccountPasswordChangeForm(request.user),
        "address_form": address_form
        or AddressBookForm(instance=editing_address, prefix="address"),
        "editing_address": editing_address,
        "addresses": request.user.addresses.all(),
        "recent_logins": request.user.login_activities.all()[:6],
        "internal_roles": user_role_labels(request.user),
        "can_view_inventory_dashboard": can_view_inventory_dashboard(request.user),
        "can_manage_inventory_network": can_manage_inventory_network(request.user),
    }


def build_inventory_dashboard_context(
    *,
    adjustment_form=None,
    transfer_form=None,
) -> dict:
    return {
        **build_inventory_dashboard(limit=10),
        "adjustment_form": adjustment_form
        or InventoryAdjustmentForm(prefix="adjustment"),
        "transfer_form": transfer_form or InventoryTransferForm(prefix="transfer"),
    }


class HomeView(TemplateView):
    template_name = "index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        featured_items = list(Item.objects.featured().with_metrics()[:4])
        featured_ids = [item.pk for item in featured_items]
        latest_items = Item.objects.active().with_metrics().exclude(pk__in=featured_ids)[:8]
        insights = build_storefront_insights(
            user=self.request.user if self.request.user.is_authenticated else None,
            limit=4,
        )
        context.update(
            {
                "featured_items": featured_items,
                "latest_items": latest_items,
                "trending_items": insights["trending_items"],
                "top_rated_items": insights["top_rated_items"],
                "value_picks": insights["value_picks"],
                "customer_segment": insights["customer_segment"],
                "customer_health": insights["customer_health"],
                "recently_viewed_items": get_recently_viewed_items(self.request, limit=4),
                "compare_items": get_compare_items(self.request),
            }
        )
        return context


class CatalogView(ListView):
    template_name = "products.html"
    context_object_name = "items"
    paginate_by = 8

    def get_queryset(self):
        queryset = Item.objects.active().with_metrics().annotate(
            display_price=Coalesce("discount_price", "price")
        )
        query = self.request.GET.get("q", "").strip()
        category_slug = self.request.GET.get("category", "").strip()
        brand_slug = self.request.GET.get("brand", "").strip()
        sort = self.request.GET.get("sort", "relevance" if query else "latest").strip()
        self.query_support_suggestions = suggest_support_answers(query, limit=3) if query else []

        if query:
            queryset = queryset.filter(
                Q(title__icontains=query)
                | Q(short_description__icontains=query)
                | Q(description__icontains=query)
                | Q(brand__name__icontains=query)
                | Q(catalog_category__name__icontains=query)
            )

        if category_slug:
            queryset = queryset.filter(catalog_category__slug=category_slug)

        if brand_slug:
            queryset = queryset.filter(brand__slug=brand_slug)

        sort_options = {
            "relevance": ("-view_count", "title"),
            "latest": ("-created_at", "title"),
            "price_low": ("display_price", "title"),
            "price_high": ("-display_price", "title"),
            "title": ("title",),
            "rating": ("-average_rating_value", "-review_count_value", "title"),
            "popular": ("-sold_units_value", "-wishlist_count_value", "-view_count", "title"),
        }
        if query and sort == "relevance":
            ranked_results = rank_catalog_search(query, queryset=list(queryset))
            for entry in ranked_results:
                entry.item.search_score = entry.score
                entry.item.search_reasons = entry.reasons
            return [entry.item for entry in ranked_results]

        return queryset.order_by(*sort_options.get(sort, ("-created_at", "title")))

    def paginate_queryset(self, queryset, page_size):
        paginator = self.get_paginator(
            queryset,
            page_size,
            orphans=self.get_paginate_orphans(),
            allow_empty_first_page=self.get_allow_empty(),
        )
        page = self.request.GET.get("page", 1)
        try:
            page_number = int(page)
        except (TypeError, ValueError):
            page_number = 1
        page_number = max(1, min(page_number, max(paginator.num_pages, 1)))
        page_obj = paginator.page(page_number)
        return paginator, page_obj, page_obj.object_list, page_obj.has_other_pages()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "categories": Category.objects.filter(is_active=True, parent__isnull=True),
                "brands": Brand.objects.filter(is_active=True),
                "selected_category": self.request.GET.get("category", "").strip(),
                "selected_brand": self.request.GET.get("brand", "").strip(),
                "selected_sort": self.request.GET.get(
                    "sort",
                    "relevance" if self.request.GET.get("q", "").strip() else "latest",
                ).strip(),
                "search_term": self.request.GET.get("q", "").strip(),
                "query_support_suggestions": getattr(self, "query_support_suggestions", []),
            }
        )
        return context


class ProductDetailView(DetailView):
    model = Item
    template_name = "productdetail.html"
    context_object_name = "item"

    def get_queryset(self):
        return Item.objects.active().with_metrics().prefetch_related("reviews__user")

    def get_object(self, queryset=None):
        item = super().get_object(queryset)
        register_item_view(item)
        register_recently_viewed_item(self.request, item)
        return item

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["recommendations"] = recommend_items(self.object, limit=4)
        context["recently_viewed_items"] = get_recently_viewed_items(
            self.request,
            limit=4,
            exclude_item=self.object,
        )
        context["reviews"] = self.object.reviews.approved().select_related("user")[:8]
        context["cart_form"] = AddToCartForm()
        context["review_form"] = ReviewForm()
        context["is_in_wishlist"] = (
            self.request.user.is_authenticated
            and self.request.user.wishlist_items.filter(item=self.object).exists()
        )
        context["is_in_compare"] = is_in_compare(self.request, self.object)
        return context


class CartView(LoginRequiredMixin, TemplateView):
    template_name = "cart.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order = get_active_order(self.request.user)
        context["order"] = order
        context["coupon_form"] = ApplyCouponForm()
        context["recommended_entries"] = recommend_for_order(order, limit=4) if order else []
        return context


class WishlistView(LoginRequiredMixin, TemplateView):
    template_name = "wishlist.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["wishlist_entries"] = self.request.user.wishlist_items.select_related(
            "item__brand",
            "item__catalog_category",
        )
        return context


class CompareView(TemplateView):
    template_name = "compare.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        compare_items = get_compare_items(self.request)
        comparison_rows = [
            {"label": "Brand", "values": [item.brand_name for item in compare_items]},
            {"label": "Category", "values": [item.category_name for item in compare_items]},
            {"label": "Price", "values": [f"${item.unit_price:.2f}" for item in compare_items]},
            {"label": "Rating", "values": [f"{item.average_rating}/5" for item in compare_items]},
            {"label": "Stock", "values": [item.inventory_status for item in compare_items]},
        ]
        attribute_keys = sorted({key for item in compare_items for key in item.attributes.keys()})
        comparison_rows.extend(
            {
                "label": key.replace("_", " ").title(),
                "values": [item.attributes.get(key, "-") for item in compare_items],
            }
            for key in attribute_keys
        )
        context.update(
            {
                "compare_items": compare_items,
                "comparison_rows": comparison_rows,
            }
        )
        return context


class InsightsView(TemplateView):
    template_name = "insights.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            build_storefront_insights(
                user=self.request.user if self.request.user.is_authenticated else None,
                limit=6,
            )
        )
        return context


class OrderHistoryView(LoginRequiredMixin, TemplateView):
    template_name = "order_history.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["orders"] = (
            Order.objects.filter(user=self.request.user)
            .exclude(status=Order.Status.CART)
            .prefetch_related("items__item", "items__return_requests", "status_events", "return_requests__order_item__item")
        )
        return context


class AccountDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "account_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        profile = ensure_customer_profile(self.request.user)
        context.update(
            {
                "profile": profile,
                "customer_segment": classify_customer(self.request.user),
                "customer_health": assess_customer_health(self.request.user),
                "recent_logins": self.request.user.login_activities.all()[:6],
                "recent_notifications": self.request.user.email_notifications.exclude(
                    delivery_state=EmailNotification.DeliveryState.SKIPPED
                )[:8],
                "support_threads": support_queryset_for_user(self.request.user)[:6],
                "recent_orders": (
                    Order.objects.filter(user=self.request.user)
                    .exclude(status=Order.Status.CART)
                    .prefetch_related("items__item")[:4]
                ),
            }
        )
        return context


class AccountSettingsView(LoginRequiredMixin, TemplateView):
    template_name = "account_settings.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            build_account_settings_context(
                self.request,
                user_form=kwargs.get("user_form"),
                profile_form=kwargs.get("profile_form"),
                password_form=kwargs.get("password_form"),
                address_form=kwargs.get("address_form"),
                editing_address=kwargs.get("editing_address"),
            )
        )
        return context


class AccountProfileUpdateView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest) -> HttpResponse:
        profile = ensure_customer_profile(request.user)
        current_email = request.user.email
        user_form = AccountIdentityForm(
            request.POST,
            instance=request.user,
            prefix="user",
        )
        profile_form = CustomerProfileSettingsForm(
            request.POST,
            instance=profile,
            prefix="profile",
        )

        if user_form.is_valid() and profile_form.is_valid():
            updated_user = user_form.save()
            profile_form.save()
            if current_email.strip().lower() != updated_user.email.strip().lower():
                mark_email_unverified(updated_user)
                send_email_verification_email(updated_user, request=request)
                messages.info(
                    request,
                    "Email changed successfully. A new verification link has been queued for delivery.",
                )
            else:
                messages.success(request, "Account settings updated successfully.")
            return redirect("store:account-settings")

        return render(
            request,
            "account_settings.html",
            build_account_settings_context(
                request,
                user_form=user_form,
                profile_form=profile_form,
            ),
            status=400,
        )


class AccountPasswordChangeView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest) -> HttpResponse:
        password_form = AccountPasswordChangeForm(request.user, request.POST)
        if password_form.is_valid():
            updated_user = password_form.save()
            update_session_auth_hash(request, updated_user)
            messages.success(request, "Password updated successfully.")
            return redirect("store:account-settings")

        return render(
            request,
            "account_settings.html",
            build_account_settings_context(
                request,
                password_form=password_form,
            ),
            status=400,
        )


class AccountAddressUpsertView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, address_id: int | None = None) -> HttpResponse:
        editing_address = None
        if address_id is not None:
            editing_address = get_object_or_404(
                Address.objects.filter(user=request.user),
                pk=address_id,
            )

        address_form = AddressBookForm(
            request.POST,
            instance=editing_address,
            prefix="address",
        )
        if address_form.is_valid():
            address = address_form.save(commit=False)
            address.user = request.user
            if address.default:
                request.user.addresses.filter(
                    address_type=address.address_type,
                    default=True,
                ).exclude(pk=address.pk).update(default=False)
            address.save()
            messages.success(
                request,
                "Address saved successfully."
                if editing_address
                else "Address added successfully.",
            )
            return redirect("store:account-settings")

        return render(
            request,
            "account_settings.html",
            build_account_settings_context(
                request,
                address_form=address_form,
                editing_address=editing_address,
            ),
            status=400,
        )


class AccountAddressDeleteView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, address_id: int) -> HttpResponse:
        address = get_object_or_404(Address.objects.filter(user=request.user), pk=address_id)
        address.delete()
        messages.success(request, "Address removed.")
        return redirect("store:account-settings")


class AccountAddressDefaultView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, address_id: int) -> HttpResponse:
        address = get_object_or_404(Address.objects.filter(user=request.user), pk=address_id)
        request.user.addresses.filter(
            address_type=address.address_type,
            default=True,
        ).exclude(pk=address.pk).update(default=False)
        if not address.default:
            address.default = True
            address.save(update_fields=["default", "updated_at"])
        messages.success(request, "Default address updated.")
        return redirect("store:account-settings")


class OperationsDashboardView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = "operations_dashboard.html"

    def test_func(self):
        return can_view_operations_dashboard(self.request.user)

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            raise PermissionDenied
        return super().handle_no_permission()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(build_admin_dashboard(limit=8))
        return context


class InventoryDashboardView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = "inventory_dashboard.html"

    def test_func(self):
        return can_view_inventory_dashboard(self.request.user)

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            raise PermissionDenied
        return super().handle_no_permission()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            build_inventory_dashboard_context(
                adjustment_form=kwargs.get("adjustment_form"),
                transfer_form=kwargs.get("transfer_form"),
            )
        )
        return context


class InventoryManagementMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return can_manage_inventory_network(self.request.user)

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            raise PermissionDenied
        return super().handle_no_permission()


class InventoryAdjustmentView(InventoryManagementMixin, View):
    def post(self, request: HttpRequest) -> HttpResponse:
        adjustment_form = InventoryAdjustmentForm(request.POST, prefix="adjustment")
        transfer_form = InventoryTransferForm(prefix="transfer")
        if adjustment_form.is_valid():
            quantity = adjustment_form.cleaned_data["quantity"]
            if adjustment_form.cleaned_data["direction"] == InventoryAdjustmentForm.DIRECTION_OUT:
                quantity *= -1
            try:
                stock_level = adjust_stock_level(
                    actor=request.user,
                    item=adjustment_form.cleaned_data["item"],
                    warehouse=adjustment_form.cleaned_data["warehouse"],
                    quantity_delta=quantity,
                    reason=adjustment_form.cleaned_data["reason"],
                    reference=adjustment_form.cleaned_data.get("reference", ""),
                )
            except ValidationError as exc:
                adjustment_form.add_error(None, str(exc))
            else:
                messages.success(
                    request,
                    f"Inventory updated for {stock_level.item.title} in {stock_level.warehouse.code}.",
                )
                return redirect("store:inventory-dashboard")

        return render(
            request,
            "inventory_dashboard.html",
            build_inventory_dashboard_context(
                adjustment_form=adjustment_form,
                transfer_form=transfer_form,
            ),
            status=400,
        )


class InventoryTransferView(InventoryManagementMixin, View):
    def post(self, request: HttpRequest) -> HttpResponse:
        transfer_form = InventoryTransferForm(request.POST, prefix="transfer")
        adjustment_form = InventoryAdjustmentForm(prefix="adjustment")
        if transfer_form.is_valid():
            try:
                transfer_stock(
                    actor=request.user,
                    item=transfer_form.cleaned_data["item"],
                    source_warehouse=transfer_form.cleaned_data["source_warehouse"],
                    destination_warehouse=transfer_form.cleaned_data["destination_warehouse"],
                    quantity=transfer_form.cleaned_data["quantity"],
                    reason=transfer_form.cleaned_data["reason"],
                    reference=transfer_form.cleaned_data.get("reference", ""),
                )
            except ValidationError as exc:
                transfer_form.add_error(None, str(exc))
            else:
                messages.success(request, "Warehouse transfer completed successfully.")
                return redirect("store:inventory-dashboard")

        return render(
            request,
            "inventory_dashboard.html",
            build_inventory_dashboard_context(
                adjustment_form=adjustment_form,
                transfer_form=transfer_form,
            ),
            status=400,
        )


class CheckoutView(LoginRequiredMixin, FormView):
    template_name = "checkout.html"
    form_class = CheckoutForm
    success_url = reverse_lazy("store:order-history")

    def dispatch(self, request, *args, **kwargs):
        self.order = get_active_order(request.user)
        if not self.order or not self.order.items.exists():
            messages.info(request, "Your cart is empty. Add products before checkout.")
            return redirect("store:catalog")
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        if self.order and self.order.coupon:
            initial["coupon_code"] = self.order.coupon.code
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "order": self.order,
                "stripe_enabled": is_stripe_enabled(),
                "default_shipping_address": self.request.user.addresses.filter(
                    address_type=Address.AddressType.SHIPPING,
                    default=True,
                ).first(),
                "default_billing_address": self.request.user.addresses.filter(
                    address_type=Address.AddressType.BILLING,
                    default=True,
                ).first(),
            }
        )
        return context

    def form_valid(self, form):
        payment_method = form.cleaned_data["payment_method"]
        pending_order = None

        try:
            coupon_code = form.cleaned_data.get("coupon_code", "").strip()
            if coupon_code:
                apply_coupon_to_order(self.order, coupon_code)
            elif self.order.coupon_id:
                self.order.coupon = None
                self.order.coupon_usage_recorded = False
                self.order.save(update_fields=["coupon", "coupon_usage_recorded", "updated_at"])

            shipping_address = self._resolve_address(
                form=form,
                prefix="shipping",
                address_type=Address.AddressType.SHIPPING,
                use_default_key="use_default_shipping",
                save_default_key="save_shipping_as_default",
            )
            if form.cleaned_data["same_billing_address"]:
                billing_address = self._clone_address(
                    shipping_address,
                    Address.AddressType.BILLING,
                    form.cleaned_data["save_billing_as_default"],
                )
            else:
                billing_address = self._resolve_address(
                    form=form,
                    prefix="billing",
                    address_type=Address.AddressType.BILLING,
                    use_default_key="use_default_billing",
                    save_default_key="save_billing_as_default",
                )

            if payment_method == Order.PaymentMethod.STRIPE:
                pending_order = prepare_order_for_online_payment(
                    self.order,
                    shipping_address=shipping_address,
                    billing_address=billing_address,
                    customer_note=form.cleaned_data.get("customer_note", "").strip(),
                )
                session = create_stripe_checkout_session(self.request, pending_order)
                self.order = attach_payment_session(
                    pending_order,
                    provider="stripe",
                    session_id=session.id,
                    payload={
                        "checkout_url": getattr(session, "url", ""),
                        "checkout_status": getattr(session, "status", ""),
                    },
                )
                return redirect(session.url)

            self.order = place_order(
                self.order,
                shipping_address=shipping_address,
                billing_address=billing_address,
                payment_method=payment_method,
                customer_note=form.cleaned_data.get("customer_note", "").strip(),
            )
        except (ImproperlyConfigured, ValidationError) as exc:
            if pending_order:
                reopen_order_for_checkout(
                    pending_order,
                    reason="Stripe checkout session could not be created. Review your cart and try again.",
                    actor="stripe",
                    payment_status=Order.PaymentStatus.FAILED,
                )
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        except Exception:
            if pending_order:
                reopen_order_for_checkout(
                    pending_order,
                    reason="Stripe checkout is temporarily unavailable. Review your cart and try again.",
                    actor="stripe",
                    payment_status=Order.PaymentStatus.FAILED,
                )
            form.add_error(None, "Stripe checkout is temporarily unavailable.")
            return self.form_invalid(form)

        messages.success(
            self.request,
            f"Order {self.order.reference} placed successfully.",
        )
        send_order_placed_email(self.order)
        return super().form_valid(form)

    def _resolve_address(
        self,
        *,
        form: CheckoutForm,
        prefix: str,
        address_type: str,
        use_default_key: str,
        save_default_key: str,
    ) -> Address:
        if form.cleaned_data[use_default_key]:
            address = self.request.user.addresses.filter(
                address_type=address_type,
                default=True,
            ).first()
            if not address:
                raise ValidationError("A saved default address was not found.")
            return address

        payload = self._address_payload(form.cleaned_data, prefix)
        save_as_default = form.cleaned_data[save_default_key]
        if save_as_default:
            self.request.user.addresses.filter(
                address_type=address_type,
                default=True,
            ).update(default=False)
        return Address.objects.create(
            user=self.request.user,
            address_type=address_type,
            default=save_as_default,
            **payload,
        )

    def _clone_address(
        self,
        source: Address,
        address_type: str,
        save_as_default: bool,
    ) -> Address:
        if save_as_default:
            self.request.user.addresses.filter(
                address_type=address_type,
                default=True,
            ).update(default=False)
        return Address.objects.create(
            user=self.request.user,
            full_name=source.full_name,
            phone_number=source.phone_number,
            street_address=source.street_address,
            apartment_address=source.apartment_address,
            city=source.city,
            state=source.state,
            country=source.country,
            postal_code=source.postal_code,
            address_type=address_type,
            default=save_as_default,
        )

    @staticmethod
    def _address_payload(cleaned_data: dict, prefix: str) -> dict:
        return {
            "full_name": cleaned_data[f"{prefix}_full_name"],
            "phone_number": cleaned_data[f"{prefix}_phone_number"],
            "street_address": cleaned_data[f"{prefix}_street_address"],
            "apartment_address": cleaned_data[f"{prefix}_apartment_address"],
            "city": cleaned_data[f"{prefix}_city"],
            "state": cleaned_data[f"{prefix}_state"],
            "country": cleaned_data[f"{prefix}_country"],
            "postal_code": cleaned_data[f"{prefix}_postal_code"],
        }


class StripeCheckoutSuccessView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        session_id = request.GET.get("session_id", "").strip()
        if not session_id:
            messages.error(request, "Stripe did not return a checkout session reference.")
            return redirect("store:order-history")

        order = (
            Order.objects.filter(user=request.user, payment_session_id=session_id)
            .prefetch_related("items__item", "status_events")
            .first()
        )
        if not order:
            messages.error(request, "The checkout session could not be matched to an order.")
            return redirect("store:order-history")

        try:
            session = retrieve_stripe_checkout_session(session_id)
            session_payload = stripe_object_to_payload(session)
        except ImproperlyConfigured as exc:
            messages.error(request, str(exc))
            return redirect("store:order-history")
        except Exception:
            messages.info(
                request,
                "Payment confirmation is still processing. Refresh your order history shortly.",
            )
            return redirect("store:order-history")

        if session_payload.get("payment_status") == "paid":
            try:
                confirmed_order = finalize_paid_order(
                    order,
                    payment_reference=session_payload.get("payment_intent") or session_id,
                    payment_session_id=session_id,
                    payment_payload=session_payload,
                    actor="stripe-success",
                )
            except ValidationError as exc:
                messages.info(request, str(exc))
            else:
                send_payment_received_email(confirmed_order)
                messages.success(
                    request,
                    f"Stripe payment confirmed for order {order.reference}.",
                )
        else:
            messages.info(
                request,
                "Stripe is still finalizing your payment. Check order history again shortly.",
            )
        return redirect("store:order-history")


class StripeCheckoutCancelView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest, reference: str) -> HttpResponse:
        order = get_object_or_404(Order.objects.filter(user=request.user), reference=reference)
        order = reopen_order_for_checkout(
            order,
            reason="Stripe payment was cancelled. Your cart is ready for checkout again.",
            actor=request.user.username,
            payment_status=Order.PaymentStatus.UNPAID,
            payment_payload={"cancelled_at": timezone.now().isoformat()},
        )
        if order.status == Order.Status.CART:
            messages.info(request, "Stripe payment was cancelled. Your cart is open again.")
            return redirect("store:checkout")

        messages.info(request, "This order is no longer awaiting Stripe payment.")
        return redirect("store:order-history")


class AccountLoginView(LoginView):
    template_name = "account.html"
    form_class = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        ensure_customer_profile(self.request.user)
        record_login_activity(self.request.user, self.request)
        return response


class SignUpView(FormView):
    template_name = "signup.html"
    form_class = SignUpForm
    success_url = reverse_lazy("store:home")

    def form_valid(self, form):
        user = form.save()
        ensure_customer_profile(user)
        auth_login(self.request, user)
        record_login_activity(user, self.request)
        send_email_verification_email(user, request=self.request)
        messages.success(
            self.request,
            "Your account is ready. A verification email has been queued for delivery.",
        )
        return redirect(self.get_success_url())


class VerifyEmailView(View):
    def get(self, request: HttpRequest, token: str) -> HttpResponse:
        try:
            user_id, email = resolve_email_verification_token(token)
        except signing.SignatureExpired:
            messages.error(request, "That verification link has expired. Request a fresh one from your dashboard.")
            return redirect("store:login")
        except signing.BadSignature:
            messages.error(request, "The verification link is invalid.")
            return redirect("store:login")

        user = get_object_or_404(User, pk=user_id, email=email)
        mark_email_verified(user)
        messages.success(request, "Email verification completed for your Redstore account.")
        if request.user.is_authenticated:
            return redirect("store:account-dashboard")
        return redirect("store:login")


class ResendVerificationEmailView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest) -> HttpResponse:
        profile = ensure_customer_profile(request.user)
        if profile.email_verified:
            messages.info(request, "Your email is already verified.")
        else:
            send_email_verification_email(request.user, request=request)
            messages.success(request, "A fresh verification email has been queued for delivery.")
        return redirect(request.POST.get("next") or "store:account-dashboard")


class AddToCartView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, slug: str) -> HttpResponse:
        item = get_object_or_404(Item.objects.active(), slug=slug)
        form = AddToCartForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Choose a valid quantity.")
            return redirect(item.get_absolute_url())

        try:
            order_item = add_item_to_cart(
                request.user,
                item,
                form.cleaned_data["quantity"],
            )
        except ValidationError as exc:
            messages.error(request, exc.message)
            return redirect(item.get_absolute_url())

        messages.success(
            request,
            f"{order_item.item.title} is now in your cart.",
        )
        return redirect(request.POST.get("next") or "store:cart")


class ApplyCouponView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest) -> HttpResponse:
        form = ApplyCouponForm(request.POST)
        order = get_active_order(request.user)
        if not order:
            messages.info(request, "You do not have an active cart.")
            return redirect("store:cart")
        if not form.is_valid():
            messages.error(request, "Enter a valid coupon code.")
            return redirect("store:cart")
        try:
            coupon = apply_coupon_to_order(order, form.cleaned_data["code"])
        except ValidationError as exc:
            messages.error(request, exc.message)
        else:
            messages.success(request, f"Coupon {coupon.code} applied to your cart.")
        return redirect("store:cart")


class SubmitReviewView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, slug: str) -> HttpResponse:
        item = get_object_or_404(Item.objects.active(), slug=slug)
        form = ReviewForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Please provide a valid review.")
            return redirect(item.get_absolute_url())

        review = submit_review(
            request.user,
            item,
            rating=form.cleaned_data["rating"],
            title=form.cleaned_data["title"],
            comment=form.cleaned_data["comment"],
        )
        messages.success(request, f"Review saved for {review.item.title}.")
        return redirect(item.get_absolute_url())


class ToggleWishlistView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, slug: str) -> HttpResponse:
        item = get_object_or_404(Item.objects.active(), slug=slug)
        added = toggle_wishlist(request.user, item)
        if added:
            messages.success(request, f"{item.title} added to your wishlist.")
        else:
            messages.info(request, f"{item.title} removed from your wishlist.")
        return redirect(request.POST.get("next") or item.get_absolute_url())


class ToggleCompareView(View):
    def post(self, request: HttpRequest, slug: str) -> HttpResponse:
        item = get_object_or_404(Item.objects.active(), slug=slug)
        result = toggle_compare_item(request, item)
        if result["added"]:
            if result["trimmed"]:
                messages.info(
                    request,
                    f"{item.title} added to compare. The oldest compare item was removed to keep the list focused.",
                )
            else:
                messages.success(request, f"{item.title} added to compare.")
        else:
            messages.info(request, f"{item.title} removed from compare.")
        return redirect(request.POST.get("next") or item.get_absolute_url())


class ReturnRequestCreateView(LoginRequiredMixin, FormView):
    template_name = "return_request.html"
    form_class = ReturnRequestForm
    success_url = reverse_lazy("store:order-history")

    def dispatch(self, request, *args, **kwargs):
        self.order = get_object_or_404(
            Order.objects.filter(user=request.user).prefetch_related("items__item", "return_requests"),
            reference=kwargs["reference"],
        )
        self.order_item = get_object_or_404(
            OrderItem.objects.select_related("item"),
            pk=kwargs["order_item_id"],
            user=request.user,
        )
        if not self.order.items.filter(pk=self.order_item.pk).exists():
            messages.error(request, "That product is not part of the selected order.")
            return redirect("store:order-history")
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        initial["quantity"] = 1
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "order": self.order,
                "order_item": self.order_item,
                "existing_return_requests": self.order.return_requests.filter(order_item=self.order_item),
            }
        )
        return context

    def form_valid(self, form):
        try:
            return_request = submit_return_request(
                self.request.user,
                self.order,
                self.order_item,
                quantity=form.cleaned_data["quantity"],
                reason=form.cleaned_data["reason"],
                details=form.cleaned_data.get("details", "").strip(),
            )
        except ValidationError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        send_return_requested_email(return_request)
        messages.success(
            self.request,
            f"Return request submitted for {self.order_item.item.title}.",
        )
        return super().form_valid(form)


class SupportInboxView(LoginRequiredMixin, FormView):
    template_name = "support_threads.html"
    form_class = SupportThreadForm
    success_url = reverse_lazy("store:support-threads")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["support_threads"] = support_queryset_for_user(self.request.user)[:15]
        return context

    def form_valid(self, form):
        try:
            thread = create_support_thread(
                self.request.user,
                subject=form.cleaned_data["subject"],
                category=form.cleaned_data["category"],
                priority=form.cleaned_data["priority"],
                message=form.cleaned_data["message"],
                order=form.cleaned_data.get("order"),
            )
        except ValidationError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        messages.success(self.request, "Support conversation opened.")
        return redirect("store:support-thread-detail", thread_id=thread.pk)


class SupportThreadDetailView(LoginRequiredMixin, FormView):
    template_name = "support_thread_detail.html"
    form_class = SupportMessageForm

    def dispatch(self, request, *args, **kwargs):
        self.thread = get_object_or_404(
            support_queryset_for_user(request.user),
            pk=kwargs["thread_id"],
        )
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse("store:support-thread-detail", kwargs={"thread_id": self.thread.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "thread": self.thread,
                "suggested_articles": self.thread.auto_reply_snapshot,
            }
        )
        return context

    def form_valid(self, form):
        try:
            support_message = post_support_message(
                self.thread,
                self.request.user,
                message=form.cleaned_data["message"],
            )
        except ValidationError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        self.thread.refresh_from_db()
        if can_manage_support_threads(self.request.user):
            send_support_reply_email(self.thread, support_message)
        messages.success(self.request, "Message posted to the support conversation.")
        return super().form_valid(form)


class ResolveSupportThreadView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, thread_id: int) -> HttpResponse:
        thread = get_object_or_404(
            support_queryset_for_user(request.user),
            pk=thread_id,
        )
        resolve_support_thread(thread, actor=request.user)
        messages.success(request, "Support conversation marked as resolved.")
        next_url = request.POST.get("next", "").strip()
        if next_url:
            return redirect(next_url)
        return redirect("store:support-thread-detail", thread_id=thread.pk)


class RemoveFromCartView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, slug: str) -> HttpResponse:
        item = get_object_or_404(Item, slug=slug)
        removed = remove_item_from_cart(request.user, item)
        if removed:
            messages.info(request, f"{item.title} was removed from your cart.")
        else:
            messages.info(request, "That item was not in your cart.")
        return redirect("store:cart")


class DecreaseCartItemView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, slug: str) -> HttpResponse:
        item = get_object_or_404(Item, slug=slug)
        order_item = decrease_item_quantity(request.user, item)
        if order_item:
            messages.success(
                request,
                f"Updated {item.title} quantity to {order_item.quantity}.",
            )
        else:
            messages.info(request, f"{item.title} was removed from your cart.")
        return redirect("store:cart")


def legacy_products_page(request: HttpRequest, page_number: int) -> HttpResponse:
    return redirect(f"{reverse('store:catalog')}?page={page_number}")


def legacy_product_detail_redirect(request: HttpRequest) -> HttpResponse:
    return redirect("store:catalog")


@login_required
def logout_view(request: HttpRequest) -> HttpResponse:
    auth_logout(request)
    messages.info(request, "You have been signed out.")
    return redirect("store:home")


@require_GET
def health_check(request: HttpRequest) -> JsonResponse:
    return JsonResponse(
        {
            "status": "ok",
            "application": "redstore",
            "catalog_items": Item.objects.filter(is_active=True).count(),
            "pending_payments": Order.objects.filter(status=Order.Status.PAYMENT_PENDING).count(),
            "open_support_threads": SupportThread.objects.exclude(
                status__in=[SupportThread.Status.RESOLVED, SupportThread.Status.CLOSED]
            ).count(),
            "timestamp": timezone.now().isoformat(),
        }
    )


@csrf_exempt
@require_POST
def stripe_webhook(request: HttpRequest) -> HttpResponse:
    signature = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    try:
        event = construct_stripe_event(request.body, signature)
    except ImproperlyConfigured:
        return HttpResponse(status=503)
    except ValueError:
        return HttpResponse(status=400)
    except Exception:
        return HttpResponse(status=400)

    event_type = event["type"]
    session_payload = stripe_object_to_payload(event["data"]["object"])
    metadata = session_payload.get("metadata") or {}
    order_reference = metadata.get("order_reference")
    if not order_reference:
        return HttpResponse(status=200)

    order = Order.objects.filter(reference=order_reference).first()
    if not order:
        return HttpResponse(status=200)

    if event_type in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        if session_payload.get("payment_status") == "paid":
            try:
                confirmed_order = finalize_paid_order(
                    order,
                    payment_reference=session_payload.get("payment_intent") or session_payload.get("id", ""),
                    payment_session_id=session_payload.get("id", ""),
                    payment_payload=session_payload,
                    actor="stripe-webhook",
                )
            except ValidationError:
                return HttpResponse(status=200)
            send_payment_received_email(confirmed_order)

    if event_type == "checkout.session.async_payment_failed":
        reopen_order_for_checkout(
            order,
            reason="Stripe payment failed or expired. Your cart was reopened.",
            actor="stripe-webhook",
            payment_status=Order.PaymentStatus.FAILED,
            payment_payload=session_payload,
        )
    if event_type == "checkout.session.expired":
        reopen_order_for_checkout(
            order,
            reason="Stripe payment session expired. Your cart was reopened.",
            actor="stripe-webhook",
            payment_status=Order.PaymentStatus.FAILED,
            payment_payload=session_payload,
            reservation_status="expired",
        )

    return HttpResponse(status=200)
