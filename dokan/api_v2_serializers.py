from __future__ import annotations

from rest_framework import serializers

from .models import Address, CustomerProfile, Item, Warehouse


class AccountProfileUpdatePayloadSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150, allow_blank=True, required=False)
    last_name = serializers.CharField(max_length=150, allow_blank=True, required=False)
    phone_number = serializers.CharField(max_length=20, allow_blank=True, required=False)
    company_name = serializers.CharField(max_length=120, allow_blank=True, required=False)
    job_title = serializers.CharField(max_length=120, allow_blank=True, required=False)
    preferred_contact_channel = serializers.ChoiceField(
        choices=CustomerProfile.PreferredContactChannel.choices
    )
    marketing_opt_in = serializers.BooleanField(required=False, default=True)


class AddressPayloadSerializer(serializers.ModelSerializer):
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


class PasswordChangePayloadSerializer(serializers.Serializer):
    old_password = serializers.CharField()
    new_password1 = serializers.CharField()
    new_password2 = serializers.CharField()


class ApiTokenRequestSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()


class InventoryAdjustmentPayloadSerializer(serializers.Serializer):
    item = serializers.PrimaryKeyRelatedField(queryset=Item.objects.active())
    warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.objects.filter(is_active=True))
    quantity = serializers.IntegerField(min_value=1)
    direction = serializers.ChoiceField(
        choices=("increase", "decrease"),
    )
    reason = serializers.CharField(max_length=255)
    reference = serializers.CharField(
        max_length=80,
        allow_blank=True,
        required=False,
        default="",
    )


class InventoryTransferPayloadSerializer(serializers.Serializer):
    item = serializers.PrimaryKeyRelatedField(queryset=Item.objects.active())
    source_warehouse = serializers.PrimaryKeyRelatedField(
        queryset=Warehouse.objects.filter(is_active=True)
    )
    destination_warehouse = serializers.PrimaryKeyRelatedField(
        queryset=Warehouse.objects.filter(is_active=True)
    )
    quantity = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=255)
    reference = serializers.CharField(
        max_length=80,
        allow_blank=True,
        required=False,
        default="",
    )

    def validate(self, attrs):
        if attrs["source_warehouse"].pk == attrs["destination_warehouse"].pk:
            raise serializers.ValidationError(
                "Choose two different warehouses for a transfer."
            )
        return attrs
