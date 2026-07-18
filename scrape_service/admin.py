from django.contrib import admin

from .models import (
    CountryRule,
    Job,
    Keyword,
    LanguageRule,
    PosterRule,
    ScrapeConfig,
    ScrapeLog,
)


@admin.register(Keyword)
class KeywordAdmin(admin.ModelAdmin):
    list_display = ("id", "word", "created_at")
    search_fields = ("word",)


@admin.register(CountryRule)
class CountryRuleAdmin(admin.ModelAdmin):
    list_display = ("id", "country", "list_type", "created_at")
    list_filter = ("list_type",)
    search_fields = ("country",)


@admin.register(LanguageRule)
class LanguageRuleAdmin(admin.ModelAdmin):
    list_display = ("id", "language_code", "list_type", "created_at")
    list_filter = ("list_type",)
    search_fields = ("language_code",)


@admin.register(PosterRule)
class PosterRuleAdmin(admin.ModelAdmin):
    list_display = ("id", "poster_name", "poster_profile_url", "list_type", "created_at")
    list_filter = ("list_type",)
    search_fields = ("poster_name", "poster_profile_url")


@admin.register(ScrapeConfig)
class ScrapeConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "start_id", "current_id", "batch_size", "is_active", "updated_at")
    list_filter = ("is_active",)


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = (
        "id", "linkedin_id", "title", "company", "location", "country", "language",
        "poster_name", "has_keyword_match", "is_filtered", "telegram_sent", "scraped_at",
    )
    list_filter = ("telegram_sent", "is_filtered", "country", "language", "matched_keywords")
    search_fields = ("title", "company", "linkedin_id", "poster_name")
    readonly_fields = [f.name for f in Job._meta.fields]
    actions = ["blacklist_poster"]

    @admin.action(description="Blacklist the poster of selected jobs")
    def blacklist_poster(self, request, queryset):
        created = 0
        for job in queryset:
            if not job.poster_name and not job.poster_profile_url:
                continue
            _, was_created = PosterRule.objects.get_or_create(
                poster_name=job.poster_name,
                poster_profile_url=job.poster_profile_url,
                list_type="blacklist",
            )
            created += int(was_created)
        self.message_user(request, f"Blacklisted {created} poster(s).")


@admin.register(ScrapeLog)
class ScrapeLogAdmin(admin.ModelAdmin):
    list_display = ("id", "config", "status", "id_from", "id_to", "ids_checked", "jobs_found", "jobs_new", "alerts_sent", "started_at")
    list_filter = ("status",)
