from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import Order, ProductReview, ReturnRequest, SupportMessage, SupportThread


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
