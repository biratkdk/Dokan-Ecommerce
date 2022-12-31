from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from dokan.models import InventoryReservation, Order
from dokan.services import reopen_order_for_checkout


class Command(BaseCommand):
    help = "Reopen stale payment-pending orders so they do not remain locked indefinitely."

    def add_arguments(self, parser):
        parser.add_argument(
            "--minutes",
            type=int,
            default=30,
            help="Treat payment-pending orders older than this many minutes as stale.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show which orders would be reopened without modifying them.",
        )

    def handle(self, *args, **options):
        threshold = timezone.now() - timedelta(minutes=options["minutes"])
        queryset = Order.objects.filter(
            status=Order.Status.PAYMENT_PENDING,
            payment_status=Order.PaymentStatus.PENDING,
            placed_at__lt=threshold,
        ).order_by("placed_at")

        if options["dry_run"]:
            for order in queryset:
                self.stdout.write(
                    f"Would reopen {order.reference} from {order.placed_at.isoformat()}."
                )
            self.stdout.write(
                self.style.WARNING(f"Dry run complete. {queryset.count()} orders matched.")
            )
            return

        reopened = 0
        for order in queryset:
            reopen_order_for_checkout(
                order,
                reason="Pending Stripe checkout expired and the cart was reopened automatically.",
                actor="cleanup-command",
                payment_status=Order.PaymentStatus.FAILED,
                payment_payload={"expired_cleanup_at": timezone.now().isoformat()},
                reservation_status=InventoryReservation.Status.EXPIRED,
            )
            reopened += 1

        self.stdout.write(
            self.style.SUCCESS(f"Reopened {reopened} stale payment-pending orders.")
        )
