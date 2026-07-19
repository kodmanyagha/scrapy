from django.db import models


class Keyword(models.Model):
    """Keywords to watch for. If a job matches any keyword, a Telegram alert is sent."""

    word = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["word"]

    def __str__(self):
        return self.word


class TitleKeyword(models.Model):
    """
    Keywords to watch for in the job title only (not company/description). If a
    job title contains any of these as a whole word, a Telegram alert is sent —
    same trigger as Keyword, just scoped to the title.
    """

    word = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["word"]
        verbose_name = "Title Keyword"
        verbose_name_plural = "Title Keywords"

    def __str__(self):
        return self.word


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

    country = models.CharField(
        max_length=10,
        blank=True,
        help_text="ISO 3166-1 alpha-2 country code detected from the job location",
    )
    language = models.CharField(
        max_length=10,
        blank=True,
        help_text="ISO 639-1 code detected from the job description via Hugging Face",
    )

    poster_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Name of the job poster, or the company if no individual recruiter is shown",
    )

    matched_keywords = models.ManyToManyField(Keyword, blank=True, related_name="jobs")
    matched_title_keywords = models.ManyToManyField(
        TitleKeyword, blank=True, related_name="jobs"
    )

    is_filtered = models.BooleanField(
        default=False,
        help_text="True if this job was excluded by a country/language/poster whitelist or blacklist rule",
    )
    filter_reason = models.CharField(max_length=200, blank=True)

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

    @property
    def has_title_keyword_match(self):
        return self.matched_title_keywords.exists()


class CountryRule(models.Model):
    """A blacklisted country — jobs detected in this country are excluded. All other countries are allowed."""

    country = models.CharField(
        max_length=100,
        unique=True,
        help_text='Country name as detected, e.g. "Turkey", "United States", "India"',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["country"]
        verbose_name = "Country Rule (blacklist)"
        verbose_name_plural = "Country Rules (blacklist)"

    def __str__(self):
        return f"blacklist: {self.country}"


class LanguageRule(models.Model):
    """A whitelisted language — only jobs detected in one of these languages are allowed."""

    language_code = models.CharField(
        max_length=10, unique=True, help_text='ISO 639-1 code, e.g. "en", "tr"'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["language_code"]
        verbose_name = "Language Rule (whitelist)"
        verbose_name_plural = "Language Rules (whitelist)"

    def __str__(self):
        return f"whitelist: {self.language_code}"


class PosterRule(models.Model):
    """A blacklisted job poster — matches as a case-insensitive substring of the poster name."""

    poster_name = models.CharField(
        max_length=200,
        unique=True,
        help_text='Substring to match against the poster name, case-insensitive (e.g. "turing" matches "Turing Recruiting Team")',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["poster_name"]
        verbose_name = "Poster Rule (blacklist)"
        verbose_name_plural = "Poster Rules (blacklist)"

    def __str__(self):
        return f"blacklist: {self.poster_name}"


class ScrapeLog(models.Model):
    """Audit log for each scrape run."""

    STATUS_CHOICES = [
        ("running", "Running"),
        ("success", "Success"),
        ("failed", "Failed"),
    ]

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
