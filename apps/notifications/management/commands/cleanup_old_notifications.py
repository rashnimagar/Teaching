from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.notifications.models import Notification


class Command(BaseCommand):
    help = "Prunes old read notifications older than a given number of days."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=90,
            help="Number of days to keep read notifications (default: 90).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulate cleanup and print count without deleting records.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        dry_run = options["dry_run"]
        cutoff = timezone.now() - timedelta(days=days)

        qs = Notification.objects.filter(read_at__isnull=False, read_at__lt=cutoff)
        count = qs.count()

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"[DRY-RUN] {count} read notification(s) older than {days} days ({cutoff.isoformat()}) would be deleted."
                )
            )
            return

        deleted_count, _ = qs.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully deleted {deleted_count} read notification(s) older than {days} days."
            )
        )
