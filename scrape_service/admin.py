from django.contrib import admin

from .models import Job, Keyword, ScrapeConfig, ScrapeLog


@admin.register(Keyword)
class KeywordAdmin(admin.ModelAdmin):
    list_display = ("word", "created_at")
    search_fields = ("word",)


@admin.register(ScrapeConfig)
class ScrapeConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "start_id", "current_id", "batch_size", "is_active", "updated_at")
    list_filter = ("is_active",)


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("linkedin_id", "title", "company", "location", "has_keyword_match", "telegram_sent", "scraped_at")
    list_filter = ("telegram_sent", "matched_keywords")
    search_fields = ("title", "company", "linkedin_id")
    readonly_fields = [f.name for f in Job._meta.fields]


@admin.register(ScrapeLog)
class ScrapeLogAdmin(admin.ModelAdmin):
    list_display = ("id", "config", "status", "id_from", "id_to", "ids_checked", "jobs_found", "jobs_new", "alerts_sent", "started_at")
    list_filter = ("status",)
