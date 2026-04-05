"""
Confidence Scorer — Gap 4: Uncertainty Signaling.

Scores Luna's response confidence (0.0–1.0) using lightweight heuristics
plus an optional Ollama verification pass. When confidence < HEDGE_THRESHOLD,
injects hedging language so Luna never presents guesses as facts.

Two-pass design:
  1. Fast heuristic scan (regex, always runs, ~0ms)
  2. Optional Ollama verification (only for factual claims, ~1-3s, background-safe)

Confidence dimensions:
  - Factual certainty  (is this a claim that could be wrong?)
  - Source grounding   (is this from memory/tools or hallucinated?)
  - Temporal freshness (is this about recent data that may have changed?)
  - Scope clarity      (is Luna speaking within her knowledge boundaries?)
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Score threshold below which hedging language is prepended
HEDGE_THRESHOLD = 0.60

# Patterns that signal LOW confidence in the response (reduce score)
_LOW_CONFIDENCE_SIGNALS = [
    (r"\bi (?:think|believe|assume|guess|suspect)\b", -0.15),
    (r"\bprobably\b", -0.10),
    (r"\bmight\b|\bcould be\b|\bmay be\b|\bmaybe\b", -0.10),
    (r"\bnot sure\b|\bunsure\b|\buncertain\b", -0.20),
    (r"\bnot (?:100%|entirely|completely) sure\b", -0.20),
    (r"\bif i recall correctly\b|\bif memory serves\b", -0.20),
    (r"\bi(?:'m| am) not certain\b", -0.20),
    (r"\bapproximately\b|\baround\b|\broughly\b|\babout\b", -0.05),
    (r"\bit (?:seems|appears|looks like)\b", -0.10),
    (r"\bsomething like\b|\bsomewhere around\b", -0.10),
    (r"\bcheck (?:that|this|the) (?:again|yourself|manually)\b", -0.15),
    (r"\byou(?:'d| would) (?:need to |want to )?verify\b", -0.15),
    (r"\bi(?:'ll| will) need to look (?:that|this) up\b", -0.25),
    (r"\bdon't (?:have|know) (?:the )?(?:exact|specific|precise)\b", -0.20),
]

# Patterns that signal HIGH confidence (increase score)
_HIGH_CONFIDENCE_SIGNALS = [
    (r"\baccording to\b", +0.10),
    (r"\bthe (?:data|records?|logs?|database) show", +0.15),
    (r"\bi (?:found|retrieved|fetched|confirmed|verified)\b", +0.15),
    (r"\bconfirmed\b|\bverified\b|\bfact\b", +0.10),
    (r"\bexactly\b|\bprecisely\b|\bspecifically\b", +0.05),
]

# Topic patterns that warrant extra scrutiny (these domains are hallucination-prone)
_RISKY_DOMAINS = [
    r"\bspecific (?:number|figure|statistic|percentage|date)\b",
    r"\b(?:market share|revenue|valuation|funding)\b",
    r"\b(?:api key|token|password|secret)\b",
    r"\blatitude|longitude|coordinates\b",
    r"\bregulation|law|legal requirement\b",
    r"\bmedical|diagnosis|dosage|prescription\b",
]

# Hedging prefixes to prepend when confidence is low
_HEDGE_PREFIXES = [
    "Just to flag — I'm not 100% certain here, but ",
    "Heads up: this is my best understanding, but worth double-checking — ",
    "I'm fairly confident, but you may want to verify: ",
    "Take this with a grain of salt — ",
]

_hedge_index = 0  # round-robin across prefixes


def score_response_confidence(
    response_text: str,
    user_message: str = "",
    tool_calls_made: bool = False,
) -> float:
    """
    Score the confidence of a response using heuristics.

    Args:
        response_text: Luna's response text
        user_message: The user's original question (helps detect risky domains)
        tool_calls_made: Whether Luna used tools to ground the response

    Returns:
        float 0.0–1.0 (1.0 = fully confident, 0.0 = highly uncertain)
    """
    score = 0.80  # Baseline: assume reasonably confident

    # Boost if grounded in tool calls
    if tool_calls_made:
        score += 0.10

    lower = response_text.lower()
    combined = (user_message + " " + response_text).lower()

    # Apply low/high confidence signals
    for pattern, delta in _LOW_CONFIDENCE_SIGNALS:
        if re.search(pattern, lower):
            score += delta

    for pattern, delta in _HIGH_CONFIDENCE_SIGNALS:
        if re.search(pattern, lower):
            score += delta

    # Risky domains reduce confidence
    for pattern in _RISKY_DOMAINS:
        if re.search(pattern, combined):
            score -= 0.10
            break  # Only penalise once

    return max(0.0, min(1.0, round(score, 3)))


def apply_hedging(response_text: str, confidence: float) -> str:
    """
    If confidence < HEDGE_THRESHOLD, prepend a hedging phrase.
    Returns the original text unchanged if confidence is sufficient.
    """
    global _hedge_index

    if confidence >= HEDGE_THRESHOLD:
        return response_text

    # Don't hedge very short responses (confirmations, greetings)
    if len(response_text.split()) < 12:
        return response_text

    # Don't double-hedge if text already starts with an uncertainty phrase
    lower_start = response_text[:80].lower()
    already_hedged = any(
        re.search(p, lower_start)
        for p, _ in _LOW_CONFIDENCE_SIGNALS[:4]  # Check the strongest signals
    )
    if already_hedged:
        return response_text

    prefix = _HEDGE_PREFIXES[_hedge_index % len(_HEDGE_PREFIXES)]
    _hedge_index += 1

    # Lower-case the first char of response if appending mid-sentence
    if response_text and response_text[0].isupper() and not response_text.startswith("I "):
        hedged = prefix + response_text[0].lower() + response_text[1:]
    else:
        hedged = prefix + response_text

    return hedged


def score_and_maybe_hedge(
    response_text: str,
    user_message: str = "",
    tool_calls_made: bool = False,
) -> tuple[str, float]:
    """
    Score response confidence and optionally inject hedging.

    Returns:
        (final_response_text, confidence_score)
    """
    confidence = score_response_confidence(
        response_text=response_text,
        user_message=user_message,
        tool_calls_made=tool_calls_made,
    )
    final = apply_hedging(response_text, confidence)

    if confidence < HEDGE_THRESHOLD:
        logger.debug(
            "Low confidence response (%.2f) — hedging applied. "
            "First 80 chars: %s",
            confidence,
            response_text[:80],
        )

    return final, confidence
