"""Deterministic news-source grading — done in preprocessing, NOT by the LLM.

The model must never guess a source's tier from an outlet name (it will happily
call a Yahoo-hosted blog "Tier-1 Reuters"). Tier is a stable editorial judgment,
so we compute it here and hand the model a fixed `source_type` to reuse.

Empirical note (verified 2026-08): Finnhub free-tier company-news only exposes the
**hosting platform** in its `source` field — in practice almost always "Yahoo" or
"SeekingAlpha" — plus a `finnhub.io` redirect URL. It does NOT reveal the original
wire (Reuters, Bloomberg). So `original_publisher` here is the *platform*, not the
true origin, and most items honestly grade as `secondary_media`. When the platform
is unrecognized we return `unknown` / low confidence rather than inventing a tier.
Resolving the true wire would need a paid news API or fetching+parsing each article.

Grading is intentionally conservative: a source is only lifted to `tier_1_media` or
`primary_official` when the name clearly matches; everything else stays secondary or
unknown. Extend the sets below as new outlets appear — this is a curated reference,
not an inference.
"""

# original reporting from a major wire / newspaper of record
_TIER_1 = {
    "reuters", "bloomberg", "wall street journal", "wsj", "financial times",
    "associated press", "the associated press", "cnbc", "barron", "dow jones",
    "new york times", "washington post", "the economist", "nikkei", "axios",
}

# aggregators / platforms / opinion syndicators — the bulk of free-tier news
_SECONDARY = {
    "yahoo", "seekingalpha", "seeking alpha", "marketwatch", "benzinga",
    "motley fool", "fool", "investing.com", "investing", "forbes", "zacks",
    "thestreet", "the street", "business insider", "insider monkey", "gurufocus",
    "simply wall", "24/7 wall", "247wall", "invezz", "tipranks", "streetinsider",
    "cointelegraph", "decrypt", "finbold", "kiplinger", "morningstar",
}

# first-party issuer / regulator / official statistical release
_PRIMARY_OFFICIAL = {
    "sec", "edgar", "businesswire", "business wire", "globe newswire",
    "globenewswire", "pr newswire", "prnewswire", "accesswire", "newsfile",
    "bls", "bea", "federal reserve", "treasury",
}

# social / user-generated / self-published
_SOCIAL = {"reddit", "twitter", "x.com", "stocktwits", "discord", "substack", "medium"}


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def classify_source(publisher: str, api_provider: str = "", url: str = "") -> dict:
    """Deterministically grade a news item. Returns the four structured fields:
    source_type, is_primary_source, source_confidence — computed, never guessed."""
    p = _norm(publisher)
    prov = _norm(api_provider)

    def hit(bag: set) -> bool:
        return any(k in p for k in bag)

    if prov in ("sec", "sec edgar", "edgar") or hit(_PRIMARY_OFFICIAL):
        return {"source_type": "primary_official", "is_primary_source": True, "source_confidence": "high"}
    if hit(_TIER_1):
        return {"source_type": "tier_1_media", "is_primary_source": False, "source_confidence": "high"}
    if hit(_SECONDARY):
        return {"source_type": "secondary_media", "is_primary_source": False, "source_confidence": "high"}
    if hit(_SOCIAL):
        return {"source_type": "social", "is_primary_source": False, "source_confidence": "low"}
    return {"source_type": "unknown", "is_primary_source": False, "source_confidence": "low"}


# source_type → the brief's Label.source enum the LLM must reuse (never re-grade).
LABEL_FOR = {
    "primary_official": "Official",
    "tier_1_media":     "Tier-1",
    "secondary_media":  "Secondary",
    "social":           "Low-confidence",
    "unknown":          "Low-confidence",
}
