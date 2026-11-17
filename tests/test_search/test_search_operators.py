"""Search queries that mix boolean words with FTS5-special characters, and
glued alphanumeric terms that must match the word as written."""

from __future__ import annotations

import json
import sqlite3

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.search import fts
from hyperresearch.search.fts import SearchQueryError, preprocess_query, search_fts


@pytest.fixture
def query_vault(tmp_vault):
    from hyperresearch.core.note import write_note
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    notes = {
        "Vaccine Trials": "Covid-19 vaccines and booster efficacy. Contact by e-mail or phone.",
        "Ion Trap Gates": "Ion-trap gate fidelity under noise.",
        "Attention Paper": "Attention mechanisms in transformers.",
        "Interpreter Notes": "We ran the benchmarks under python3 and llama3 on an h264 stream.",
        "Model Roundup": "Mamba3 and GPT-4o vs llama3.1 on long context.",
        "Mamba Spaced": "The Mamba 3 release notes.",
    }
    for title, body in notes.items():
        write_note(tmp_vault.notes_dir, title, body=body)
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault, force=True))
    return tmp_vault


def _ids(vault, query):
    return {r["id"] for r in search_fts(vault.db, query)}


# --- Operators are uppercase only --------------------------------------------


@pytest.mark.parametrize("query", ["covid-19 and vaccines", "e-mail or phone", "covid-19 not vaccines"])
def test_lowercase_boolean_words_are_terms(query):
    """FTS5 operators are case-sensitive, so lowercase and/or/not are words.
    Treating them as operators used to hand the raw query to FTS5, which read
    the hyphenated word as a column filter ('no such column: 19')."""
    word = query.split()[1]
    assert f'"{word}"*' in preprocess_query(query)


@pytest.mark.parametrize("query", ["covid-19 and vaccines", "e-mail or phone"])
def test_natural_language_query_with_hyphen_matches(query_vault, query):
    assert "vaccine-trials" in _ids(query_vault, query)


def test_natural_language_query_with_hyphen_does_not_crash(query_vault):
    # 'and' is a required term here and this note has none, so no hit is right.
    assert _ids(query_vault, "ion-trap gate fidelity and noise") == set()
    assert "ion-trap-gates" in _ids(query_vault, "ion-trap gate fidelity noise")


# --- Operator mode still quotes terms FTS5 would misparse ---------------------


@pytest.mark.parametrize(("query", "expected"), [
    ("covid-19 AND vaccines", '"covid-19" AND vaccines'),
    ("title:vaccine OR e-mail", '"title:vaccine" OR "e-mail"'),
    ("llama3.1 AND ci/cd", '"llama3.1" AND "ci/cd"'),
    ("covid-19* AND vacc*", '"covid-19"* AND vacc*'),
    ("(covid-19 OR flu) AND vaccines", '( "covid-19" OR flu ) AND vaccines'),
])
def test_operator_query_quotes_special_terms(query, expected):
    assert preprocess_query(query) == expected


@pytest.mark.parametrize("query", [
    "covid-19 AND vaccines",
    "e-mail OR phone",
    "(covid-19 OR flu) AND booster",
    "vaccines NOT title:zzz",
])
def test_operator_query_with_special_terms_matches(query_vault, query):
    assert "vaccine-trials" in _ids(query_vault, query)


def test_operator_query_keeps_boolean_semantics(query_vault):
    assert _ids(query_vault, "attention NOT transformers") == set()
    assert "attention-paper" in _ids(query_vault, "zzzz OR attention")


def test_leading_near_group_is_an_operator(query_vault):
    """'NEAR(' at the start of the query was not detected (the check needed a
    leading space), so the group was stripped into plain words."""
    assert "attention-paper" in _ids(query_vault, "NEAR(attention transformers)")
    assert "attention-paper" in _ids(query_vault, "NEAR(attention transformers, 3)")


# --- Every FTS5 rejection is a SearchQueryError -------------------------------


