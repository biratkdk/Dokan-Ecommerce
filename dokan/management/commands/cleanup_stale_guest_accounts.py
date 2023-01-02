from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = (
        "Delete guest checkout accounts (unusable password) that never placed an "
        "order, so an abandoned-cart visit doesn't accumulate a User row forever."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Treat guest accounts older than this many days as stale.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show which accounts would be deleted without modifying them.",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        threshold = timezone.now() - timedelta(days=options["days"])

        # Never touch a guest with ANY order history -- cart, placed, or
        # otherwise. This only clears out identities that were created (by
        # get_or_create_cart_user) and then genuinely abandoned before ever
        # adding anything, or whose cart was already merged/checked out and
        # cleared elsewhere.
        candidates = User.objects.filter(
            username__startswith="guest-",
            date_joined__lt=threshold,
            orders__isnull=True,
        ).distinct()

        if options["dry_run"]:
            for user in candidates:
                self.stdout.write(f"Would delete {user.username} (joined {user.date_joined.isoformat()}).")
            self.stdout.write(self.style.WARNING(f"Dry run complete. {candidates.count()} accounts matched."))
            return

        deleted_count = candidates.count()
        candidates.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_count} stale guest accounts."))
