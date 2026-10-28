"""Hide personal identifiers before any text is sent to an AI provider.

The model never needs a national ID, bank, card, passport or phone number, or an email address, to classify a
message or draft a reply. So they are replaced with tokens like [NATIONAL_ID] in the copy that goes to the model.
The stored message keeps the original text: the reviewer sees everything, and only the AI does not.

The patterns lean towards hiding too much, but stay clear of dates, times, years, money amounts and short reference
numbers, which drafts legitimately need. Names are not removed: replies greet the person by name.
"""
import re
from dataclasses import dataclass

_L = r"(?<![\w-])"  # not glued to a word or a hyphenated code
_R = r"(?![\w-])"

# Applied in order: specific formats first, the generic long-number rule last.
PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b")),
    # Pakistani CNIC: 35202-1234567-1 (an unseparated 13-digit number is caught as NUMBER below)
    ("NATIONAL_ID", re.compile(_L + r"\d{5}([- ])\d{7}\1\d" + _R)),
    # only next to the word "passport" (the format alone matches too many codes); group 1 is what gets replaced
    ("PASSPORT", re.compile(r"(?i)\bpassport(?:\s*(?:no\.?|number|#))?\s*[:-]?\s*([A-Z]{1,2}\d{6,8})\b")),
    # 13-19 digits, plain or in card groups; must pass the Luhn check
    ("CARD_NUMBER", re.compile(_L + r"(?:\d{13,19}|\d{4}(?:[ -]\d{4}){2,3}(?:[ -]\d{1,3})?|\d{4}[ -]\d{6}[ -]\d{5})"
                               + _R)),
    # international (+92 300 1234567, 0044 20 7946 0958) or local starting with 0 (03001234567, 042-3576-1234)
    ("PHONE", re.compile(r"(?<![\w+])(?:\+|00)\d{1,3}(?:[ .-]?\(?\d{1,4}\)?){2,5}" + _R
                         + r"|" + _L + r"0(?:\d{9,10}|\d{2,4}[ .-]\d{3,4}(?:[ .-]?\d{3,4})?)" + _R)),
    # anything else with 9+ digits: account numbers, IDs without separators. Groups of 3+ digits only, so dates
    # and times (2026-10-27 14:30) never match.
    ("NUMBER", re.compile(_L + r"(?:\d{9,}|\d{3,}(?:[ -]\d{3,})+)" + _R)),
]
MIN_DIGITS = {"PHONE": 8, "NUMBER": 9}


def _luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        n = int(ch)
        if i % 2 == parity:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


@dataclass
class Redaction:
    text: str
    kinds: list[str]  # what was hidden, e.g. ["NATIONAL_ID", "NUMBER"]; empty if nothing


def find_identifiers(text: str) -> list[tuple[int, int, str]]:
    """(start, end, kind) of every identifier redact() hides, as offsets into text, for highlighting it to the
    reviewer. A found span is blanked before the next pattern runs, the same order and rules as redact()."""
    spans: list[tuple[int, int, str]] = []
    masked = text
    for kind, pattern in PATTERNS:
        for m in pattern.finditer(masked):
            value = m.group(0)
            digits = re.sub(r"\D", "", value)
            if len(digits) < MIN_DIGITS.get(kind, 0):
                continue
            if kind == "CARD_NUMBER" and not _luhn_ok(digits):
                continue
            if kind == "IBAN" and not re.search(r"\d{6}", value.replace(" ", "")):
                continue
            start, end = (m.start(1), m.end(1)) if kind == "PASSPORT" else (m.start(0), m.end(0))
            spans.append((start, end, kind))
        for start, end, _ in spans:
            masked = masked[:start] + "\0" * (end - start) + masked[end:]
    return sorted(spans)


def redact(text: str) -> Redaction:
    kinds: set[str] = set()
    for kind, pattern in PATTERNS:
        def swap(m: re.Match, kind=kind) -> str:
            value = m.group(0)
            digits = re.sub(r"\D", "", value)
            if len(digits) < MIN_DIGITS.get(kind, 0):
                return value
            if kind == "CARD_NUMBER" and not _luhn_ok(digits):
                return value  # left for the phone / number rules
            if kind == "IBAN" and not re.search(r"\d{6}", value.replace(" ", "")):
                return value  # a run of capitalised words, not an account
            kinds.add(kind)
            if kind == "PASSPORT":  # keep the label ("passport no."), hide the value
                return value[:m.start(1) - m.start(0)] + f"[{kind}]" + value[m.end(1) - m.start(0):]
            return f"[{kind}]"
        text = pattern.sub(swap, text)
    return Redaction(text, sorted(kinds))
