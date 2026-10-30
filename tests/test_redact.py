"""Personal identifiers are hidden from the AI; ordinary numbers that drafts need are not."""
import json

import pytest

from inbox_helper.config import ROOT
from inbox_helper.loader import load_messages
from inbox_helper.redact import find_identifiers, redact


@pytest.mark.parametrize("text, expected, kinds", [
    ("Here is my CNIC number 35202-1234567-1 and my bank account number 0123456789012 for the joining bonus.",
     "Here is my CNIC number [NATIONAL_ID] and my bank account number [NUMBER] for the joining bonus.",
     ["NATIONAL_ID", "NUMBER"]),
    ("CNIC: 35202 1234567 1", "CNIC: [NATIONAL_ID]", ["NATIONAL_ID"]),
    ("IBAN PK36SCBL0000001123456702 please", "IBAN [IBAN] please", ["IBAN"]),
    ("IBAN: PK36 SCBL 0000 0011 2345 6702.", "IBAN: [IBAN].", ["IBAN"]),
    ("Card 4111 1111 1111 1111 exp soon", "Card [CARD_NUMBER] exp soon", ["CARD_NUMBER"]),
    ("Call me on +92 300 1234567 or 0300-1234567", "Call me on [PHONE] or [PHONE]", ["PHONE"]),
    ("my number is 03001234567.", "my number is [PHONE].", ["PHONE"]),
    ("UK: +44 (20) 7946 0958", "UK: [PHONE]", ["PHONE"]),
    ("Passport No. AB1234567 attached", "Passport No. [PASSPORT] attached", ["PASSPORT"]),
    ("reach me at amna.r+jobs@mail.example.org instead", "reach me at [EMAIL] instead", ["EMAIL"]),
    ("account 1234-5678-9012", "account [NUMBER]", ["NUMBER"]),
    ("My password is Brightpath123! - could you log in?", "My password is [PASSWORD] - could you log in?",
     ["PASSWORD"]),
    ("Password: hunter2", "Password: [PASSWORD]", ["PASSWORD"]),
    ('the portal password was "Qx7!pw9z" yesterday', 'the portal password was "[PASSWORD]" yesterday', ["PASSWORD"]),
])
def test_identifiers_are_hidden(text, expected, kinds):
    r = redact(text)
    assert (r.text, r.kinds) == (expected, kinds)


@pytest.mark.parametrize("text", [
    "I graduated in 2023 and applied on 2 October.",
    "Interview on 2026-10-27 14:30, or 27/10/2026 at 2:30 pm?",
    "The range was PKR 250,000 to 300,000 per month, or $4,500.",
    "My application reference is REF-2024-00123.",
    "Room 101, building 12, 3 years of experience, 40-110 words.",
    "I scored 1450 on the test and 98.5% in maths.",
    "Order AB1234567 is not a passport.",
    "Thanks, ACME CORP TEAM SALES DEPT",
    "My password is not working and the reset link expired.",
    "I forgot my password: can you send a reset link?",
    "Password reset on 12/10 did not arrive.",
])
def test_ordinary_numbers_and_text_are_kept(text):
    assert redact(text).text == text


def test_only_m039_and_g111_change_in_the_sample_and_golden_messages():
    """Guards against over-redaction: in the synthetic data only M039 (ID and bank numbers) and G111 (a password)
    carry identifiers."""
    texts = {m.message_id: f"{m.subject}\n{m.body}" for m in load_messages(ROOT / "data" / "messages.csv").messages}
    goldens = json.loads((ROOT / "evals" / "goldens.json").read_text(encoding="utf-8"))["goldens"]
    texts |= {g["id"]: f"{g['message'].get('subject', '')}\n{g['message']['body']}" for g in goldens}
    changed = {mid for mid, t in texts.items() if redact(t).text != t}
    assert changed == {"M039", "G111"}


def _replace_spans(text: str) -> str:
    for start, end, kind in sorted(find_identifiers(text), reverse=True):
        text = text[:start] + f"[{kind}]" + text[end:]
    return text


@pytest.mark.parametrize("text", [
    "Here is my CNIC number 35202-1234567-1 and my bank account number 0123456789012 for the joining bonus.",
    "IBAN: PK36 SCBL 0000 0011 2345 6702.", "Card 4111 1111 1111 1111 exp soon", "Passport No. AB1234567 attached",
    "Call me on +92 300 1234567 or 0300-1234567", "My interview is on 2026-10-27 at 14:30, ref 4521.",
    "My password is Brightpath123! - could you log in?",
])
def test_highlight_spans_mark_exactly_what_redact_hides(text):
    assert _replace_spans(text) == redact(text).text


def test_highlight_spans_agree_with_redact_on_the_whole_sample():
    for m in load_messages(ROOT / "data" / "messages.csv").messages:
        assert _replace_spans(m.body) == redact(m.body).text, m.message_id
