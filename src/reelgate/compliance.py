"""Regulatory, copyright, and youth-protection compliance evaluator for video publishing."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
from typing import Any


DEFAULT_BLOCKED_TERMS: list[str] = [
    "gun",
    "weapon",
    "shoot",
    "kill",
    "murder",
    "suicide",
    "self-harm",
    "terror",
    "bomb",
]

DEFAULT_KIDS_BLOCKED_TERMS: list[str] = [
    "gun",
    "weapon",
    "blood",
    "horror",
    "scary",
    "monster attack",
    "gambling",
    "casino",
    "alcohol",
    "beer",
    "vodka",
    "cigarette",
    "vape",
    "kauf jetzt",
    "jetzt kaufen",
    "buy now",
    "order now",
    "rabattcode",
    "discount code",
    "link in bio",
]

DEFAULT_COMMERCIAL_TRIGGERS: list[str] = [
    "affiliate",
    "rabattcode",
    "gutscheincode",
    "promo code",
    "discount code",
    "utm_source=",
    "ref=",
    "amzn.to/",
    "bit.ly/",
]

DEFAULT_DISCLOSURE_MARKERS: list[str] = [
    "anzeige",
    "werbung",
    "#anzeige",
    "#werbung",
    "#ad",
    "#sponsored",
    "sponsored",
]

URL_PATTERN = re.compile(r"https?://[^\s)\]>\"']+", re.IGNORECASE)
HASHTAG_PATTERN = re.compile(r"(?:^|\s)#[a-zA-Z0-9_äöüÄÖÜß]+")


@dataclass(frozen=True)
class CompliancePolicy:
    """Rules for legal, youth-protection, copyright, and disclosure verification."""

    made_for_kids: bool = False
    min_duration_sec: float = 10.0
    max_duration_sec: float = 60.0
    max_hashtags: int = 15
    blocked_terms: list[str] = field(default_factory=lambda: list(DEFAULT_BLOCKED_TERMS))
    kids_blocked_terms: list[str] = field(default_factory=lambda: list(DEFAULT_KIDS_BLOCKED_TERMS))
    forbid_links_for_kids: bool = True
    commercial_triggers: list[str] = field(default_factory=lambda: list(DEFAULT_COMMERCIAL_TRIGGERS))
    disclosure_markers: list[str] = field(default_factory=lambda: list(DEFAULT_DISCLOSURE_MARKERS))
    require_synthetic_disclosure: bool = False
    min_remix_commentary_words: int = 15
    min_remix_source_clips: int = 3
    blocked_domains: list[str] = field(default_factory=list)
    require_imprint_reference: bool = False
    imprint_markers: list[str] = field(
        default_factory=lambda: ["impressum", "ddg", "kontakt:", "inhaber"]
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CompliancePolicy:
        return cls(
            made_for_kids=bool(raw.get("made_for_kids", False)),
            min_duration_sec=float(raw.get("min_duration_sec", 10.0)),
            max_duration_sec=float(raw.get("max_duration_sec", 60.0)),
            max_hashtags=int(raw.get("max_hashtags", 15)),
            blocked_terms=list(raw.get("blocked_terms", DEFAULT_BLOCKED_TERMS)),
            kids_blocked_terms=list(raw.get("kids_blocked_terms", DEFAULT_KIDS_BLOCKED_TERMS)),
            forbid_links_for_kids=bool(raw.get("forbid_links_for_kids", True)),
            commercial_triggers=list(raw.get("commercial_triggers", DEFAULT_COMMERCIAL_TRIGGERS)),
            disclosure_markers=list(raw.get("disclosure_markers", DEFAULT_DISCLOSURE_MARKERS)),
            require_synthetic_disclosure=bool(raw.get("require_synthetic_disclosure", False)),
            min_remix_commentary_words=int(raw.get("min_remix_commentary_words", 15)),
            min_remix_source_clips=int(raw.get("min_remix_source_clips", 3)),
            blocked_domains=list(raw.get("blocked_domains", [])),
            require_imprint_reference=bool(raw.get("require_imprint_reference", False)),
            imprint_markers=list(
                raw.get("imprint_markers", ["impressum", "ddg", "kontakt:", "inhaber"])
            ),
        )


@dataclass(frozen=True)
class SubmissionMetadata:
    """Metadata and editorial context for a candidate video publication."""

    title: str
    caption: str = ""
    script_text: str = ""
    duration_sec: float | None = None
    made_for_kids: bool | None = None
    is_commercial: bool = False
    paid_promotion_flag: bool = False
    is_synthetic_media: bool = False
    synthetic_disclosure_flag: bool = False
    is_remix: bool = False
    original_audio_replaced: bool = True
    source_clip_count: int = 0
    recent_titles: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SubmissionMetadata:
        return cls(
            title=str(raw.get("title", "")),
            caption=str(raw.get("caption", "")),
            script_text=str(raw.get("script_text", "")),
            duration_sec=float(raw["duration_sec"]) if raw.get("duration_sec") is not None else None,
            made_for_kids=bool(raw["made_for_kids"]) if raw.get("made_for_kids") is not None else None,
            is_commercial=bool(raw.get("is_commercial", False)),
            paid_promotion_flag=bool(raw.get("paid_promotion_flag", False)),
            is_synthetic_media=bool(raw.get("is_synthetic_media", False)),
            synthetic_disclosure_flag=bool(raw.get("synthetic_disclosure_flag", False)),
            is_remix=bool(raw.get("is_remix", False)),
            original_audio_replaced=bool(raw.get("original_audio_replaced", True)),
            source_clip_count=int(raw.get("source_clip_count", 0)),
            recent_titles=list(raw.get("recent_titles", [])),
        )


@dataclass(frozen=True)
class ComplianceReport:
    """Result of evaluating a SubmissionMetadata instance against a CompliancePolicy."""

    passed: bool
    effective_made_for_kids: bool
    hashtag_count: int
    external_urls: list[str]
    matched_blocked_terms: list[str]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_title(text: str) -> str:
    collapsed = re.sub(r"[^a-z0-9äöüß]+", " ", text.lower()).strip()
    return re.sub(r"\s+", " ", collapsed)


def _find_matching_terms(corpus_lower: str, terms: list[str]) -> list[str]:
    matched: list[str] = []
    for raw_term in terms:
        term = raw_term.strip().lower()
        if not term:
            continue
        if re.search(r"^[a-z0-9äöüß_-]+$", term):
            pattern = rf"\b{re.escape(term)}\b"
            if re.search(pattern, corpus_lower):
                matched.append(raw_term)
        elif term in corpus_lower:
            matched.append(raw_term)
    return matched


def evaluate_compliance(
    submission: SubmissionMetadata,
    policy: CompliancePolicy | None = None,
) -> ComplianceReport:
    """Evaluate editorial, youth-protection, disclosure, and copyright rules."""
    active = policy or CompliancePolicy()
    reasons: list[str] = []

    title_clean = submission.title.strip()
    if not title_clean:
        reasons.append("missing_title: title must not be empty")

    effective_kids = (
        submission.made_for_kids
        if submission.made_for_kids is not None
        else active.made_for_kids
    )

    combined_text = f"{submission.title}\n{submission.caption}\n{submission.script_text}"
    corpus_lower = combined_text.lower()

    if submission.duration_sec is not None:
        if not (active.min_duration_sec <= submission.duration_sec <= active.max_duration_sec):
            reasons.append(
                f"duration_out_of_bounds: {submission.duration_sec:.1f}s outside "
                f"[{active.min_duration_sec:.1f}s, {active.max_duration_sec:.1f}s]"
            )

    norm_title = _normalize_title(title_clean)
    if norm_title:
        recent_norm = {_normalize_title(item) for item in submission.recent_titles if item.strip()}
        if norm_title in recent_norm:
            reasons.append(f"duplicate_title: '{title_clean}' was already used recently")

    matched_terms = _find_matching_terms(corpus_lower, active.blocked_terms)
    if effective_kids:
        kids_matches = _find_matching_terms(corpus_lower, active.kids_blocked_terms)
        for item in kids_matches:
            if item not in matched_terms:
                matched_terms.append(item)

    if matched_terms:
        reasons.append(
            f"blocked_terms_found: {', '.join(sorted(set(matched_terms)))}"
        )

    urls = URL_PATTERN.findall(combined_text)
    if effective_kids and active.forbid_links_for_kids and urls:
        reasons.append(
            "kids_external_links_forbidden: external URLs are not permitted in made_for_kids metadata"
        )

    if effective_kids and (submission.is_commercial or submission.paid_promotion_flag):
        reasons.append(
            "kids_commercial_promotion_forbidden: commercial promotions are not permitted in made_for_kids content"
        )

    commercial_hits = [
        trig for trig in active.commercial_triggers if trig.lower() in corpus_lower
    ]
    needs_commercial_disclosure = submission.is_commercial or bool(commercial_hits)
    if needs_commercial_disclosure and not effective_kids:
        caption_lower = submission.caption.lower()
        title_lower = submission.title.lower()
        has_marker = any(
            m.lower() in caption_lower or m.lower() in title_lower
            for m in active.disclosure_markers
        )
        if not (submission.paid_promotion_flag or has_marker):
            reasons.append(
                "missing_commercial_disclosure: commercial intent or affiliate trigger detected "
                "without explicit advertising disclosure (Anzeige/Werbung/#ad or paid_promotion_flag)"
            )

    if (submission.is_synthetic_media or active.require_synthetic_disclosure) and not (
        submission.synthetic_disclosure_flag
        or "ki-generiert" in corpus_lower
        or "ai-generated" in corpus_lower
        or "synthetisch" in corpus_lower
    ):
        if submission.is_synthetic_media and active.require_synthetic_disclosure:
            reasons.append(
                "missing_synthetic_disclosure: synthetic media requires synthetic_disclosure_flag "
                "or explicit text disclosure"
            )

    if submission.is_remix:
        if not submission.original_audio_replaced:
            reasons.append(
                "remix_unmodified_audio: remix requires replacing or transforming original source audio"
            )
        script_words = [w for w in re.split(r"\s+", submission.script_text.strip()) if w]
        if len(script_words) < active.min_remix_commentary_words:
            reasons.append(
                f"remix_insufficient_commentary: {len(script_words)} words < minimum "
                f"{active.min_remix_commentary_words} words for transformative commentary"
            )
        if submission.source_clip_count < active.min_remix_source_clips:
            reasons.append(
                f"remix_insufficient_clips: {submission.source_clip_count} source clips < minimum "
                f"{active.min_remix_source_clips} clips"
            )

    for url in urls:
        url_low = url.lower()
        for dom in active.blocked_domains:
            dom_clean = dom.strip().lower()
            if dom_clean and dom_clean in url_low:
                reasons.append(f"blocked_domain_found: '{dom_clean}' in '{url}'")

    if active.require_imprint_reference:
        has_imprint = any(m.lower() in corpus_lower for m in active.imprint_markers)
        if not has_imprint:
            reasons.append(
                "missing_imprint_reference: required provider identification (§ 5 DDG) not found"
            )

    hashtags = HASHTAG_PATTERN.findall(f" {submission.title} {submission.caption}")
    if len(hashtags) > active.max_hashtags:
        reasons.append(
            f"excessive_hashtags: {len(hashtags)} hashtags exceed maximum of {active.max_hashtags}"
        )

    return ComplianceReport(
        passed=len(reasons) == 0,
        effective_made_for_kids=effective_kids,
        hashtag_count=len(hashtags),
        external_urls=urls,
        matched_blocked_terms=matched_terms,
        reasons=reasons,
    )


def load_compliance_policy(path: str | Path) -> CompliancePolicy:
    """Load a CompliancePolicy from a JSON file."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return CompliancePolicy.from_dict(raw)


def load_submission_metadata(path: str | Path) -> SubmissionMetadata:
    """Load SubmissionMetadata from a JSON file."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return SubmissionMetadata.from_dict(raw)
