"""Handle/email detection shared by the upload page and create_batch_enrichment."""

import io

import pytest

from influencers_club_mcp import upload_server
from influencers_club_mcp.csv_import import count_csv_rows, mostly_emails, to_single_column


# ─── Several columns ───────────────────────────────────────────────────

def test_a_named_column_wins():
    rows = ["name,Email,handle", "Ann,a@x.com,@ann"]
    assert to_single_column(rows) == (["email", "a@x.com"], "email", 1)


def test_unnamed_columns_pick_the_one_with_most_emails():
    rows = ["a,b,c", "a@x.com,b@x.com,nope", "nope,c@x.com,d@x.com", "e@x.com,f@x.com,g@x.com"]
    assert to_single_column(rows) == (["email", "b@x.com", "c@x.com", "f@x.com"], "email", 1)


def test_without_emails_the_first_column_is_handles():
    rows = ["who,notes", "@ann,hi", "@bob,"]
    assert to_single_column(rows) == (["handle", "@ann", "@bob"], "handle", 0)


def test_values_are_read_as_csv():
    rows = ["handle,note", '"@ann","hi, there"', ",x", '"@bob",y']
    assert to_single_column(rows)[0] == ["handle", "@ann", "@bob"]


# ─── One column ────────────────────────────────────────────────────────

@pytest.mark.parametrize("header", ["email", "Emails", '"handle"', "HANDLES"])
def test_a_named_single_column_is_left_alone(header):
    assert to_single_column([header, "@ann"]) is None


def test_an_unnamed_first_line_is_replaced_by_the_header():
    rows = ["username", "@ann", "@bob"]
    assert to_single_column(rows) == (["handle", "@ann", "@bob"], "handle", None)


def test_type_follows_the_first_five_values():
    rows = ["list", "@a", "@b", "c@x.com", "d@x.com", "e@x.com", "@f", "@g"]
    assert to_single_column(rows)[1] == "email"


def test_quote_only_values_are_ignored_when_guessing():
    rows = ["list", "''", '""', "a@x.com"]
    assert to_single_column(rows) == (["email", "''", '""', "a@x.com"], "email", None)


def test_no_values_to_guess_from_is_an_error():
    with pytest.raises(ValueError, match="CSV has no data rows"):
        to_single_column(["list", '""', "''"])


# ─── Helpers ───────────────────────────────────────────────────────────

def test_mostly_emails_needs_more_than_half():
    assert mostly_emails(["a@x.com", "b@x.com", "@c"])
    assert not mostly_emails(["a@x.com", "@c"])
    assert not mostly_emails(["user@localhost"])
    assert not mostly_emails(["@john.doe", "tiktok.com/@jane.doe"])
    assert not mostly_emails([])


@pytest.mark.parametrize("text, rows", [
    ("", 0),
    ("email", 0),
    ("email\na@x.com\n\n  \nb@x.com\n", 2),
    ("email\r\na@x.com\r\nb@x.com\r\n", 2),
])
def test_count_csv_rows(text, rows):
    assert count_csv_rows(text) == rows


# ─── Callers ───────────────────────────────────────────────────────────

class _Upload(upload_server.UploadHandler):
    """The upload handler without a socket: request body in, JSON reply captured."""

    def __init__(self, body: bytes):
        self.headers = {"Content-Length": str(len(body)), "X-Filename": "list.csv"}
        self.rfile = io.BytesIO(body)

    def _send_json(self, code, data):
        self.reply = (code, data)


def test_upload_page_takes_the_first_line_as_the_header(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_server, "IMPORTS_DIR", str(tmp_path))
    handler = _Upload(b"username\nann\nbob\n")
    handler._handle_upload()
    code, reply = handler.reply
    assert (code, reply["rows"], reply["detected_type"]) == (200, 2, "handle")
    assert (tmp_path / "list.csv").read_bytes() == b"handle\nann\nbob"
