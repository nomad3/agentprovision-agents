"""Deterministic echocardiogram measurement extractor + QA (Central Vet OS).

The CORE net-new piece of Brett's cardiology referral-report loop. Parses the
"Adult Echo: Measurements and Calculations" block from an echo machine export
into a structured, provenance-stamped, QA-flagged measurement set so a DACVIM
report can be drafted *and every clinical number is human-verifiable*.

Design notes (grounded against the real on-disk sample
health-pets/docs/data/21560820260214_WINNIE_NIETO_*.pdf, 2026-06-04):

- The measurement block is **multi-column TEXT**, not a pdfplumber table
  (`extract_tables()` only catches "Patient Demographics"). So we parse the
  page text with a **label-anchored** regex — layout-tolerant, not positional.
- Each line packs up to three ``label value unit`` triples, e.g.
  ``LVIDd (2D) 2.06 cm  LVAd (A4C) 4.28 cm²  EF (A4C) 69.3 %``. Labels carry a
  parenthesised modality (``(2D)``, ``(MM)``, ``(A4C)``, ``(MM-Teich)``) that
  contains digits — the regex treats a ``(...)`` group as one label chunk so
  those digits aren't mistaken for the value.
- Ratios (``LA/Ao (2D) 1.49``) have NO unit — never require one.
- PDF extraction (PDF→text) is split from parsing (text→measurements) so the
  parser is fully unit-testable against the real text without the PDF.

QA rules (per Luna): ``LA:Ao > 1.6 or < 0.8 ⇒ review``; ``FS% < 25 or > 55 ⇒
review``. Completeness gate: block the draft unless LVIDd, (LVIDs or FS/EF),
LA:Ao, species and weight are present at acceptable confidence.

This module is pure (no DB / network); the workflow step + KG persistence wrap
it. See docs/plans/2026-06-04-central-vet-os-lean-slice-plan.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ── confidence levels ────────────────────────────────────────────────────────
HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"

# Units we recognise in echo exports. Order matters: longer/compound units
# (cm², cm/s, m/s, mmHg) must precede their prefixes (cm, m) so the alternation
# doesn't truncate "cm/s" to "cm".
_UNITS = ["cm²", "cm/s", "m/s", "mmHg", "bpm", "cm", "mm", "ml", "ms", "%", "g", "°"]
_UNIT_RE = "(?:" + "|".join(re.escape(u) for u in _UNITS) + ")"

# A label chunk is either a parenthesised modality group (kept whole so its
# inner digits aren't read as the value) or a word that may carry / ' ` % - .
_LABEL_CHUNK = r"(?:\([^)]*\)|[A-Za-z%][A-Za-z0-9'`%/.\-]*)"
_MEAS_RE = re.compile(
    r"(?P<label>" + _LABEL_CHUNK + r"(?:\s+" + _LABEL_CHUNK + r")*)"
    r"\s*(?P<value>-?\d+(?:\.\d+)?)"
    r"\s*(?P<unit>" + _UNIT_RE + r")?"
)

_MODALITY_RE = re.compile(r"\(([^)]*)\)")

# Canonical field map: normalised-base-label -> canonical key. Base label = the
# label with its modality paren stripped, collapsed + lowercased.
_FIELD_MAP: Dict[str, str] = {
    "lvidd": "lvidd",
    "lvids": "lvids",
    "lvpwd": "lvpwd",
    "lvpws": "lvpws",
    "ivsd": "ivsd",
    "ivss": "ivss",
    "la/ao": "la_ao",
    "la/ao lax": "la_ao",
    "fs": "fs",
    "ef": "ef",
    "la area": "la_area",
    "la dimen": "la_dimen",
    "la lax": "la_lax",
    "ivs/lvpw": "ivs_lvpw",
    "aor diam": "ao_diam",
    "mr vmax": "mr_vmax",
    "tr vmax": "tr_vmax",
    "lvot vmax": "lvot_vmax",
    "mv epss": "mv_epss",
    "mv e/a": "mv_ea",
    "ivrt": "ivrt",
}

# Ratio fields legitimately carry no unit — don't penalise their confidence.
_RATIO_FIELDS = {"la_ao", "ivs_lvpw", "mv_ea"}

# Anchor that opens the measurement block.
_BLOCK_ANCHOR = re.compile(r"measurements?\s+and\s+calculations?", re.I)


@dataclass
class Measurement:
    """One extracted echo measurement, with provenance + QA."""
    field: str                      # canonical key, e.g. "la_ao" (or "" if unmapped)
    label: str                      # raw label, e.g. "LA/Ao (2D)"
    value: float
    unit: str                       # "" for ratios
    modality: Optional[str]         # "2D" | "MM" | "A4C" | "MM-Teich" | ...
    source_page: int
    confidence: str                 # HIGH | MEDIUM | LOW
    outlier_flag: bool = False
    outlier_reason: Optional[str] = None


@dataclass
class CompletenessResult:
    complete: bool
    missing: List[str] = field(default_factory=list)


@dataclass
class EchoExtraction:
    measurements: List[Measurement] = field(default_factory=list)
    by_field: Dict[str, Measurement] = field(default_factory=dict)
    signalment: Dict[str, object] = field(default_factory=dict)
    completeness: CompletenessResult = field(
        default_factory=lambda: CompletenessResult(False)
    )
    needs_review: bool = False
    review_reasons: List[str] = field(default_factory=list)


# ── parsing ──────────────────────────────────────────────────────────────────


def _normalise_label(label: str) -> Tuple[str, Optional[str]]:
    """Return (canonical_field_or_empty, modality). Strips the modality paren,
    collapses whitespace, lowercases, and looks up the field map."""
    modality = None
    m = _MODALITY_RE.search(label)
    if m:
        modality = m.group(1).strip()
    base = _MODALITY_RE.sub("", label)
    base = re.sub(r"\s+", " ", base).strip().lower()
    return _FIELD_MAP.get(base, ""), modality


def parse_measurements_from_text(text: str, *, source_page: int = 0) -> List[Measurement]:
    """Parse all ``label value unit`` triples out of an echo measurement block.

    Scans line by line so a stray multi-line wrap can't merge two measurements.
    Confidence:
      HIGH   — mapped field with a unit (or a known ratio field).
      MEDIUM — mapped field missing an expected unit, OR unmapped-but-clean.
      LOW    — value with no recognisable label.
    """
    out: List[Measurement] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for m in _MEAS_RE.finditer(line):
            label = re.sub(r"\s+", " ", m.group("label")).strip()
            try:
                value = float(m.group("value"))
            except (TypeError, ValueError):
                continue
            unit = (m.group("unit") or "").strip()
            field_key, modality = _normalise_label(label)

            if not label or label.isdigit():
                confidence = LOW
            elif field_key:
                if unit or field_key in _RATIO_FIELDS:
                    confidence = HIGH
                else:
                    confidence = MEDIUM
            else:
                confidence = MEDIUM if unit else LOW

            out.append(
                Measurement(
                    field=field_key,
                    label=label,
                    value=value,
                    unit=unit,
                    modality=modality,
                    source_page=source_page,
                    confidence=confidence,
                )
            )
    return out


# Signalment narrative patterns (from the finalised report, e.g.
# "13y FS Chihuahua" / "Wt: 4.0kg").
_AGE_RE = re.compile(r"\b(\d{1,2})\s*y(?:ears?|o|r)?\b", re.I)
_SEX_RE = re.compile(r"\b(MN|FS|MI|FI|M|F)\b")
_WEIGHT_RE = re.compile(r"\bwt[:\s]*([\d.]+)\s*kg\b", re.I)
# Species inference. Word-boundary only — a bare "cat" SUBSTRING matches inside
# "indicate"/"location"/etc. and mislabels dogs feline (real-PDF bug, 2026-06-04).
_FELINE_BREEDS = {
    "dsh", "dlh", "domestic shorthair", "domestic longhair",
    "siamese", "maine coon", "persian", "ragdoll", "bengal", "sphynx",
}
_FELINE_TEXT_RE = re.compile(
    r"\b(feline|cat|dsh|dlh|domestic short ?hair|domestic long ?hair|siamese|maine coon)\b",
    re.I,
)
_CANINE_TEXT_RE = re.compile(r"\b(canine|dog|k9)\b", re.I)


def parse_signalment_from_text(text: str) -> Dict[str, object]:
    """Best-effort signalment from the finalised-report narrative.

    Secondary to the measurements — used by the completeness gate (species +
    weight) and to stamp the case artifact. Conservative: only fields it can
    read with confidence.
    """
    sig: Dict[str, object] = {}

    am = _AGE_RE.search(text)
    if am:
        sig["age_years"] = int(am.group(1))

    # Sex token typically appears right after the age ("13y FS Chihuahua").
    # Search from am.end() so offsets stay ABSOLUTE in `text` (a window
    # substring would give relative offsets that break the breed slice below).
    sm = _SEX_RE.search(text, am.end()) if am else _SEX_RE.search(text)
    if sm:
        sig["sex"] = sm.group(1).upper()

    wm = _WEIGHT_RE.search(text)
    if wm:
        try:
            sig["weight_kg"] = float(wm.group(1))
        except ValueError:
            pass

    # Breed: the capitalised word(s) after the sex token, on the SAME line
    # (so a following "Presenting Complaint:" line can't be glued on).
    if am and sm:
        tail = text[sm.end():].split("\n", 1)[0].strip()
        bm = re.match(r"([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)", tail)
        if bm:
            sig["breed"] = bm.group(1).strip()

    breed_l = str(sig.get("breed", "")).strip().lower()
    if breed_l in _FELINE_BREEDS or _FELINE_TEXT_RE.search(text):
        sig["species"] = "feline"
    elif sig.get("breed") or _CANINE_TEXT_RE.search(text):
        # Cardiology referrals are dog-dominant; a found, non-feline breed
        # defaults canine. A rare misclassification is caught at human approval.
        sig["species"] = "canine"

    return sig


# ── QA: outliers + completeness ──────────────────────────────────────────────


def _apply_outliers(by_field: Dict[str, Measurement]) -> List[str]:
    """Flag physiologic-range outliers in place; return human review reasons.

    Rules per Luna's QA contract:
      LA:Ao > 1.6 or < 0.8  ⇒ review (left-atrial enlargement / implausible)
      FS%   < 25 or > 55    ⇒ review (systolic function out of range)
    """
    reasons: List[str] = []
    la_ao = by_field.get("la_ao")
    if la_ao is not None and (la_ao.value > 1.6 or la_ao.value < 0.8):
        la_ao.outlier_flag = True
        la_ao.outlier_reason = f"LA:Ao {la_ao.value} outside 0.8–1.6"
        reasons.append(la_ao.outlier_reason)
    fs = by_field.get("fs")
    if fs is not None and (fs.value < 25 or fs.value > 55):
        fs.outlier_flag = True
        fs.outlier_reason = f"FS {fs.value}% outside 25–55"
        reasons.append(fs.outlier_reason)
    return reasons


# A measurement counts as "present" only at HIGH/MEDIUM confidence.
_PRESENT = {HIGH, MEDIUM}


def _check_completeness(
    by_field: Dict[str, Measurement], signalment: Dict[str, object]
) -> CompletenessResult:
    missing: List[str] = []

    def present(key: str) -> bool:
        meas = by_field.get(key)
        return meas is not None and meas.confidence in _PRESENT

    if not present("lvidd"):
        missing.append("LVIDd")
    if not (present("lvids") or present("fs") or present("ef")):
        missing.append("LVIDs/FS/EF (systolic function)")
    if not present("la_ao"):
        missing.append("LA:Ao")
    if not signalment.get("species"):
        missing.append("species")
    if not signalment.get("weight_kg"):
        missing.append("weight")

    return CompletenessResult(complete=not missing, missing=missing)


def _pick_canonical(measurements: List[Measurement]) -> Dict[str, Measurement]:
    """One measurement per canonical field. Prefer higher confidence; on a tie
    prefer 2D over MM (closer to the modern guideline standard), else first."""
    rank = {HIGH: 2, MEDIUM: 1, LOW: 0}
    by_field: Dict[str, Measurement] = {}
    for meas in measurements:
        if not meas.field:
            continue
        cur = by_field.get(meas.field)
        if cur is None:
            by_field[meas.field] = meas
            continue
        if rank[meas.confidence] > rank[cur.confidence]:
            by_field[meas.field] = meas
        elif rank[meas.confidence] == rank[cur.confidence]:
            if meas.modality == "2D" and cur.modality != "2D":
                by_field[meas.field] = meas
    return by_field


def build_extraction(
    *, measurement_text: str, report_text: str = "", source_page: int = 0
) -> EchoExtraction:
    """Assemble a full EchoExtraction from the measurement-block text and the
    (optional) finalised-report narrative.

    ``needs_review`` is the gate the workflow's human_approval step keys on: it
    is True if any QA outlier fired OR the completeness gate failed. The CLI
    draft must NOT be sent without a human clearing this.
    """
    measurements = parse_measurements_from_text(measurement_text, source_page=source_page)
    by_field = _pick_canonical(measurements)
    signalment = parse_signalment_from_text(report_text or measurement_text)

    review_reasons = _apply_outliers(by_field)
    completeness = _check_completeness(by_field, signalment)
    if not completeness.complete:
        review_reasons.append("incomplete: missing " + ", ".join(completeness.missing))

    return EchoExtraction(
        measurements=measurements,
        by_field=by_field,
        signalment=signalment,
        completeness=completeness,
        needs_review=bool(review_reasons),
        review_reasons=review_reasons,
    )


def extract_from_pdf_bytes(pdf_bytes: bytes) -> EchoExtraction:
    """PDF→text→extraction. Thin pdfplumber wrapper; the measurement block is
    located by the "Measurements and Calculations" anchor, and the page text is
    fed to the pure parser. Falls back to whole-document text if the anchor
    isn't found (flagged via empty/incomplete extraction downstream)."""
    import io

    import pdfplumber

    measurement_text = ""
    all_text_parts: List[str] = []
    block_page = 0
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for pi, page in enumerate(pdf.pages):
            txt = page.extract_text() or ""
            all_text_parts.append(txt)
            if not measurement_text and _BLOCK_ANCHOR.search(txt):
                measurement_text = txt
                block_page = pi
    full_text = "\n".join(all_text_parts)
    if not measurement_text:
        measurement_text = full_text
    return build_extraction(
        measurement_text=measurement_text,
        report_text=full_text,
        source_page=block_page,
    )
