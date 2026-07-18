"""
linkedin_scraper/scraper.py
───────────────────────────
ID-iteration scraping engine.

Strategy
────────
LinkedIn job detail pages are publicly accessible at:
    https://www.linkedin.com/jobs/view/<JOB_ID>/

Job IDs are sequential integers. We start from a user-specified ID and probe
each subsequent ID one by one:
  - HTTP 200  → job is live → parse and save
  - HTTP 404  → job doesn't exist or was removed → skip
  - HTTP 429  → rate-limited → back off and retry
  - Other     → log and skip

The last checked ID is persisted in ScrapeConfig.current_id so runs resume
correctly even after interruption.
"""

import logging
import time
import re
import random

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.utils import timezone as django_tz

from ..models import Job, Keyword, ScrapeConfig, ScrapeLog
from ..telegram import send_telegram_message, build_job_message
from .detectors import check_filters, detect_country, detect_language

logger = logging.getLogger(__name__)

JOB_URL = "https://www.linkedin.com/jobs/view/{}/"

# Rotate through several real browser User-Agent strings to avoid fingerprinting
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

BASE_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.google.com/",  # pretend we came from Google, not LinkedIn itself
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "cross-site",
    "Upgrade-Insecure-Requests": "1",
}


def _get_headers() -> dict:
    """Return headers with a randomly chosen User-Agent."""
    return {**BASE_HEADERS, "User-Agent": random.choice(USER_AGENTS)}


# How many times to retry a 429/999 before giving up on that ID
MAX_RATE_LIMIT_RETRIES = 3
RATE_LIMIT_BACKOFF = 60  # seconds to wait after a 429 or 999


# ─── Public API ───────────────────────────────────────────────────────────────


def run_scraper():
    """
    Pick the active ScrapeConfig, iterate IDs for one batch, save results.
    Returns a stats dict.
    """
    try:
        config = ScrapeConfig.objects.filter(is_active=True).latest("created_at")
    except ScrapeConfig.DoesNotExist:
        logger.warning("No active ScrapeConfig found. Create one in the admin panel.")
        return {"error": "No active config"}

    id_from = config.current_id + 1
    id_to = id_from + config.batch_size - 1

    log = ScrapeLog.objects.create(
        config=config,
        status="running",
        id_from=id_from,
        id_to=id_to,
    )

    keywords = list(Keyword.objects.values_list("word", flat=True))
    stats = {"ids_checked": 0, "jobs_found": 0, "jobs_new": 0, "alerts_sent": 0}

    logger.info("batch start: checking IDs %s..%s (log #%s)", id_from, id_to, log.pk)

    try:
        for job_id in range(id_from, id_to + 1):
            logger.info("probing job_id=%s", job_id)
            result = _probe_job_id(job_id, keywords)
            stats["ids_checked"] += 1

            if result["exists"]:
                stats["jobs_found"] += 1
                if result["is_new"]:
                    stats["jobs_new"] += 1
                    logger.info("job_id=%s is NEW and saved", job_id)
                else:
                    logger.info("job_id=%s already in DB, skipped insert", job_id)
                if result["alert_sent"]:
                    stats["alerts_sent"] += 1
                    logger.info("job_id=%s Telegram alert sent", job_id)
            else:
                logger.info("job_id=%s does not exist / no result", job_id)

            # Always advance current_id so we don't re-check on next run
            config.current_id = job_id
            config.save(update_fields=["current_id", "updated_at"])

            # Base delay + random jitter to look less like a bot
            base_delay = getattr(settings, "SCRAPER_REQUEST_DELAY", 3)
            delay = base_delay + random.uniform(0.5, 2.5)
            logger.info("sleeping %.2fs before next request", delay)
            time.sleep(delay)

        log.status = "success"
        logger.info("batch finished successfully: %s", stats)

    except BlockedByLinkedIn as exc:
        logger.error("Batch stopped early — blocked by LinkedIn: %s", exc)
        log.status = "failed"
        log.error_message = str(exc)

    except Exception as exc:
        logger.exception("Scraper run failed at job_id=%s", job_id)
        log.status = "failed"
        log.error_message = str(exc)

    finally:
        log.ids_checked = stats["ids_checked"]
        log.jobs_found = stats["jobs_found"]
        log.jobs_new = stats["jobs_new"]
        log.alerts_sent = stats["alerts_sent"]
        log.finished_at = django_tz.now()
        log.save()

    return stats


# ─── Internal helpers ─────────────────────────────────────────────────────────


