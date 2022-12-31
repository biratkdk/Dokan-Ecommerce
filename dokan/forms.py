from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm,
    UserCreationForm,
)

from .models import (
    Address,
    CustomerProfile,
    Item,
    Order,
    ProductReview,
    ReturnRequest,
    Warehouse,
    SupportMessage,
    SupportThread,
)


User = get_user_model()


def _apply_input_style(field: forms.Field, *, placeholder: str = "") -> None:
    if isinstance(field.widget, (forms.CheckboxInput, forms.RadioSelect)):
        return
    existing = field.widget.attrs.get("class", "")
    field.widget.attrs["class"] = f"{existing} checkout-input".strip()
    if placeholder:
        field.widget.attrs["placeholder"] = placeholder


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={"class": "auth-input", "placeholder": "Username"}
        ),
    )
    password = forms.CharField(
        strip=False,
        widget=forms.PasswordInput(
            attrs={"class": "auth-input", "placeholder": "Password"}
        ),
    )


class SignUpForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(
            attrs={"class": "auth-input", "placeholder": "Email address"}
        ),
    )

    class Meta:
        model = User
        fields = ["username", "email", "password1", "password2"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {"class": "auth-input", "placeholder": "Choose a username"}
        )
        self.fields["password1"].widget.attrs.update(
            {"class": "auth-input", "placeholder": "Create a password"}
        )
        self.fields["password2"].widget.attrs.update(
            {"class": "auth-input", "placeholder": "Confirm your password"}
        )

    def save(self, commit: bool = True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class PasswordResetRequestForm(PasswordResetForm):
    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={"class": "auth-input", "placeholder": "Email address"}
        ),
    )


class PasswordResetConfirmForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].widget.attrs.update(
            {"class": "auth-input", "placeholder": "Create a new password"}
        )
        self.fields["new_password2"].widget.attrs.update(
            {"class": "auth-input", "placeholder": "Confirm the new password"}
        )


class AccountIdentityForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        placeholders = {
            "username": "Username",
            "first_name": "First name",
            "last_name": "Last name",
            "email": "Email address",
        }
        for field_name, placeholder in placeholders.items():
            _apply_input_style(self.fields[field_name], placeholder=placeholder)