@pytest.mark.parametrize("query", [
    "NEAR(attention transformers, x)",  # fts5: expected integer, got "x"
    "covid-19 AND (vaccines",           # fts5: syntax error
])
def test_fts5_rejection_is_a_search_query_error(query_vault, query):
    with pytest.raises(SearchQueryError, match="Invalid search query"):
        search_fts(query_vault.db, query)


def test_fts5_column_error_is_a_search_query_error(query_vault, monkeypatch):
    """'no such column' comes from FTS5 parsing the MATCH expression, not from
    a broken vault, so it must take the bad-query path."""
    monkeypatch.setattr(fts, "preprocess_query", lambda raw: raw)
    with pytest.raises(SearchQueryError, match="no such column: 19"):
        search_fts(query_vault.db, "covid-19 AND vaccines")


def test_broken_index_still_surfaces(query_vault):
    query_vault.db.execute("DROP TABLE IF EXISTS notes_fts")
    with pytest.raises(sqlite3.OperationalError, match="notes_fts"):
        search_fts(query_vault.db, "covid-19 AND vaccines")


# --- Glued alphanumeric terms -------------------------------------------------


@pytest.mark.parametrize(("query", "expected"), [
    ("python3", "interpreter-notes"),
    ("llama3", "interpreter-notes"),
    ("h264", "interpreter-notes"),
    ("python3 h264", "interpreter-notes"),
    ("llama3.1", "model-roundup"),
    ("mamba3", "model-roundup"),
])
def test_glued_alphanumeric_matches_word_as_written(query_vault, query, expected):
    """unicode61 indexes 'python3' as one token, so splitting it into
    'python' + '3' alone could never match the verbatim word."""
    assert expected in _ids(query_vault, query)


def test_glued_alphanumeric_still_matches_spaced_form(query_vault):
    ids = _ids(query_vault, "mamba3")
    assert {"model-roundup", "mamba-spaced"} <= ids


# --- Plain-mode words that yield no token -------------------------------------


@pytest.mark.parametrize(("query", "expected"), [
    ("attention - transformers", "attention-paper"),
    ("attention & transformers", "attention-paper"),
    ("attention \u2013 transformers", "attention-paper"),  # en dash
    ("python3 , h264", "interpreter-notes"),
    ('attention "-" transformers', "attention-paper"),
])
def test_tokenless_word_does_not_empty_plain_query(query_vault, query, expected):
    """A word with no letters or digits is an empty phrase to FTS5. Implicit
    AND ignores an empty phrase, but the explicit AND that the glued-term group
    needs makes it match nothing, so 'rock & roll' found no notes."""
    assert expected in _ids(query_vault, query)


@pytest.mark.parametrize("query", ["-", "& ,", '"-"'])
def test_query_of_only_tokenless_words_has_no_searchable_terms(query_vault, query):
    with pytest.raises(SearchQueryError, match="no searchable terms"):
        search_fts(query_vault.db, query)


# --- Callers: CLI and MCP -----------------------------------------------------


def test_cli_lowercase_and_with_hyphen_returns_json(query_vault, monkeypatch):
    monkeypatch.chdir(query_vault.root)
    result = CliRunner().invoke(app, ["search", "covid-19 and vaccines", "-j", "--no-body"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert "vaccine-trials" in {r["id"] for r in data["data"]["results"]}


def test_cli_fts5_rejection_is_bad_query_json(query_vault, monkeypatch):
    monkeypatch.chdir(query_vault.root)
    result = CliRunner().invoke(app, ["search", "NEAR(attention transformers, x)", "-j"])
    assert result.exit_code == 2, result.output
    data = json.loads(result.stdout)
    assert data["ok"] is False
    assert data["error_code"] == "BAD_QUERY"


def test_mcp_search_notes_handles_operator_words(query_vault, monkeypatch):
    mcp = pytest.importorskip("hyperresearch.mcp.server")
    monkeypatch.setattr(mcp, "_vault", query_vault)
    rows = json.loads(mcp.search_notes("covid-19 and vaccines"))
    assert "vaccine-trials" in {r["id"] for r in rows}
    assert mcp.search_notes("NEAR(attention transformers, x)").startswith("Invalid search query")