def _probe_job_id(job_id: int, keywords: list[str]) -> dict:
    """
    Fetch a single LinkedIn job ID.
    Returns dict: {exists, is_new, alert_sent}
    """
    url = JOB_URL.format(job_id)
    html = _fetch_with_retry(url)

    if html is None:
        # 404 or persistent error — job doesn't exist
        logger.debug("Job ID %s: not found / skipped", job_id)
        return {"exists": False, "is_new": False, "alert_sent": False}

    data = _parse_job_page(html, job_id, url)
    if not data:
        logger.debug("Job ID %s: page fetched but could not parse", job_id)
        return {"exists": False, "is_new": False, "alert_sent": False}

    logger.info('Job ID %s: "%s" at %s', job_id, data["title"], data["company"])

    # Already in DB? (idempotent — safe to call multiple times)
    if Job.objects.filter(linkedin_id=job_id).exists():
        return {"exists": True, "is_new": False, "alert_sent": False}

    country = detect_country(data["location"])
    language = detect_language(data["description"] or data["title"])
    poster_name = data["poster_name"]
    poster_profile_url = data["poster_profile_url"]
    logger.info(
        "job_id=%s detected country=%s language=%s poster=%s",
        job_id, country, language, poster_name or poster_profile_url or None,
    )

    allowed, filter_reason = check_filters(country, language, poster_name, poster_profile_url)

    logger.info(
        'inserting Job row for linkedin_id=%s: "%s" at %s',
        job_id, data["title"], data["company"],
    )
    job = Job.objects.create(
        linkedin_id=job_id,
        title=data["title"],
        company=data["company"],
        location=data["location"],
        url=url,
        posted_date=data["posted_date"],
        description=data["description"],
        employment_type=data["employment_type"],
        seniority_level=data["seniority_level"],
        country=country or "",
        language=language or "",
        poster_name=poster_name,
        poster_profile_url=poster_profile_url,
        is_filtered=not allowed,
        filter_reason=filter_reason,
    )
    logger.info("Job row inserted (pk=%s)", job.pk)

    if not allowed:
        logger.info("job_id=%s filtered out: %s", job_id, filter_reason)
        return {"exists": True, "is_new": True, "alert_sent": False}

    # Check keywords
    full_text = f"{data['title']} {data['company']} {data['description']}"
    matched = _check_keywords(full_text, keywords)

    alert_sent = False
    if matched:
        logger.info("job_id=%s matched keywords: %s", job_id, matched)
        kw_objects = Keyword.objects.filter(word__in=matched)
        job.matched_keywords.set(kw_objects)
        message = build_job_message(job, matched)
        logger.info("sending Telegram API request for job_id=%s", job_id)
        if send_telegram_message(message):
            job.telegram_sent = True
            job.telegram_sent_at = django_tz.now()
            alert_sent = True
            logger.info("Telegram API request succeeded for job_id=%s", job_id)
        else:
            logger.warning("Telegram API request FAILED for job_id=%s", job_id)
        job.save()
    else:
        job.save()

    return {"exists": True, "is_new": True, "alert_sent": alert_sent}


def _fetch_with_retry(url: str) -> str | None:
    """
    GET url. Returns HTML string on 200, None on 404/gone.
    Retries on 429 (rate limit) and 999 (LinkedIn bot detection).
    Uses a random User-Agent and jitter delay on each attempt.
    """
    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            # Random jitter: 1–4 extra seconds on top of the base delay
            if attempt > 0:
                jitter = random.uniform(1, 4)
                time.sleep(RATE_LIMIT_BACKOFF + jitter)

            resp = requests.get(
                url,
                headers=_get_headers(),
                timeout=20,
                allow_redirects=True,
            )

            if resp.status_code == 200:
                # LinkedIn sometimes serves a sign-in wall instead of 404
                if _is_auth_wall(resp.text):
                    logger.debug("Auth wall hit for %s", url)
                    return None
                return resp.text

            if resp.status_code in (404, 410):
                return None  # job doesn't exist — normal, skip silently

            if resp.status_code in (429, 999):
                # 429 = standard rate limit
                # 999 = LinkedIn bot detection
                if attempt < MAX_RATE_LIMIT_RETRIES:
                    wait = RATE_LIMIT_BACKOFF * (
                        attempt + 1
                    )  # escalating: 60s, 120s, 180s
                    logger.warning(
                        "Blocked (HTTP %s) on attempt %d. Waiting %ds before retry…",
                        resp.status_code,
                        attempt + 1,
                        wait,
                    )
                    time.sleep(wait)
                    continue
                else:
                    logger.error(
                        "Still blocked after %d retries. Stopping this batch. "
                        "Try increasing SCRAPER_REQUEST_DELAY in settings.py.",
                        MAX_RATE_LIMIT_RETRIES,
                    )
                    raise BlockedByLinkedIn(
                        f"LinkedIn returned {resp.status_code} after {MAX_RATE_LIMIT_RETRIES} retries. "
                        f"Increase SCRAPER_REQUEST_DELAY or wait before running again."
                    )

            logger.warning("Unexpected status %s for %s", resp.status_code, url)
            return None

        except BlockedByLinkedIn:
            raise  # propagate to stop the whole batch

        except requests.RequestException as exc:
            logger.error("Request error for %s: %s", url, exc)
            return None

    return None


