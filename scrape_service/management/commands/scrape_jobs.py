"""
Usage:
  python manage.py scrape_jobs                    # probe one batch, resuming from MAX(Job.linkedin_id) + 1
  python manage.py scrape_jobs --start 4056789     # start from a specific job ID instead
  python manage.py scrape_jobs --batch 100         # override how many IDs to probe this run
  python manage.py scrape_jobs --continuous        # run forever until interrupted (Ctrl+C)
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from scrape_service.services.linkedin_scraper import run_scraper


class Command(BaseCommand):
    help = "Iterate LinkedIn job IDs and scrape any that are live."

    def add_arguments(self, parser):
        parser.add_argument(
            "--start",
            type=int,
            default=None,
            help="Start from this job ID instead of resuming from MAX(Job.linkedin_id) + 1.",
        )
        parser.add_argument(
            "--batch",
            type=int,
            default=None,
            help="How many IDs to probe this run (ignored with --continuous). Default: SCRAPER_BATCH_SIZE setting.",
        )
        parser.add_argument(
            "--continuous",
            action="store_true",
            default=False,
            help="Keep probing indefinitely until interrupted (Ctrl+C).",
        )

    def handle(self, *args, **options):
        start_id = options.get("start")
        batch_size = options.get("batch")
        continuous = options.get("continuous")

        limit = None if continuous else (batch_size or getattr(settings, "SCRAPER_BATCH_SIZE", 50))

        if continuous:
            self.stdout.write(
                self.style.WARNING("Continuous mode enabled. Press Ctrl+C to stop.")
            )

        try:
            stats = run_scraper(start_id=start_id, limit=limit)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nStopped by user. Progress saved."))
            return

        if "error" in stats:
            raise CommandError(stats["error"])

        self.stdout.write(
            self.style.SUCCESS(
                f'Done. Checked: {stats["ids_checked"]} IDs | '
                f'Found: {stats["jobs_found"]} jobs | '
                f'New: {stats["jobs_new"]} | '
                f'Alerts: {stats["alerts_sent"]}'
            )
        )
