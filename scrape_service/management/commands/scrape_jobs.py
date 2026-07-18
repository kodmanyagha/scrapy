"""
Usage:
  python manage.py scrape_jobs                        # run one batch (uses active ScrapeConfig)
  python manage.py scrape_jobs --start 4056789        # set a new start ID and run
  python manage.py scrape_jobs --batch 100            # override batch size for this run
  python manage.py scrape_jobs --continuous           # loop forever, batch after batch
  python manage.py scrape_jobs --continuous --pause 10  # wait 10s between batches
"""

import time

from django.core.management.base import BaseCommand, CommandError
from scrape_service.services.linkedin_scraper import run_scraper
from scrape_service.models import ScrapeConfig


class Command(BaseCommand):
    help = "Iterate LinkedIn job IDs and scrape any that are live."

    def add_arguments(self, parser):
        parser.add_argument(
            "--start",
            type=int,
            default=None,
            help="Set a new starting job ID (creates/updates the active ScrapeConfig).",
        )
        parser.add_argument(
            "--batch",
            type=int,
            default=None,
            help="Override the batch size (number of IDs to probe) for this run only.",
        )
        parser.add_argument(
            "--continuous",
            action="store_true",
            default=False,
            help="Keep running batches indefinitely until interrupted (Ctrl+C).",
        )
        parser.add_argument(
            "--pause",
            type=int,
            default=0,
            help="Seconds to wait between batches in --continuous mode (default: 0).",
        )

    def handle(self, *args, **options):
        start_id = options.get("start")
        batch_size = options.get("batch")
        continuous = options.get("continuous")
        pause: int = options.get("pause") or 0

        # If a new start ID is given, create a fresh config
        if start_id is not None:
            # Deactivate old configs
            ScrapeConfig.objects.filter(is_active=True).update(is_active=False)
            config = ScrapeConfig.objects.create(
                start_id=start_id,
                current_id=start_id - 1,  # will start FROM start_id on first run
                batch_size=batch_size or 50,
                is_active=True,
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f"Created new ScrapeConfig: start_id={start_id}, "
                    f"batch_size={config.batch_size}"
                )
            )

        # Override batch size for this run if requested
        if batch_size is not None and start_id is None:
            try:
                config = ScrapeConfig.objects.filter(is_active=True).latest(
                    "created_at"
                )

                config.batch_size = batch_size
                config.save(update_fields=["batch_size", "updated_at"])
                self.stdout.write(f"Batch size set to {batch_size} for this run.")
            except ScrapeConfig.DoesNotExist:
                raise CommandError(
                    "No active ScrapeConfig found. Use --start <ID> to create one."
                )

        # Verify an active config exists before starting
        try:
            ScrapeConfig.objects.filter(is_active=True).latest("created_at")
        except ScrapeConfig.DoesNotExist:
            raise CommandError(
                "No active ScrapeConfig found. "
                "Create one with: python manage.py scrape_jobs --start <LAST_JOB_ID>"
            )

        if continuous:
            self.stdout.write(
                self.style.WARNING("Continuous mode enabled. Press Ctrl+C to stop.")
            )

        batch_num = 0
        try:
            while True:
                batch_num += 1
                active = ScrapeConfig.objects.filter(is_active=True).latest(
                    "created_at"
                )

                self.stdout.write(
                    f"[Batch #{batch_num}] Scraping IDs {active.current_id + 1} → "
                    f"{active.current_id + active.batch_size} …"
                )

                stats = run_scraper()

                if "error" in stats:
                    raise CommandError(stats["error"])

                active.refresh_from_db()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[Batch #{batch_num}] Done. "
                        f'Checked: {stats["ids_checked"]} IDs | '
                        f'Found: {stats["jobs_found"]} jobs | '
                        f'New: {stats["jobs_new"]} | '
                        f'Alerts: {stats["alerts_sent"]}'
                    )
                )
                self.stdout.write(
                    f"Next batch will start from ID {active.current_id + 1}"
                )

                if not continuous:
                    break

                if pause > 0:
                    self.stdout.write(f"Waiting {pause}s before next batch…")
                    time.sleep(pause)

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nStopped by user. Progress saved."))
