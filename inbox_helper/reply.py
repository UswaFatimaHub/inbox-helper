"""Greeting and sign-off: added by code, never written by the AI.

The model writes only the body of a reply (and says which language the candidate wrote in). compose() wraps the
body in the same layout every time:

    Hi Rabia,

    <body>

    Best regards,
    Brightpath Recruiting Team

Replies in another language get a greeting and closing in that language (LOCALIZED), so a Spanish body never sits
between an English greeting and sign-off. For English, each reviewer can set their own greeting and sign-off
(reviewer_settings); otherwise the defaults apply.

strip_salutations() removes a greeting or sign-off the model writes anyway: inline ("Dear Rabia, thank you ...
follow up. Brightpath Recruiting Team"), on their own lines, or in another language ("Hola Maria," ... "Saludos").
"""
import re

TEAM = "Brightpath Recruiting Team"  # the brand name stays as it is in every language

# language: (greeting with the first name, greeting when there is no person's name, closing line)
LOCALIZED = {
    "en": ("Hi {first_name},", "Hello,", "Best regards,"),
    "es": ("Hola {first_name},", "Hola,", "Saludos cordiales,"),
    "fr": ("Bonjour {first_name},", "Bonjour,", "Cordialement,"),
    "de": ("Hallo {first_name},", "Guten Tag,", "Viele Grüße,"),
    "it": ("Gentile {first_name},", "Buongiorno,", "Cordiali saluti,"),
    "pt": ("Olá {first_name},", "Olá,", "Atenciosamente,"),
    "ur": ("السلام علیکم {first_name}،", "السلام علیکم،", "شکریہ،"),
    "ar": ("مرحبًا {first_name}،", "مرحبًا،", "مع أطيب التحيات،"),
}
DEFAULT_GREETING = LOCALIZED["en"][0]
NO_NAME_GREETING = LOCALIZED["en"][1]
DEFAULT_SIGN_OFF = f"{LOCALIZED['en'][2]}\n{TEAM}"
MAX_GREETING = 120
MAX_SIGN_OFF = 400

# Senders whose "name" is a team or a system, not a person to greet by first name
_NOT_A_PERSON = re.compile(r"\b(team|desk|support|office|info|admin|hr|noreply|no-reply|notifications?|google|"
                           r"recruit\w*|careers|jobs|hiring|sales|marketing|events)\b", re.I)

# Greetings and closings the model may write anyway, in the languages candidates use. Keyed by language so an
# old draft's greeting also tells which language it was in (migration 0006).
_GREETING_WORDS = {
    "en": r"hi|hello|hey|dear|good (?:morning|afternoon|evening)|greetings",
    "es": r"hola|estimad[oa]s?|querid[oa]s?|buen(?:os|as) (?:días|tardes|noches)",
    "fr": r"bonjour|bonsoir|salut|cher|chère|madame|monsieur",
    "de": r"hallo|guten tag|liebe[rs]?|sehr geehrte[rs]?",
    "it": r"ciao|buongiorno|gentile|car[oa]",
    "pt": r"olá|ola|prezad[oa]s?|bom dia|boa tarde",
    "ur": r"السلام علیکم|السلام عليكم|وعلیکم السلام|محترم|محترمہ|assalam[- ]?o[- ]?alaikum|salam",
    "ar": r"مرحبا|مرحبًا|عزيزي|عزيزتي|السلام عليكم",
}
_CLOSING_WORDS = (r"best regards|kind regards|warm regards|regards|sincerely|best wishes|many thanks|thanks|cheers|best"
                  r"|saludos cordiales|un saludo|saludos|atentamente|cordialmente|cordialement|bien à vous"
                  r"|mit freundlichen grüßen|viele grüße|beste grüße|cordiali saluti|distinti saluti|atenciosamente"
                  r"|abraços|شکریہ|خیر اندیش|مع أطيب التحيات|مع خالص التحيات")
_END = r"[,!:،]"  # what ends a greeting: "Hi Ali," "Hola Maria:" "السلام علیکم،"


def _greeting_re(words: str) -> re.Pattern:
    return re.compile(rf"^\s*(?:{words})(?![\w])[^\n,!.:،]{{0,60}}{_END}\s*", re.I)


