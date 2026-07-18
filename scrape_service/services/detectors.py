"""
scrape_service/services/detectors.py
─────────────────────────────────────
Country detection (parsed from the LinkedIn "location" string via pycountry)
and language detection (offline, via py3langid — no network call, so it can't
fail from API downtime/rate limits/DNS issues), plus filtering against
CountryRule / LanguageRule / PosterRule:
  - CountryRule and PosterRule are blacklists — everything is allowed except
    what's listed.
  - LanguageRule is a whitelist — only listed languages are allowed (if the
    list is empty, all languages are allowed).
If a value can't be detected at all, it is NOT filtered out (fail open).
"""

import logging

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
) -> tuple[bool, str]:
    """
    Check a detected alpha-2 country code, ISO 639-1 language code, and job
    poster name against CountryRule (blacklist) / LanguageRule (whitelist) /
    PosterRule (blacklist). Returns (allowed, reason); reason is empty when allowed.
    """
    if country_code is not None:
        for rule in CountryRule.objects.all():
            if _resolve_country_code(rule.country) == country_code:
                return False, f"country '{country_code}' is blacklisted"

    if language is not None:
        whitelist = list(LanguageRule.objects.values_list("language_code", flat=True))
        if whitelist and language.strip().lower() not in (w.strip().lower() for w in whitelist):
            return False, f"language '{language}' is not in the whitelist"

    allowed, reason = check_poster(poster_name)
    if not allowed:
        return False, reason

    return True, ""


def check_poster(poster_name: str | None) -> tuple[bool, str]:
    """Check a job poster's name against PosterRule (blacklist) as a case-insensitive substring match."""
    poster_name = (poster_name or "").strip()
    if not poster_name:
        return True, ""  # couldn't detect a poster — fail open

    for rule in PosterRule.objects.all():
        if rule.poster_name.strip().lower() in poster_name.lower():
            return False, f"poster '{poster_name}' is blacklisted"

    return True, ""