class CustomerProfileSettingsForm(forms.ModelForm):
    class Meta:
        model = CustomerProfile
        fields = [
            "phone_number",
            "company_name",
            "job_title",
            "preferred_contact_channel",
            "marketing_opt_in",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        placeholders = {
            "phone_number": "Primary phone number",
            "company_name": "Company or organization",
            "job_title": "Job title",
        }
        for field_name, placeholder in placeholders.items():
            _apply_input_style(self.fields[field_name], placeholder=placeholder)
        _apply_input_style(self.fields["preferred_contact_channel"])


class AddressBookForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = [
            "full_name",
            "phone_number",
            "street_address",
            "apartment_address",
            "city",
            "state",
            "country",
            "postal_code",
            "address_type",
            "default",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        placeholders = {
            "full_name": "Full name",
            "phone_number": "Phone number",
            "street_address": "Street address",
            "apartment_address": "Apartment, suite, etc. (optional)",
            "city": "City",
            "state": "State or province",
            "country": "Country",
            "postal_code": "Postal code",
        }
        for field_name, placeholder in placeholders.items():
            _apply_input_style(self.fields[field_name], placeholder=placeholder)
        _apply_input_style(self.fields["address_type"])


class AccountPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        placeholders = {
            "old_password": "Current password",
            "new_password1": "New password",
            "new_password2": "Confirm new password",
        }
        for field_name, placeholder in placeholders.items():
            self.fields[field_name].widget.attrs.update(
                {"class": "auth-input", "placeholder": placeholder}
            )


class InventoryAdjustmentForm(forms.Form):
    DIRECTION_IN = "increase"
    DIRECTION_OUT = "decrease"

    item = forms.ModelChoiceField(
        queryset=Item.objects.none(),
        widget=forms.Select(attrs={"class": "checkout-input"}),
    )
    warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.none(),
        widget=forms.Select(attrs={"class": "checkout-input"}),
    )
    direction = forms.ChoiceField(
        choices=(
            (DIRECTION_IN, "Increase on-hand stock"),
            (DIRECTION_OUT, "Decrease on-hand stock"),
        ),
        widget=forms.Select(attrs={"class": "checkout-input"}),
    )
    quantity = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "checkout-input", "min": 1}),
    )
    reason = forms.CharField(
        max_length=255,
        widget=forms.TextInput(
            attrs={
                "class": "checkout-input",
                "placeholder": "Reason for the stock adjustment",
            }
        ),
    )
    reference = forms.CharField(
        max_length=80,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "checkout-input",
                "placeholder": "Reference ID (optional)",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = Item.objects.active().order_by("title")
        self.fields["warehouse"].queryset = Warehouse.objects.filter(is_active=True).order_by(
            "priority",
            "name",
        )


class InventoryTransferForm(forms.Form):
    item = forms.ModelChoiceField(
        queryset=Item.objects.none(),
        widget=forms.Select(attrs={"class": "checkout-input"}),
    )
    source_warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.none(),
        widget=forms.Select(attrs={"class": "checkout-input"}),
    )
    destination_warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.none(),
        widget=forms.Select(attrs={"class": "checkout-input"}),
    )
    quantity = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "checkout-input", "min": 1}),
    )
    reason = forms.CharField(
        max_length=255,
        widget=forms.TextInput(
            attrs={
                "class": "checkout-input",
                "placeholder": "Reason for the warehouse transfer",
            }
        ),
    )
    reference = forms.CharField(
        max_length=80,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "checkout-input",
                "placeholder": "Transfer or batch reference (optional)",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        active_warehouses = Warehouse.objects.filter(is_active=True).order_by("priority", "name")
        self.fields["item"].queryset = Item.objects.active().order_by("title")
        self.fields["source_warehouse"].queryset = active_warehouses
        self.fields["destination_warehouse"].queryset = active_warehouses

    def clean(self):
        cleaned_data = super().clean()
        source_warehouse = cleaned_data.get("source_warehouse")
        destination_warehouse = cleaned_data.get("destination_warehouse")
        if (
            source_warehouse
            and destination_warehouse
            and source_warehouse.pk == destination_warehouse.pk
        ):
            raise forms.ValidationError("Choose two different warehouses for a transfer.")
        return cleaned_data


class AddToCartForm(forms.Form):
    quantity = forms.IntegerField(
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={"class": "qty-input"}),
    )


class ApplyCouponForm(forms.Form):
    code = forms.CharField(
        max_length=30,
        widget=forms.TextInput(
            attrs={"class": "checkout-input", "placeholder": "Coupon code"}
        ),
    )


class ReviewForm(forms.ModelForm):
    class Meta:
        model = ProductReview
        fields = ["rating", "title", "comment"]
        widgets = {
            "rating": forms.Select(
                choices=((5, "5 - Excellent"), (4, "4 - Good"), (3, "3 - Average"), (2, "2 - Weak"), (1, "1 - Poor")),
                attrs={"class": "checkout-input"},
            ),
            "title": forms.TextInput(
                attrs={"class": "checkout-input", "placeholder": "Review title"}
            ),
            "comment": forms.Textarea(
                attrs={
                    "class": "checkout-input",
                    "placeholder": "Write an honest product review",
                    "rows": 4,
                }
            ),
        }


class ReturnRequestForm(forms.ModelForm):
    class Meta:
        model = ReturnRequest
        fields = ["quantity", "reason", "details"]
        widgets = {
            "quantity": forms.NumberInput(
                attrs={"class": "checkout-input", "min": 1}
            ),
            "reason": forms.Select(attrs={"class": "checkout-input"}),
            "details": forms.Textarea(
                attrs={
                    "class": "checkout-input",
                    "rows": 4,
                    "placeholder": "Describe the issue with the delivered product",
                }
            ),
        }


