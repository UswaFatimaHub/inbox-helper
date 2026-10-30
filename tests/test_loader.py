import json

import pytest

from inbox_helper.loader import InputError, load_messages


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_valid_csv_loads_all_rows(tmp_path):
    p = write(tmp_path, "m.csv", 'message_id,candidate_name,body\nA1,Ann,"Hello, any update?"\nA2,Bo,Withdraw me\n')
    res = load_messages(p)
    assert [m.message_id for m in res.messages] == ["A1", "A2"]
    assert res.messages[0].body == "Hello, any update?"
    assert res.errors == []


def test_json_list_and_wrapped_object(tmp_path):
    rows = [{"message_id": "J1", "body": "Hi"}]
    assert len(load_messages(write(tmp_path, "a.json", json.dumps(rows))).messages) == 1
    assert len(load_messages(write(tmp_path, "b.json", json.dumps({"messages": rows}))).messages) == 1


def test_bom_is_ignored(tmp_path):
    p = tmp_path / "bom.csv"
    p.write_text("message_id,body\nB1,Hi\n", encoding="utf-8-sig")
    assert load_messages(p).messages[0].message_id == "B1"


@pytest.mark.parametrize("name,text,expected", [
    ("m.csv", "message_id,subject\nX,Hi\n", r"missing required column\(s\): body"),
    ("m.csv", "", "is empty"),
    ("m.csv", "message_id,body\n", "no messages"),
    ("m.json", '[{"message_id": "J1", "body": }]', "not valid JSON"),
    ("m.json", '{"foo": 1}', "must contain a list"),
    ("m.txt", "hello", "Unsupported file type"),
])
def test_unusable_files_give_clear_errors(tmp_path, name, text, expected):
    with pytest.raises(InputError, match=expected):
        load_messages(write(tmp_path, name, text))


def test_missing_file(tmp_path):
    with pytest.raises(InputError, match="File not found"):
        load_messages(tmp_path / "nope.csv")


def test_non_utf8_file(tmp_path):
    p = tmp_path / "latin.csv"
    p.write_bytes("message_id,body\nL1,Caf\xe9\n".encode("latin-1"))
    with pytest.raises(InputError, match="not valid UTF-8"):
        load_messages(p)


def test_bad_rows_are_reported_and_good_rows_kept(tmp_path):
    p = write(tmp_path, "m.csv",
              "message_id,body\nOK1,Fine\n,No id\nOK1,Duplicate id\nE1,\nOK2,Also fine\n")
    res = load_messages(p)
    assert [m.message_id for m in res.messages] == ["OK1", "OK2"]
    errors = {e.row: e.error for e in res.errors}
    assert "Missing message_id" in errors[2]
    assert "Duplicate message_id" in errors[3]
    assert "empty" in errors[4]


def test_unquoted_comma_row_is_rejected(tmp_path):
    p = write(tmp_path, "m.csv", "message_id,body\nC1,Hello, world\n")
    res = load_messages(p)
    assert res.messages == []
    assert "more cells than the header" in res.errors[0].error


def test_warnings_for_bad_email_and_duplicate_text(tmp_path):
    p = write(tmp_path, "m.csv",
              "message_id,candidate_email,body\nW1,bad@,Any update?\nW2,ok@example.com,any   UPDATE?\n")
    first, second = load_messages(p).messages
    assert first.warnings == ["invalid_email"]
    assert second.warnings == ["duplicate_message"]


def test_sample_dataset_loads():
    from inbox_helper.config import ROOT
    res = load_messages(ROOT / "data" / "messages.csv")
    assert len(res.messages) == 48
    assert [e.message_id for e in res.errors] == ["M041"]  # the deliberately empty message
