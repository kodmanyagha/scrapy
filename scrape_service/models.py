from django.db import models


class Keyword(models.Model):
    """Keywords to watch for. If a job matches any keyword, a Telegram alert is sent."""

    word = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["word"]

    def __str__(self):
        return self.word


class ScrapeConfig(models.Model):
    """
    Defines where to start/continue iterating LinkedIn job IDs.
    There is normally only one row; the scraper always picks the latest one.
    """

    start_id = models.BigIntegerField(help_text="First LinkedIn job ID to check")
    current_id = models.BigIntegerField(
        help_text="Last ID that was checked (auto-updated)"
    )
    batch_size = models.IntegerField(
        default=50, help_text="How many IDs to probe per run"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Scrape Config"
        verbose_name_plural = "Scrape Configs"

    def __str__(self):
        return f"Config #{self.pk} | start={self.start_id} | current={self.current_id}"


class Job(models.Model):
    """A scraped LinkedIn job posting."""

    linkedin_id = models.BigIntegerField(unique=True, db_index=True)
    title = models.CharField(max_length=300)
    company = models.CharField(max_length=300)
    location = models.CharField(max_length=300, blank=True)
    description = models.TextField(blank=True)
    url = models.URLField(max_length=600)
    posted_date = models.CharField(max_length=100, blank=True)
    employment_type = models.CharField(max_length=100, blank=True)
    seniority_level = models.CharField(max_length=100, blank=True)

    matched_keywords = models.ManyToManyField(Keyword, blank=True, related_name="jobs")

    telegram_sent = models.BooleanField(default=False)
    telegram_sent_at = models.DateTimeField(null=True, blank=True)

    scraped_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-linkedin_id"]

    def __str__(self):
        return f"[{self.linkedin_id}] {self.title} at {self.company}"

    @property
    def has_keyword_match(self):
        return self.matched_keywords.exists()


class ScrapeLog(models.Model):
    """Audit log for each scrape run."""

    STATUS_CHOICES = [
        ("running", "Running"),
        ("success", "Success"),
        ("failed", "Failed"),
    ]

    config = models.ForeignKey(
        ScrapeConfig, on_delete=models.CASCADE, related_name="logs"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="running")
    id_from = models.BigIntegerField()
    id_to = models.BigIntegerField()
    ids_checked = models.IntegerField(default=0)
    jobs_found = models.IntegerField(default=0)  # IDs that returned a real job
    jobs_new = models.IntegerField(default=0)  # jobs saved for the first time
    alerts_sent = models.IntegerField(default=0)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return (
            f"[{self.status}] IDs {self.id_from}→{self.id_to} "
            f"| found={self.jobs_found} new={self.jobs_new} @ {self.started_at:%Y-%m-%d %H:%M}"
        )

    @property
    def duration_seconds(self):
        if self.finished_at:
            return (self.finished_at - self.started_at).seconds
        return None