class SupportThreadForm(forms.ModelForm):
    order = forms.ModelChoiceField(
        queryset=Order.objects.none(),
        required=False,
        empty_label="General inquiry",
        widget=forms.Select(attrs={"class": "checkout-input"}),
    )

    class Meta:
        model = SupportThread
        fields = ["subject", "category", "priority", "order"]
        widgets = {
            "subject": forms.TextInput(
                attrs={
                    "class": "checkout-input",
                    "placeholder": "Short summary of the issue",
                }
            ),
            "category": forms.Select(attrs={"class": "checkout-input"}),
            "priority": forms.Select(attrs={"class": "checkout-input"}),
            "message": forms.Textarea(
                attrs={
                    "class": "checkout-input",
                    "rows": 5,
                    "placeholder": "Describe the problem, your order context, and what help you need.",
                }
            ),
        }

    message = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": "checkout-input",
                "rows": 5,
                "placeholder": "Describe the problem, your order context, and what help you need.",
            }
        )
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and user.is_authenticated:
            self.fields["order"].queryset = (
                Order.objects.filter(user=user)
                .exclude(status=Order.Status.CART)
                .order_by("-created_at")
            )


class SupportMessageForm(forms.ModelForm):
    class Meta:
        model = SupportMessage
        fields = ["message"]
        widgets = {
            "message": forms.Textarea(
                attrs={
                    "class": "checkout-input",
                    "rows": 4,
                    "placeholder": "Write your message to support",
                }
            )
        }


class CheckoutForm(forms.Form):
    use_default_shipping = forms.BooleanField(required=False)
    shipping_full_name = forms.CharField(required=False)
    shipping_phone_number = forms.CharField(required=False)
    shipping_street_address = forms.CharField(required=False)
    shipping_apartment_address = forms.CharField(required=False)
    shipping_city = forms.CharField(required=False)
    shipping_state = forms.CharField(required=False)
    shipping_country = forms.CharField(required=False)
    shipping_postal_code = forms.CharField(required=False)
    save_shipping_as_default = forms.BooleanField(required=False)

    same_billing_address = forms.BooleanField(required=False)
    use_default_billing = forms.BooleanField(required=False)
    billing_full_name = forms.CharField(required=False)
    billing_phone_number = forms.CharField(required=False)
    billing_street_address = forms.CharField(required=False)
    billing_apartment_address = forms.CharField(required=False)
    billing_city = forms.CharField(required=False)
    billing_state = forms.CharField(required=False)
    billing_country = forms.CharField(required=False)
    billing_postal_code = forms.CharField(required=False)
    save_billing_as_default = forms.BooleanField(required=False)

    coupon_code = forms.CharField(required=False)
    customer_note = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "checkout-input",
                "rows": 3,
                "placeholder": "Optional delivery instructions or order note",
            }
        ),
    )
    payment_method = forms.ChoiceField(
        choices=Order.PaymentMethod.choices,
        widget=forms.RadioSelect,
    )

    ADDRESS_PLACEHOLDERS = {
        "full_name": "Full name",
        "phone_number": "Phone number",
        "street_address": "Street address",
        "apartment_address": "Apartment, suite, etc. (optional)",
        "city": "City",
        "state": "State or Province",
        "country": "Country",
        "postal_code": "Postal code",
    }

    REQUIRED_ADDRESS_FIELDS = (
        "full_name",
        "phone_number",
        "street_address",
        "city",
        "state",
        "country",
        "postal_code",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for prefix in ("shipping", "billing"):
            for field_name, placeholder in self.ADDRESS_PLACEHOLDERS.items():
                _apply_input_style(
                    self.fields[f"{prefix}_{field_name}"],
                    placeholder=placeholder,
                )
        _apply_input_style(self.fields["coupon_code"], placeholder="Coupon code")

    def clean(self):
        cleaned_data = super().clean()
        self._validate_address_block(cleaned_data, "shipping", "use_default_shipping")
        if not cleaned_data.get("same_billing_address"):
            self._validate_address_block(cleaned_data, "billing", "use_default_billing")
        return cleaned_data

    def _validate_address_block(
        self,
        cleaned_data: dict,
        prefix: str,
        use_default_key: str,
    ) -> None:
        if cleaned_data.get(use_default_key):
            return

        for field_name in self.REQUIRED_ADDRESS_FIELDS:
            key = f"{prefix}_{field_name}"
            if not cleaned_data.get(key):
                label = field_name.replace("_", " ").capitalize()
                self.add_error(key, f"{label} is required.")


class createuserform(SignUpForm):
    """Backward-compatible alias for older imports."""
