from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from dokan.models import InventoryReservation, Order
from dokan.services import release_expired_reservations


class Command(BaseCommand):
    help = "Release expired inventory reservations for abandoned payment-pending orders."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show which active reservations are expired without modifying them.",
        )

    def handle(self, *args, **options):
        now = timezone.now()
        queryset = InventoryReservation.objects.filter(
            status=InventoryReservation.Status.ACTIVE,
            expires_at__lt=now,
            order__status=Order.Status.PAYMENT_PENDING,
        ).select_related("order", "item", "warehouse")

        if options["dry_run"]:
            for reservation in queryset.order_by("expires_at", "order__reference"):
                self.stdout.write(
                    (
                        f"Would release reservation {reservation.pk} for order "
                        f"{reservation.order.reference} ({reservation.item.title} x {reservation.quantity}) "
                        f"from warehouse {reservation.warehouse.code}."
                    )
                )
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run complete. {queryset.count()} expired active reservations matched."
                )
            )
            return

        reopened_orders = release_expired_reservations(at_time=now)
        self.stdout.write(
            self.style.SUCCESS(
                f"Released expired reservations and reopened {reopened_orders} payment-pending orders."
            )
        )
