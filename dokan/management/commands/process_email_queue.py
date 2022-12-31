from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand

from dokan.notifications import process_pending_email_queue


class Command(BaseCommand):
    help = "Deliver queued Redstore email notifications from the database outbox."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=getattr(settings, "EMAIL_QUEUE_BATCH_SIZE", 25),
            help="Maximum number of queued notifications to process in this run.",
        )
        parser.add_argument(
            "--include-failed",
            action="store_true",
            help="Retry notifications that previously failed delivery.",
        )
        parser.add_argument(
            "--kind",
            action="append",
            dest="kinds",
            help="Optional notification kind filter. Can be supplied multiple times.",
        )

    def handle(self, *args, **options):
        summary = process_pending_email_queue(
            limit=options["limit"],
            kinds=options.get("kinds") or None,
            include_failed=options["include_failed"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Processed {processed} queued notifications: {sent} sent, {failed} failed, {skipped} skipped.".format(
                    **summary
                )
            )
        )
