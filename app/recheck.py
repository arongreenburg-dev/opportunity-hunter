"""Source recheck engine: extract evidence, compare it, and judge decision impact.

This module is deliberately deterministic and dependency-free so the demo
fixtures and the live official-source path run through exactly the same
extraction, comparison and decision logic.

Pipeline for one check:

    page text -> extract_evidence() -> compare_evidence(baseline, current)
              -> assess_impact(decision, reason, comparison) -> verdict
"""

from __future__ import annotations

import difflib
import hashlib
import re
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser

# ---------------------------------------------------------------------------
# Fields we track, in priority order. Labels are user-facing.
# ---------------------------------------------------------------------------

FIELDS: list[tuple[str, str]] = [
    ("deadline", "Deadline"),
    ("eligibility", "Eligibility"),
    ("participation", "Participation format"),
    ("submission", "Submission requirements"),
]
FIELD_LABELS = dict(FIELDS)

# Heading/label text that introduces a field section on a structured page.
_LABEL_PATTERNS = {
    "deadline": r"(key |important |upcoming )?(due )?dates?|(upcoming )?deadlines?( dates?)?|timeline|when",
    "eligibility": r"eligibility|who can (apply|enter|participate)|who is eligible",
    "participation": r"(participation )?format|location|venue|where|attendance|travel",
    "submission": r"(submission|application) requirements?|how to (apply|submit|enter)|what to submit|requirements?|deliverables?",
}

# Event announcements (webinars, office hours) mention dates and "virtual"
# but are not terms of the opportunity itself.
_NOISE = re.compile(
    r"webinar|office hours?|open hours?|info(rmation(al)?)? session|workshop|newsletter",
    re.I,
)

# Sentence-level keyword triggers used when a page is not cleanly structured.
_SENTENCE_PATTERNS = {
    "deadline": r"\bdeadline\b|\bdue\b|\bclos(e|es|ing)\b|submitted (by|no later than|before)|\blast day\b|\bopens?\b",
    "eligibility": r"\beligib|\bopen to\b|\bmust be (a|an|at least)\b|\bresidents?\b|\bcitizens?\b|\b(age|aged) \d|\b18\b|\benrolled\b",
    "participation": r"\bremote(ly)?\b|\bvirtual(ly)?\b|\bonline\b|\bin[- ]person\b|\bon[- ]?site\b|\btravel\b|\bhybrid\b|\battend\b",
    "submission": r"\bsubmi(t|ssion|ssions)\b|\bdeliverables?\b|\bmust include\b|\bpitch deck\b|\bvideo\b|\brepository\b|\bwrite-?up\b|\bdemo\b",
}

_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ]
    )
}
_MONTHS.update({k[:3]: v for k, v in list(_MONTHS.items())})
_MONTHS["sept"] = 9

_DATE_RE = re.compile(
    r"\b(?P<month>jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|june?|july?|aug(ust)?|"
    r"sep(t|tember)?|oct(ober)?|nov(ember)?|dec(ember)?)\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<year>\d{4})\b"  # codespell:ignore
    r"|\b(?P<iy>\d{4})-(?P<im>\d{2})-(?P<id>\d{2})\b"
    r"|\b(?P<uday>\d{1,2})\s+(?P<umonth>jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|june?|july?|aug(ust)?|"
    r"sep(t|tember)?|oct(ober)?|nov(ember)?|dec(ember)?)\.?,?\s+(?P<uyear>\d{4})\b",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"[$€£]?\d[\d,]*(\.\d+)?\s*(k|m|%|usd)?", re.IGNORECASE)

# Words whose presence or absence changes obligations/permissions.
_STRENGTH_WORDS = {
    "must",
    "required",
    "require",
    "requires",
    "mandatory",
    "optional",
    "only",
    "not",
    "no",
    "cannot",
    "may",
    "allowed",
    "permitted",
    "prohibited",
    "excluded",
    "except",
    "unless",
    "longer",
    # Conjunctions change obligations: "a proposal and a video" vs "or".
    "and",
    "or",
    "either",
    "both",
    "neither",
    "nor",
}