class BlockedByLinkedIn(Exception):
    """Raised when LinkedIn persistently blocks requests (HTTP 999 / 429)."""

    pass


def _is_auth_wall(html: str) -> bool:
    """Return True if LinkedIn is showing a login/sign-in page instead of job content."""
    markers = [
        "urn:li:page:d_jobs_guest_login",
        "authwall",
        "join-form",
        "login-email",
    ]
    lower = html.lower()
    return any(m in lower for m in markers)


def _parse_job_page(html: str, job_id: int, url: str) -> dict | None:
    """Parse a LinkedIn job detail page and return structured data."""
    soup = BeautifulSoup(html, "html.parser")

    # ── Title ──────────────────────────────────────────────────────────────────
    title = ""
    for sel in [
        "h1.top-card-layout__title",
        'h1[class*="title"]',
        "h1",
        "title",
    ]:
        el = soup.select_one(sel)
        if el:
            title = el.get_text(strip=True)
            # Strip " | LinkedIn" suffix from <title>
            title = re.sub(r"\s*\|\s*LinkedIn.*$", "", title, flags=re.IGNORECASE)
            if title:
                break

    if not title or title.lower() in ("linkedin", ""):
        return None  # probably not a real job page

    # ── Company ────────────────────────────────────────────────────────────────
    company = ""
    for sel in [
        "a.topcard__org-name-link",
        'a[class*="company"]',
        "span.topcard__flavor a",
        ".jobs-unified-top-card__company-name a",
        ".jobs-unified-top-card__company-name",
    ]:
        el = soup.select_one(sel)
        if el:
            company = el.get_text(strip=True)
            break

    # ── Location ───────────────────────────────────────────────────────────────
    location = ""
    for sel in [
        "span.topcard__flavor--bullet",
        ".jobs-unified-top-card__bullet",
        'span[class*="location"]',
    ]:
        el = soup.select_one(sel)
        if el:
            location = el.get_text(strip=True)
            break

    # ── Posted date ────────────────────────────────────────────────────────────
    posted_date = ""
    time_el = soup.select_one('time, span.posted-time-ago__text, [class*="posted"]')
    if time_el:
        posted_date = time_el.get("datetime") or time_el.get_text(strip=True)

    # ── Description ────────────────────────────────────────────────────────────
    description = ""
    for sel in [
        "div.description__text",
        'div[class*="description"] div[class*="content"]',
        "section.description",
        "div#job-details",
    ]:
        el = soup.select_one(sel)
        if el:
            description = el.get_text(separator="\n", strip=True)
            break

    # ── Job criteria (employment type, seniority) ──────────────────────────────
    employment_type = ""
    seniority_level = ""
    for item in soup.select("li.description__job-criteria-item"):
        label_el = item.select_one("h3")
        value_el = item.select_one("span")
        if label_el and value_el:
            lbl = label_el.get_text(strip=True).lower()
            val = value_el.get_text(strip=True)
            if "employment" in lbl:
                employment_type = val
            elif "seniority" in lbl:
                seniority_level = val

    # ── Job poster (only present when LinkedIn renders a "message the job
    #    poster" card — many listings don't have one, so this is best-effort) ──
    poster_name = ""
    poster_profile_url = ""
    recruiter_section = soup.select_one("div.message-the-recruiter")
    if recruiter_section:
        name_el = recruiter_section.select_one("h3.base-main-card__title")
        if name_el:
            poster_name = name_el.get_text(strip=True)

        link_el = recruiter_section.select_one("a.base-card__full-link")
        if link_el:
            href = str(link_el.get("href") or "")
            poster_profile_url = href.split("?")[0] if href else ""

    return {
        "title": title,
        "company": company or "Unknown Company",
        "location": location,
        "posted_date": posted_date,
        "description": description,
        "employment_type": employment_type,
        "seniority_level": seniority_level,
        "poster_name": poster_name,
        "poster_profile_url": poster_profile_url,
    }


def _check_keywords(text: str, keywords: list[str]) -> list[str]:
    """Return which keywords appear in text (case-insensitive)."""
    text_lower = text.lower()
    return [kw for kw in keywords if kw.lower() in text_lower]
