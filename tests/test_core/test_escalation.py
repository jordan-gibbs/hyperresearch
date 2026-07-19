"""Phase-4 tests: escalation queue, fetch-gate enqueue, chrome policy, ingest."""

from __future__ import annotations

import json

import pytest

from hyperresearch.core.escalation import (
    EscalationError,
    claim_next,
    enqueue,
    list_items,
    maybe_enqueue_blocked_fetch,
    queue_stats,
    resolve,
)


class TestQueueBasics:
    def test_enqueue_and_list(self, tmp_vault):
        conn = tmp_vault.db
        item_id = enqueue(conn, "https://x.com/a", "login_wall", vault_tag="run-1", utility_score=14)
        assert item_id is not None
        items = list_items(conn, vault_tag="run-1")
        assert len(items) == 1
        assert items[0]["status"] == "queued"
        assert items[0]["reason"] == "login_wall"

    def test_duplicate_enqueue_is_idempotent(self, tmp_vault):
        conn = tmp_vault.db
        first = enqueue(conn, "https://x.com/a", "login_wall", vault_tag="run-1")
        second = enqueue(conn, "https://x.com/a", "bot_block", vault_tag="run-1")
        assert first is not None and second is None
        assert len(list_items(conn)) == 1

    def test_same_url_different_runs_both_queue(self, tmp_vault):
        conn = tmp_vault.db
        assert enqueue(conn, "https://x.com/a", "login_wall", vault_tag="run-1")
        assert enqueue(conn, "https://x.com/a", "login_wall", vault_tag="run-2")

    def test_invalid_reason_rejected(self, tmp_vault):
        with pytest.raises(EscalationError, match="invalid reason"):
            enqueue(tmp_vault.db, "https://x.com", "paywall")


class TestClaimSemantics:
    def test_claim_takes_highest_utility_first(self, tmp_vault):
        conn = tmp_vault.db
        enqueue(conn, "https://low.com", "bot_block", utility_score=5)
        enqueue(conn, "https://high.com", "bot_block", utility_score=17)
        enqueue(conn, "https://unscored.com", "bot_block")
        item = claim_next(conn, "tester")
        assert item["url"] == "https://high.com"
        assert item["status"] == "in_progress"
        assert item["claimed_by"] == "tester"
        assert item["attempts"] == 1

    def test_claims_never_hand_out_same_item(self, tmp_vault):
        conn = tmp_vault.db
        enqueue(conn, "https://only.com", "bot_block")
        a = claim_next(conn, "a")
        b = claim_next(conn, "b")
        assert a is not None
        assert b is None  # queue exhausted, not double-claimed

    def test_claim_scoped_by_tag(self, tmp_vault):
        conn = tmp_vault.db
        enqueue(conn, "https://other.com", "bot_block", vault_tag="other-run")
        assert claim_next(conn, "t", vault_tag="my-run") is None

    def test_lifecycle_to_needs_human_and_retry(self, tmp_vault):
        conn = tmp_vault.db
        item_id = enqueue(conn, "https://x.com/c", "captcha")
        claim_next(conn, "t")
        item = resolve(conn, item_id, "needs_human", detail="solve CAPTCHA on x.com")
        assert item["status"] == "needs_human"
        assert queue_stats(conn)["needs_human"] == 1
        # human done -> retry
        item = resolve(conn, item_id, "queued")
        assert item["status"] == "queued"
        assert claim_next(conn, "t")["id"] == item_id


class TestChromePolicy:
    def test_low_utility_declined(self, tmp_vault):
        assert maybe_enqueue_blocked_fetch(tmp_vault, "https://x.com", "bot_block", utility_score=3.0) is None
        assert maybe_enqueue_blocked_fetch(tmp_vault, "https://x.com", "bot_block", utility_score=9.0) is not None

    def test_unscored_urls_pass(self, tmp_vault):
        assert maybe_enqueue_blocked_fetch(tmp_vault, "https://y.com", "login_wall") is not None

    def test_disabled_lane_declines(self, tmp_vault):
        cfg = tmp_vault.config_path
        cfg.write_text(cfg.read_text(encoding="utf-8").replace(
            "[chrome]\nenabled = true", "[chrome]\nenabled = false"
        ), encoding="utf-8")
        vault = type(tmp_vault).discover(tmp_vault.root)
        assert vault.config.chrome.enabled is False
        assert maybe_enqueue_blocked_fetch(vault, "https://z.com", "login_wall") is None

    def test_per_run_cap(self, tmp_vault):
        cfg = tmp_vault.config_path
        cfg.write_text(cfg.read_text(encoding="utf-8").replace(
            "max_items_per_run = 25", "max_items_per_run = 2"
        ), encoding="utf-8")
        vault = type(tmp_vault).discover(tmp_vault.root)
        assert maybe_enqueue_blocked_fetch(vault, "https://a.com", "login_wall", vault_tag="capped") is not None
        assert maybe_enqueue_blocked_fetch(vault, "https://b.com", "login_wall", vault_tag="capped") is not None
        assert maybe_enqueue_blocked_fetch(vault, "https://c.com", "login_wall", vault_tag="capped") is None


