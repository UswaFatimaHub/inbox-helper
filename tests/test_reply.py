"""Greeting and sign-off are added by code in one fixed layout; whatever the model writes around the body goes."""
import pytest

from inbox_helper.reply import DEFAULT_SIGN_OFF, compose, first_name, greeting_for, greeting_language, strip_salutations


@pytest.mark.parametrize("draft, body", [
    # the reported case: greeting and sign-off run into the body on one line
    ("Dear Rabia, thank you for reaching out. If your portal upload fails, please attach your CV as a PDF. "
     "The recruiter will check and follow up. Brightpath Recruiting Team",
     "Thank you for reaching out. If your portal upload fails, please attach your CV as a PDF. "
     "The recruiter will check and follow up."),
    ("Hi Ali,\n\nThanks for checking in. The recruiter will follow up.\n\nBest regards,\nBrightpath Recruiting Team",
     "Thanks for checking in. The recruiter will follow up."),
    ("Hello Sara,\nWe received your message.\nKind regards, Brightpath Recruiting Team", "We received your message."),
    ("Hi there! We will pass this on.\n\nBest,\nThe Brightpath Recruiting Team.", "We will pass this on."),
    ("Thank you for your message; this inbox handles candidate enquiries only.\n\nBrightpath Recruiting Team",
     "Thank you for your message; this inbox handles candidate enquiries only."),
    ("Hi Omar,\n\nWe will check.\n\nThanks,\nBrightpath Recruiting Team", "We will check."),
])
def test_greeting_and_sign_off_written_by_the_model_are_removed(draft, body):
    assert strip_salutations(draft) == body


@pytest.mark.parametrize("text", [
    "We wish you the best. Brightpath Recruiting Team",
    "We wish you all the best in your new role.",
    "Thanks for letting us know. The recruiter will follow up.",
])
def test_words_that_only_look_like_a_sign_off_are_kept(text):
    assert strip_salutations(text).startswith(text.split(". Brightpath")[0].rstrip("."))


def test_compose_always_uses_the_same_layout():
    reply = compose("Thanks for checking in.\n\n\n\nThe recruiter will follow up.", "Rabia Aslam")
    assert reply == ("Hi Rabia,\n\nThanks for checking in.\n\nThe recruiter will follow up.\n\n" + DEFAULT_SIGN_OFF)


def test_compose_uses_the_reviewers_greeting_and_sign_off():
    reply = compose("Thanks.", "Rabia Aslam", "Dear {first_name},", "Warm wishes,\nUswa\nBrightpath Talent")
    assert reply == "Dear Rabia,\n\nThanks.\n\nWarm wishes,\nUswa\nBrightpath Talent"


def test_no_draft_stays_empty():
    assert compose("", "Rabia") == "" and compose("   ", "Rabia") == ""


@pytest.mark.parametrize("name, first", [
    ("Rabia Aslam", "Rabia"), ("Sarah (HR)", "Sarah"), ("Growth Team", None), ("Google", None), ("", None),
    ("ali@example.com", None), ("Events Desk", None),
])
def test_first_name_only_for_people(name, first):
    assert first_name(name) == first


def test_greeting_without_a_person_name_is_neutral():
    assert greeting_for("Dear {first_name},", "Growth Team") == "Hello,"
    assert greeting_for("Good day,", "Growth Team") == "Good day,"  # no placeholder: used as written


# ---- other languages -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("draft, body", [
    # the reported case: the code's English greeting, then the model's own Spanish one
    ("Hi Maria,\n\nHola Maria,\n\nGracias por escribirnos. Agradecemos su interés en Brightpath.",
     "Gracias por escribirnos. Agradecemos su interés en Brightpath."),
    ("Hola Maria:\n\nGracias por tu mensaje.\n\nSaludos cordiales,\nEquipo de Reclutamiento de Brightpath",
     "Gracias por tu mensaje."),
    ("Maria:\n\nGracias por tu mensaje.\n\nUn saludo,\nBrightpath Recruiting Team", "Gracias por tu mensaje."),
    ("وعلیکم السلام حارث،\n\nآپ کے پیغام کا شکریہ۔\n\nشکریہ،\nBrightpath Recruiting Team", "آپ کے پیغام کا شکریہ۔"),
    ("Bonjour Léa,\n\nMerci pour votre message.\n\nCordialement,\nBrightpath Recruiting Team", "Merci pour votre message."),
])
def test_greetings_and_sign_offs_in_other_languages_are_removed(draft, body):
    name = {"H": "Haris Nadeem", "B": "Léa Martin"}.get(draft[0], "Maria Gonzalez")
    assert strip_salutations(draft, name) == body


def test_a_reply_in_another_language_gets_greeting_and_closing_in_that_language():
    assert compose("Gracias por escribirnos.", "Maria Gonzalez", language="es") == (
        "Hola Maria,\n\nGracias por escribirnos.\n\nSaludos cordiales,\nBrightpath Recruiting Team")
    # the reviewer's own (English) signature is for English replies only
    assert compose("Gracias.", "Maria Gonzalez", "Dear {first_name},", "Cheers,\nUswa", language="es").startswith("Hola Maria,")
    assert compose("Thanks.", "Maria Gonzalez", "Dear {first_name},", "Cheers,\nUswa", language="en").startswith("Dear Maria,")
    assert compose("你好", "Li Wei", language="zh").startswith("Hi Li,")  # unsupported language: English wording


def test_the_greeting_tells_the_language_of_an_old_draft():
    assert greeting_language("Hola Maria:\n\nGracias") == "es"
    assert greeting_language("السلام علیکم،\n\nشکریہ") == "ur"
    assert greeting_language("Hi Ali,\n\nThanks") == "en"
    assert greeting_language("Thanks for writing.") is None