_GREETING = _greeting_re("|".join(_GREETING_WORDS.values()))
_GREETING_BY_LANGUAGE = {lang: _greeting_re(words) for lang, words in _GREETING_WORDS.items()}
_SIGN_OFF = re.compile(
    # a closing word counts only at the start of a line or sentence, so "we wish you the best." keeps its "best"
    rf"(?:(?:(?<=[.!?\n۔])|^)\s*(?:{_CLOSING_WORDS})[,!.،]?)?\s*(?:[-–—]\s*)?(?:the\s+)?brightpath(?:\s+analytics)?"
    rf"\s+recruiting\s+team\.?\s*$"
    rf"|\n\s*(?:{_CLOSING_WORDS})[,،]?(?:\s*\n[^\n]{{0,60}})?\s*$",  # a closing on its own line, maybe a team line after
    re.I)
# a last line of a few words naming Brightpath ("Equipo de Reclutamiento de Brightpath") is a signature
_TEAM_LINE = re.compile(r"\n[^\n.!?۔]{0,50}brightpath[^\n.!?۔]{0,50}\.?\s*$", re.I)


def first_name(name: str) -> str | None:
    """The first word of a person's name; None for "Growth Team", "Google", an email address or nothing."""
    name = re.sub(r"\(.*?\)", "", name or "").strip()  # "Sarah (HR)" -> "Sarah"
    if not name or "@" in name or _NOT_A_PERSON.search(name):
        return None
    word = name.split()[0].strip(",.")
    return word if word[:1].isalpha() else None


def language_of(code: str | None) -> str:
    """A supported language code ("es"), or "en" for anything else."""
    code = (code or "").strip().lower()[:2]
    return code if code in LOCALIZED else "en"


def greeting_for(template: str | None, name: str, no_name: str = NO_NAME_GREETING) -> str:
    template = (template or DEFAULT_GREETING).strip()
    if "{first_name}" not in template and "{name}" not in template:
        return template
    first = first_name(name)
    if not first:
        return no_name
    return template.replace("{first_name}", first).replace("{name}", re.sub(r"\(.*?\)", "", name).strip())


def greeting_language(text: str) -> str | None:
    """The language of the greeting a draft starts with, if any ("Hola Maria," -> "es")."""
    for lang, pattern in _GREETING_BY_LANGUAGE.items():
        if pattern.match(text or ""):
            return lang
    return None


def strip_salutations(text: str, name: str = "") -> str:
    """The body of a reply: greetings at the start and the sign-off at the end removed, in any supported language.
    name: the sender's name; a short first line addressing them ("Maria:") is a greeting too."""
    body = (text or "").strip()
    first = first_name(name)
    for _ in range(2):  # a greeting can be doubled ("Hi Maria,\n\nHola Maria,")
        m = _GREETING.match(body)
        if not m and first:
            m = re.match(rf"^\s*[^\n]{{0,25}}\b{re.escape(first)}\b[^\n]{{0,25}}{_END}\s*\n", body, re.I)
        if not m:
            break
        body = body[m.end():].lstrip()
        body = body[:1].upper() + body[1:]  # "Dear Rabia, thank you" -> "Thank you"
    for _ in range(2):  # "Saludos cordiales,\nEquipo de Brightpath": the team line, then the closing
        body = _TEAM_LINE.sub("", _SIGN_OFF.sub("", body)).rstrip()
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def compose(body: str, name: str, greeting: str | None = None, sign_off: str | None = None,
            language: str | None = None) -> str:
    """Greeting, blank line, body, blank line, sign-off. An empty body (no draft) stays empty.

    greeting / sign_off: the reviewer's own (English replies only); None means the default. A reply in another
    supported language gets that language's greeting and closing instead."""
    body = re.sub(r"\n{3,}", "\n\n", (body or "").strip())  # paragraphs: one blank line between them
    if not body:
        return ""
    lang = language_of(language)
    if lang != "en":
        with_name, without_name, closing = LOCALIZED[lang]
        return f"{greeting_for(with_name, name, without_name)}\n\n{body}\n\n{closing}\n{TEAM}"
    return f"{greeting_for(greeting, name)}\n\n{body}\n\n{(sign_off or DEFAULT_SIGN_OFF).strip()}"
