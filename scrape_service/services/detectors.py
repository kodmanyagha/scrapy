"""
scrape_service/services/detectors.py
─────────────────────────────────────
Country detection (parsed from the LinkedIn "location" string via pycountry)
and language detection (offline, via py3langid — no network call, so it can't
fail from API downtime/rate limits/DNS issues), plus whitelist/blacklist
filtering against CountryRule / LanguageRule / PosterRule.

Filtering rule: blacklist always wins. If a whitelist exists for a field and
the detected value isn't in it, the job is rejected. If a value can't be
detected at all, it is NOT filtered out (fail open).
"""

import logging
from urllib.parse import urlparse

import py3langid as langid
import pycountry

from ..models import CountryRule, LanguageRule, PosterRule

logger = logging.getLogger(__name__)

# Common LinkedIn location spellings that pycountry's exact lookup() won't resolve
# on its own (either because ISO renamed the country, e.g. Turkey -> Türkiye, or
# because the abbreviation isn't registered as an alias).
_COUNTRY_ALIASES = {
    "turkey": "TR",
    "uk": "GB",
    "u.k.": "GB",
    "great britain": "GB",
    "south korea": "KR",
    "north korea": "KP",
    "russia": "RU",
    "vietnam": "VN",
    "usa": "US",
    "u.s.": "US",
    "u.s.a.": "US",
    "ivory coast": "CI",
    "laos": "LA",
    "syria": "SY",
    "iran": "IR",
    "bolivia": "BO",
    "venezuela": "VE",
    "tanzania": "TZ",
    "moldova": "MD",
    "brunei": "BN",
    "czech republic": "CZ",
}


def detect_country(location: str) -> str | None:
    """
    Resolve the ISO 3166-1 alpha-2 country code from a LinkedIn location string
    like 'Bengaluru, Karnataka, India'. Only the last comma-separated segment is
    considered, since that's where LinkedIn puts the country — matching earlier
    segments (city/state) against the country list produces false positives
    (e.g. a fuzzy match can mistake a city name for an unrelated country).
    """
    if not location:
        return None

    segments = [seg.strip() for seg in location.split(",") if seg.strip()]
    if not segments:
        return None

    return _resolve_country_code(segments[-1])


def _resolve_country_code(text: str) -> str | None:
    text = text.strip()
    if not text:
        return None

    alias = _COUNTRY_ALIASES.get(text.lower())
    if alias:
        return alias

    try:
        return pycountry.countries.lookup(text).alpha_2
    except LookupError:
        return None


def detect_language(text: str) -> str | None:
    """Detect the ISO 639-1 language code of `text` using py3langid (offline, no network call)."""
    text = (text or "").strip()
    if not text:
        return None

    try:
        code, score = langid.classify(text[:5000])
        logger.info("detected language=%s (score=%.2f)", code, score)
        return code
    except Exception as exc:
        logger.warning("Language detection failed: %s", exc)
        return None


def check_filters(
    country_code: str | None,
    language: str | None,
    poster_name: str | None = None,
    poster_profile_url: str | None = None,
) -> tuple[bool, str]:
    """
    Check a detected alpha-2 country code, ISO 639-1 language code, and job
    poster against CountryRule/LanguageRule/PosterRule.
    Returns (allowed, reason); reason is empty when allowed.
    """
    allowed, reason = _check_rules(
        country_code,
        list(CountryRule.objects.all()),
        "country",
        lambda r: _resolve_country_code(r.country),
    )
    if not allowed:
        return False, reason

    allowed, reason = _check_rules(
        language,
        list(LanguageRule.objects.all()),
        "language",
        lambda r: r.language_code.strip().lower(),
    )
    if not allowed:
        return False, reason

    allowed, reason = check_poster(poster_name, poster_profile_url)
    if not allowed:
        return False, reason

    return True, ""


def check_poster(poster_name: str | None, poster_profile_url: str | None) -> tuple[bool, str]:
    """
    Check a job poster's name/profile URL against PosterRule. A rule matches
    if either its name or its profile URL matches the job's (whichever fields
    are set on both sides).
    """
    poster_name = (poster_name or "").strip()
    poster_profile_url = (poster_profile_url or "").strip()

    if not poster_name and not poster_profile_url:
        return True, ""  # couldn't detect a poster — fail open

    rules = list(PosterRule.objects.all())
    blacklist = [r for r in rules if r.list_type == "blacklist"]
    whitelist = [r for r in rules if r.list_type == "whitelist"]

    def matches(rule: PosterRule) -> bool:
        if rule.poster_name and poster_name and rule.poster_name.strip().lower() in poster_name.lower():
            return True
        if (
            rule.poster_profile_url
            and poster_profile_url
            and _normalize_url(rule.poster_profile_url) == _normalize_url(poster_profile_url)
        ):
            return True
        return False

    label = poster_name or poster_profile_url

    for rule in blacklist:
        if matches(rule):
            return False, f"poster '{label}' is blacklisted"

    if whitelist and not any(matches(rule) for rule in whitelist):
        return False, f"poster '{label}' is not in the whitelist"

    return True, ""


def _normalize_url(url: str) -> str:
    """Compare LinkedIn profile URLs by path only, so uk.linkedin.com/in/x
    and www.linkedin.com/in/x (or http vs https) are treated as the same profile."""
    path = urlparse(url.strip()).path.rstrip("/").lower()
    return path or url.strip().lower()


def _check_rules(value, rules, field_name, get_rule_value) -> tuple[bool, str]:
    if value is None:
        return True, ""  # couldn't detect — fail open

    value_lower = value.strip().lower()
    blacklist = [r for r in rules if r.list_type == "blacklist"]
    whitelist = [r for r in rules if r.list_type == "whitelist"]

    for rule in blacklist:
        rule_value = get_rule_value(rule)
        if rule_value and rule_value.lower() == value_lower:
            return False, f"{field_name} '{value}' is blacklisted"

    if whitelist and not any(
        (rv := get_rule_value(rule)) and rv.lower() == value_lower for rule in whitelist
    ):
        return False, f"{field_name} '{value}' is not in the whitelist"

    return True, ""
