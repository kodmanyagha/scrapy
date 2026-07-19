from django.contrib import admin

from .models import (
    CountryRule,
    Job,
    Keyword,
    LanguageRule,
    PosterRule,
    ScrapeLog,
    TitleKeyword,
)


@admin.register(Keyword)
class KeywordAdmin(admin.ModelAdmin):
    list_display = ("id", "word", "created_at")
    search_fields = ("word",)


@admin.register(TitleKeyword)
class TitleKeywordAdmin(admin.ModelAdmin):
    list_display = ("id", "word", "created_at")
    search_fields = ("word",)


@admin.register(CountryRule)
class CountryRuleAdmin(admin.ModelAdmin):
    list_display = ("id", "country", "created_at")
    search_fields = ("country",)


@admin.register(LanguageRule)
class LanguageRuleAdmin(admin.ModelAdmin):
    list_display = ("id", "language_code", "created_at")
    search_fields = ("language_code",)


@admin.register(PosterRule)
class PosterRuleAdmin(admin.ModelAdmin):
    list_display = ("id", "poster_name", "created_at")
    search_fields = ("poster_name",)


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = (
        "id", "linkedin_id", "title", "company", "location", "country", "language",
        "poster_name", "has_keyword_match", "has_title_keyword_match", "is_filtered",
        "telegram_sent", "scraped_at",
    )
    list_filter = (
        "telegram_sent", "is_filtered", "country", "language",
        "matched_keywords", "matched_title_keywords",
    )
    search_fields = ("title", "company", "linkedin_id", "poster_name")
    readonly_fields = [f.name for f in Job._meta.fields]
    actions = ["blacklist_poster"]

    @admin.action(description="Blacklist the poster of selected jobs")
    def blacklist_poster(self, request, queryset):
        created = 0
        for job in queryset:
            if not job.poster_name:
                continue
            _, was_created = PosterRule.objects.get_or_create(poster_name=job.poster_name)
            created += int(was_created)
        self.message_user(request, f"Blacklisted {created} poster(s).")


@admin.register(ScrapeLog)
class ScrapeLogAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "id_from", "id_to", "ids_checked", "jobs_found", "jobs_new", "alerts_sent", "started_at")
    list_filter = ("status",)