class TestFetchGateIntegration:
    def test_login_wall_fetch_escalates(self, tmp_vault, monkeypatch):
        """A CLI fetch that hits a login wall queues the URL instead of just dying."""
        from typer.testing import CliRunner

        import hyperresearch.cli.fetch as fetch_mod
        from hyperresearch.cli import app
        from hyperresearch.web.base import WebResult

        class WallProvider:
            name = "stub"

            def fetch(self, url):
                return WebResult(url=url, title="Sign in to continue", content="Please log in.")

        monkeypatch.setattr(fetch_mod, "get_provider", lambda *a, **k: WallProvider(), raising=False)
        # cli.fetch imports get_provider inside the function from web.base
        import hyperresearch.web.base as base_mod

        monkeypatch.setattr(base_mod, "get_provider", lambda *a, **k: WallProvider())

        monkeypatch.chdir(tmp_vault.root)
        runner = CliRunner()
        r = runner.invoke(app, ["fetch", "https://walled.example.com/article",
                                "--tag", "esc-run", "--utility-score", "15", "--json"])
        assert r.exit_code == 1
        payload = json.loads(r.stdout)
        assert payload["error_code"] == "AUTH_REQUIRED_ESCALATED"

        items = list_items(tmp_vault.db, vault_tag="esc-run")
        assert len(items) == 1
        assert items[0]["url"] == "https://walled.example.com/article"
        assert items[0]["reason"] == "login_wall"
        assert items[0]["utility_score"] == 15.0


class TestEscalationCli:
    def test_add_claim_ingest_roundtrip(self, tmp_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        monkeypatch.chdir(tmp_vault.root)
        runner = CliRunner()

        r = runner.invoke(app, ["escalation", "add", "https://gated.example.com/paper",
                                "--reason", "interactive_needed", "--tag", "cli-esc",
                                "--utility", "12", "--json"])
        assert r.exit_code == 0
        item_id = json.loads(r.stdout)["data"]["id"]

        r = runner.invoke(app, ["escalation", "claim", "--tag", "cli-esc", "--json"])
        assert r.exit_code == 0
        assert json.loads(r.stdout)["data"]["item"]["id"] == item_id

        body = tmp_vault.root / "scratch-body.md"
        body.write_text("Extracted page content with plenty of real words in it.", encoding="utf-8")
        r = runner.invoke(app, ["escalation", "ingest", str(item_id),
                                "--title", "Gated Paper", "--body-file", str(body), "--json"])
        assert r.exit_code == 0
        data = json.loads(r.stdout)["data"]
        note_id = data["note_id"]

        # Note exists with chrome provenance + vault_tag tag; source row recorded
        row = tmp_vault.db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        assert row is not None
        src = tmp_vault.db.execute(
            "SELECT provider, note_id FROM sources WHERE url = 'https://gated.example.com/paper'"
        ).fetchone()
        assert src["provider"] == "chrome"
        assert src["note_id"] == note_id
        tags = {t["tag"] for t in tmp_vault.db.execute("SELECT tag FROM tags WHERE note_id = ?", (note_id,))}
        assert "cli-esc" in tags
        note_text = (tmp_vault.root / data["path"]).read_text(encoding="utf-8")
        assert "fetch_provider: chrome" in note_text

        # Item resolved
        assert list_items(tmp_vault.db, vault_tag="cli-esc")[0]["status"] == "fetched"

    def test_human_flow_cli(self, tmp_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        monkeypatch.chdir(tmp_vault.root)
        runner = CliRunner()
        runner.invoke(app, ["escalation", "add", "https://c.example.com", "--reason", "captcha", "--json"])
        r = runner.invoke(app, ["escalation", "claim", "--json"])
        item_id = json.loads(r.stdout)["data"]["item"]["id"]

        r = runner.invoke(app, ["escalation", "human", str(item_id),
                                "--detail", "solve CAPTCHA on c.example.com", "--json"])
        assert r.exit_code == 0
        r = runner.invoke(app, ["escalation", "retry", str(item_id), "--json"])
        assert r.exit_code == 0
        assert json.loads(r.stdout)["data"]["status"] == "queued"


class TestRunStatusIntegration:
    def test_run_status_shows_queue_depth(self, tmp_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app
        from hyperresearch.core.runs import init_run

        init_run(tmp_vault, "esc-status-01")
        enqueue(tmp_vault.db, "https://q.example.com", "login_wall", vault_tag="esc-status-01")
        item_id = enqueue(tmp_vault.db, "https://h.example.com", "captcha", vault_tag="esc-status-01")
        resolve(tmp_vault.db, item_id, "needs_human", detail="x")

        monkeypatch.chdir(tmp_vault.root)
        runner = CliRunner()
        r = runner.invoke(app, ["run", "status", "esc-status-01", "--json"])
        assert r.exit_code == 0
        esc = json.loads(r.stdout)["data"]["escalations"]
        assert esc["queued"] == 1
        assert esc["needs_human"] == 1


class TestBrowserFetcherAgent:
    def test_agent_installs_with_boundary(self, tmp_vault):
        from hyperresearch.core.hooks import _install_browser_fetcher_agent

        result = _install_browser_fetcher_agent(tmp_vault.root, "hyperresearch")
        assert result is not None
        body = (tmp_vault.root / ".claude" / "agents" / "hyperresearch-browser-fetcher.md").read_text(encoding="utf-8")
        assert "name: hyperresearch-browser-fetcher" in body
        assert "model: sonnet" in body
        assert "NEVER" in body and "CAPTCHA" in body
        assert "escalation human" in body
        assert "escalation ingest" in body
        assert "scholar.google.com" in body
        assert "<<" not in body  # fully rendered