# Words that routinely come and go in copy edits without changing meaning.
_FILLER_WORDS = {
    "a",
    "an",
    "the",
    "all",
    "any",
    "each",
    "every",
    "please",
    "note",
    "kindly",
    "that",
    "this",
    "these",
    "those",
    "of",
    "to",
    "for",
    "by",
    "on",
    "in",
    "at",
    "is",
    "are",
    "be",
    "will",
    "should",
    "later",
    "than",
    "via",
    "through",
    "using",
    "your",
    "our",
    "their",
    "its",
    "with",
    "as",
    "from",
    "official",
    "portal",
    "online",
    "form",
    "page",
    "here",
    "below",
    "above",
    "following",
    "applicants",
    "applicant",
    "participants",
    "entrants",
    "teams",
    "team",
    "entries",
    "entry",
    "application",
    "applications",
    "received",
    "submitted",
    "made",
    "complete",
    "completed",
    "full",
    "fully",
    "also",
    "now",
    "currently",
    "time",
    "pm",
    "am",
    "et",
    "pt",
    "utc",
}


# ---------------------------------------------------------------------------
# HTML -> text
# ---------------------------------------------------------------------------


class _TextExtractor(HTMLParser):
    _BLOCK = frozenset(
        {
            "p",
            "div",
            "li",
            "ul",
            "ol",
            "br",
            "tr",
            "td",
            "th",
            "dt",
            "dd",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "section",
            "article",
            "header",
            "footer",
            "table",
            "blockquote",
        }
    )
    _SKIP = frozenset({"script", "style", "noscript", "svg", "template", "nav"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """Return (page title, visible text with one block per line)."""
    parser = _TextExtractor()
    parser.feed(html)
    raw = "".join(parser.parts)
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw.split("\n")]
    text = "\n".join(line for line in lines if line)
    return re.sub(r"\s+", " ", parser.title).strip(), text


# ---------------------------------------------------------------------------
# Evidence extraction
# ---------------------------------------------------------------------------


def _split_sentences(line: str) -> list[str]:
    parts = re.split(r"(?<=[.!?;])\s+(?=[A-Z0-9\"'(])", line)
    return [p.strip() for p in parts if p.strip()]


def _match_label(line: str) -> str | None:
    clean = line.strip().lstrip("-•*").rstrip(":").strip().lower()
    if len(clean) > 40:
        return None
    for field, pattern in _LABEL_PATTERNS.items():
        if re.fullmatch(pattern, clean):
            return field
    return None


def _looks_like_heading(line: str) -> bool:
    """Short, unpunctuated lines are section headings on most listing pages."""
    words = line.split()
    return (
        len(line) <= 40
        and len(words) <= 5
        and not re.search(r"[.!?;:,]$", line)
        and not parse_dates(line)
    )


def parse_dates(text: str) -> list[str]:
    """Return ISO dates found in text, in order of appearance."""
    found: list[str] = []
    for m in _DATE_RE.finditer(text):
        try:
            if m.group("iy"):
                d = date(int(m.group("iy")), int(m.group("im")), int(m.group("id")))
            elif m.group("month"):
                month = _MONTHS[m.group("month").lower()[:3]]
                d = date(int(m.group("year")), month, int(m.group("day")))
            else:
                month = _MONTHS[m.group("umonth").lower()[:3]]
                d = date(int(m.group("uyear")), month, int(m.group("uday")))
        except (ValueError, KeyError):
            continue
        iso = d.isoformat()
        if iso not in found:
            found.append(iso)
    return found


def participation_modes(text: str) -> set[str]:
    """Classify participation wording into {'remote', 'in_person'}."""
    modes: set[str] = set()
    for sentence in _split_sentences(text):
        s = sentence.lower()
        remote = re.search(
            r"\bremote(ly)?\b|\bvirtual(ly)?\b|\bonline\b|from anywhere", s
        )
        negated_remote = remote and re.search(
            r"(no|not|cannot|can't|isn't|without)\s+(\w+\s+){0,2}(remote|virtual|online)"
            r"|(remote|virtual|online)\s+(\w+\s+){0,3}(is|are)\s+not\b"
            r"|(remote|virtual|online)\s+(\w+\s+){0,3}(not available|not permitted|not allowed|unavailable|not offered)",
            s,
        )
        if remote and not negated_remote:
            modes.add("remote")
        in_person = re.search(
            r"\bin[- ]person\b|\bon[- ]?site\b|must (travel|attend)|travel to\b|held (in|at)\b",
            s,
        )
        optional_travel = re.search(r"travel (is )?(optional|not required)", s)
        negated_ip = re.search(r"(no|not)\s+(\w+\s+){0,2}(in[- ]person|on[- ]?site)", s)
        if in_person and not negated_ip:
            modes.add("in_person")
        if optional_travel:
            modes.add("remote")
    if "hybrid" in text.lower():
        modes.update({"remote", "in_person"})
    return modes


def extract_evidence(text: str) -> dict:
    """Extract priority-field evidence from page text.

    Returns {field: {"text": str, "dates": [...], "modes": [...]}} for every
    field that has evidence on the page. Missing fields are omitted.
    """
    lines = [line for line in text.split("\n") if line.strip()]
    collected: dict[str, list[str]] = {f: [] for f, _ in FIELDS}

    # Pass 1: structured sections (label line followed by content lines).
    current: str | None = None
    taken = 0
    for line in lines:
        label = _match_label(line)
        if label:
            current, taken = label, 0
            continue
        if _NOISE.search(line):
            continue
        # Date sections are often laid out as short fragments ("Full proposal",
        # "July 28 2027"), so only non-date sections end at a short heading.
        if current and current != "deadline" and _looks_like_heading(line):
            current = None
            continue
        if current and taken < (6 if current == "deadline" else 4) and len(line) > 3:
            collected[current].append(line)
            taken += 1
            continue
        current = None

    # Pass 2: keyword sentences anywhere, if a field has no structured section.
    for field, pattern in _SENTENCE_PATTERNS.items():
        if collected[field]:
            continue
        for line in lines:
            if _NOISE.search(line):
                continue
            for sentence in _split_sentences(line):
                if len(sentence) < 12 or len(sentence) > 400:
                    continue
                if field == "deadline" and not parse_dates(sentence):
                    continue
                if re.search(pattern, sentence, re.IGNORECASE):
                    collected[field].append(sentence)
            if len(collected[field]) >= 4:
                break

    evidence: dict[str, dict] = {}
    for field, _ in FIELDS:
        seen: list[str] = []
        for item in collected[field]:
            if item not in seen:
                seen.append(item)
        if not seen:
            continue
        joined = " ".join(seen[:4])
        if len(joined) > 700:
            joined = joined[:697].rsplit(" ", 1)[0] + "…"
        entry: dict = {"text": joined, "dates": parse_dates(joined)}
        if field == "participation":
            entry["modes"] = sorted(participation_modes(joined))
        evidence[field] = entry
    return evidence


def content_hash(evidence: dict) -> str:
    canonical = "|".join(
        f"{f}:{_normalize(evidence.get(f, {}).get('text', ''))}" for f, _ in FIELDS
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    text = (
        text.lower()
        .replace("\u2019", "'")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )
    text = re.sub(r"[^\w\s$%-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9$%]+", _normalize(text).replace("-", " "))


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _signals(text: str, field: str) -> dict:
    tokens = set(_tokens(text))
    signals = {
        "dates": sorted(parse_dates(text)),
        "numbers": sorted(
            {
                re.sub(r"[,\s]", "", m.group(0)).lower()
                for m in _NUMBER_RE.finditer(_DATE_RE.sub(" ", text))
            }
        ),
        "strength": sorted(tokens & _STRENGTH_WORDS),
    }
    if field == "participation":
        signals["modes"] = sorted(participation_modes(text))
    return signals


def _proper_nouns(text: str) -> set[str]:
    nouns = set()
    for sentence in _split_sentences(text):
        words = re.findall(r"[A-Za-z][\w'-]*", sentence)
        for w in words[1:]:
            if w[0].isupper() and w.lower() not in _FILLER_WORDS:
                nouns.add(w.lower())
    return nouns


def word_diff(old: str, new: str) -> dict:
    """Word-level diff segments for side-by-side rendering."""
    a, b = old.split(), new.split()
    sm = difflib.SequenceMatcher(
        a=[_normalize(w) for w in a], b=[_normalize(w) for w in b], autojunk=False
    )
    before: list[dict] = []
    after: list[dict] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            before.append({"op": "eq", "text": " ".join(a[i1:i2])})
            after.append({"op": "eq", "text": " ".join(b[j1:j2])})
        else:
            if i2 > i1:
                before.append({"op": "del", "text": " ".join(a[i1:i2])})
            if j2 > j1:
                after.append({"op": "ins", "text": " ".join(b[j1:j2])})
    return {"before": before, "after": after}


@dataclass
class FieldChange:
    field: str
    kind: str  # "material" | "cosmetic" | "added" | "removed"
    before: str
    after: str
    detail: str

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "label": FIELD_LABELS[self.field],
            "kind": self.kind,
            "before": self.before,
            "after": self.after,
            "detail": self.detail,
            "diff": word_diff(self.before, self.after),
        }


def classify_field_change(field: str, before: str, after: str) -> FieldChange | None:
    """Classify a change in one field. Returns None if text is identical."""
    if _normalize(before) == _normalize(after):
        return (
            None
            if before.strip() == after.strip()
            else FieldChange(
                field, "cosmetic", before, after, "Punctuation or formatting only."
            )
        )

    sig_a, sig_b = _signals(before, field), _signals(after, field)
    reasons = []
    if sig_a["dates"] != sig_b["dates"]:
        reasons.append("dates changed")
    if sig_a["numbers"] != sig_b["numbers"]:
        reasons.append("amounts or counts changed")
    if sig_a.get("modes") != sig_b.get("modes"):
        reasons.append("participation format changed")
    if sig_a["strength"] != sig_b["strength"]:
        reasons.append("obligation wording changed (must / optional / only / not)")

    nouns_changed = _proper_nouns(before) ^ _proper_nouns(after)
    if nouns_changed:
        reasons.append("named places, groups or items changed")

    content_a = {_stem(t) for t in _tokens(before) if t not in _FILLER_WORDS}
    content_b = {_stem(t) for t in _tokens(after) if t not in _FILLER_WORDS}
    union = content_a | content_b
    churn = len(content_a ^ content_b) / len(union) if union else 0.0
    if churn > 0.4:
        reasons.append("substantial new wording")

    if reasons:
        return FieldChange(
            field, "material", before, after, "; ".join(reasons).capitalize() + "."
        )
    return FieldChange(
        field,
        "cosmetic",
        before,
        after,
        "Wording edited; dates, requirements and format are unchanged.",
    )


def compare_evidence(baseline: dict, current: dict) -> list[FieldChange]:
    changes: list[FieldChange] = []
    for field, _ in FIELDS:
        old = (baseline.get(field) or {}).get("text", "")
        new = (current.get(field) or {}).get("text", "")
        if not old and not new:
            continue
        if old and not new:
            changes.append(
                FieldChange(
                    field, "removed", old, "", "No longer stated on the source page."
                )
            )
        elif new and not old:
            changes.append(
                FieldChange(field, "added", "", new, "Newly stated on the source page.")
            )
        else:
            change = classify_field_change(field, old, new)
            if change:
                changes.append(change)
    return changes


# ---------------------------------------------------------------------------
# Decision impact
# ---------------------------------------------------------------------------

# Saved-reason keywords -> fields the reason depends on.
_REASON_CONCERNS = {
    "participation": r"travel|in[- ]person|on[- ]?site|onsite|relocat|commute|attend|remote|virtual|location|distance|fly|flight",
    "deadline": r"deadline|too soon|not enough time|no time|timeline|timing|date|rush|due|schedule|calendar|busy",
    "eligibility": r"eligib|qualif|citizen|resident|student|age|degree|license|credential|open to|not allowed|only for",
    "submission": r"requirement|submi|video|deck|demo|repo|code|portfolio|essay|letter|team|workload|effort|deliverable|prototype",
}

DECISIONS = ("pursue", "watch", "pass")

# Verdicts, in queue-priority order.
VERDICT_RECONSIDER = "reconsider"
VERDICT_REVIEW = "review"
VERDICT_UNVERIFIED = "unverified"
VERDICT_QUIET = "quiet"
VERDICT_CURRENT = "current"
VERDICT_BASELINE = "baseline"

ATTENTION_VERDICTS = (VERDICT_RECONSIDER, VERDICT_REVIEW, VERDICT_UNVERIFIED)


def reason_concerns(reason: str) -> list[str]:
    reason = (reason or "").lower()
    return [f for f, pattern in _REASON_CONCERNS.items() if re.search(pattern, reason)]


def _direction(change: FieldChange, today: date) -> str:
    """'easier', 'harder' or 'unclear' for the user, given a material change."""
    if change.field == "participation":
        a = participation_modes(change.before)
        b = participation_modes(change.after)
        if "remote" in b and "remote" not in a:
            return "easier"
        if "remote" in a and "remote" not in b:
            return "harder"
        return "unclear"
    if change.field == "deadline":
        a, b = parse_dates(change.before), parse_dates(change.after)
        if a and b:
            last_a, last_b = max(a), max(b)
            if last_b < today.isoformat():
                return "harder"
            if last_b > last_a:
                return "easier"
            if last_b < last_a:
                return "harder"
        return "unclear"
    before = set(_tokens(change.before))
    after = set(_tokens(change.after))
    if change.field == "submission":
        loosened = {"optional", "no", "longer"} & (after - before)
        tightened = {"must", "required", "mandatory"} & (after - before)
        if loosened and not tightened:
            return "easier"
        if tightened and not loosened:
            return "harder"
    if change.field == "eligibility":
        if {"only", "must", "excluded"} & (after - before):
            return "harder"
        if {"only", "must", "excluded"} & (before - after) or {
            "any",
            "anyone",
            "all",
            "worldwide",
            "international",
        } & (after - before):
            return "easier"
    return "unclear"


def _clip(text: str, limit: int = 160) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def assess_impact(
    decision: str, reason: str, changes: list[FieldChange], today: date | None = None
) -> dict:
    """Decide whether a set of source changes should reopen the saved decision."""
    today = today or date.today()
    decision = (decision or "watch").lower()
    material = [c for c in changes if c.kind != "cosmetic"]
    cosmetic = [c for c in changes if c.kind == "cosmetic"]
    concerns = reason_concerns(reason)

    if not material:
        if cosmetic:
            fields = ", ".join(FIELD_LABELS[c.field].lower() for c in cosmetic)
            return {
                "verdict": VERDICT_QUIET,
                "headline": "Wording edited — nothing that affects your decision",
                "explanation": f"The source reworded the {fields} text, but dates, requirements and format are the same.",
                "related_fields": [],
            }
        return {
            "verdict": VERDICT_CURRENT,
            "headline": "No changes since your last check",
            "explanation": "Deadline, eligibility, format and submission requirements match the last verified evidence.",
            "related_fields": [],
        }

    scored = []
    for c in material:
        direction = _direction(c, today)
        related = c.field in concerns
        scored.append((c, direction, related))

    # Changes that undercut a "pass"/"watch" reason -> Reconsider.
    if decision in ("pass", "watch"):
        for c, direction, related in scored:
            if related and direction == "easier":
                return {
                    "verdict": VERDICT_RECONSIDER,
                    "headline": f"{FIELD_LABELS[c.field]} changed — your reason to {decision} may no longer hold",
                    "explanation": (
                        f"You chose {decision.capitalize()} because “{_clip(reason).rstrip('.')}.” "
                        f"The official source now says “{_clip(c.after).rstrip('.')}.”"
                    ),
                    "related_fields": [c.field],
                    "suggested_decision": "pursue"
                    if decision == "watch" or len(concerns) == 1
                    else "watch",
                }
        for c, _dir, related in scored:
            if related:
                return {
                    "verdict": VERDICT_RECONSIDER,
                    "headline": f"{FIELD_LABELS[c.field]} changed — check it against your reason",
                    "explanation": (
                        f"You chose {decision.capitalize()} because “{_clip(reason).rstrip('.')}.” "
                        f"That depends on {FIELD_LABELS[c.field].lower()}, which changed. {c.detail}"
                    ),
                    "related_fields": [c.field],
                    "suggested_decision": "watch" if decision == "pass" else decision,
                }

    # Changes that make a "pursue" harder -> Review.
    if decision == "pursue":
        for c, direction, _related in scored:
            if direction == "harder":
                return {
                    "verdict": VERDICT_REVIEW,
                    "headline": f"{FIELD_LABELS[c.field]} tightened — your plan may need to change",
                    "explanation": f"You're pursuing this. The official source now says “{_clip(c.after).rstrip('.')}.” {c.detail}",
                    "related_fields": [c.field],
                }

    c = material[0]
    names = ", ".join(FIELD_LABELS[x.field].lower() for x in material)
    return {
        "verdict": VERDICT_REVIEW,
        "headline": f"{FIELD_LABELS[c.field]} changed on the official source",
        "explanation": f"Material change in {names}. It isn't tied to your saved reason, but it may matter. {c.detail}",
        "related_fields": [x.field for x in material],
    }


def evaluate_check(
    *,
    baseline: dict | None,
    current: dict | None,
    page_title: str,
    expected_title: str,
    decision: str,
    reason: str,
    error: str | None = None,
    today: date | None = None,
) -> dict:
    """Full verdict for one check. ``current`` is None when retrieval failed."""
    if error or current is None:
        return {
            "outcome": "failed",
            "verdict": VERDICT_UNVERIFIED,
            "headline": "Couldn't verify the official source",
            "explanation": f"{error or 'The page could not be retrieved.'} Your decision and the last verified evidence are unchanged.",
            "changes": [],
            "related_fields": [],
        }

    if not current:
        return {
            "outcome": "ambiguous",
            "verdict": VERDICT_UNVERIFIED,
            "headline": "Couldn't verify — the page no longer states key terms",
            "explanation": "The source loaded but no deadline, eligibility, format or submission terms could be found. Your decision and the last verified evidence are unchanged.",
            "changes": [],
            "related_fields": [],
        }

    if expected_title and not _title_matches(expected_title, page_title):
        if baseline:
            return {
                "outcome": "ambiguous",
                "verdict": VERDICT_UNVERIFIED,
                "headline": "Couldn't verify — the source may now be a different page",
                "explanation": f"The page title is now “{_clip(page_title, 90)}”, which doesn't match this opportunity. Your decision and the last verified evidence are unchanged.",
                "changes": [],
                "related_fields": [],
            }

    if not baseline:
        return {
            "outcome": "verified",
            "verdict": VERDICT_BASELINE,
            "headline": "Evidence captured",
            "explanation": "This is the first verified check. Future checks compare against it.",
            "changes": [],
            "related_fields": [],
        }

    changes = compare_evidence(baseline, current)
    removed = [c for c in changes if c.kind == "removed"]
    if removed and len(removed) * 2 >= len([f for f, _ in FIELDS if baseline.get(f)]):
        return {
            "outcome": "ambiguous",
            "verdict": VERDICT_UNVERIFIED,
            "headline": "Couldn't verify — key terms disappeared from the page",
            "explanation": "Several previously verified terms are missing, which usually means the page was restructured or replaced. Your decision and the last verified evidence are unchanged.",
            "changes": [c.to_dict() for c in changes],
            "related_fields": [c.field for c in removed],
        }

    impact = assess_impact(decision, reason, changes, today=today)
    return {"outcome": "verified", **impact, "changes": [c.to_dict() for c in changes]}


def _title_matches(expected: str, page_title: str) -> bool:
    if not page_title:
        return True  # Nothing to contradict.
    want = {t for t in _tokens(expected) if t not in _FILLER_WORDS and len(t) > 2}
    have = set(_tokens(page_title))
    if not want:
        return True
    return len(want & have) / len(want) >= 0.5
