"""Exercise the real viewer with idle browser preconnections and concurrent clients."""

import json
import multiprocessing
import os
import signal
import socket
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler
from socketserver import TCPServer
from threading import Lock

import pytest

from hyperresearch.core.vault import Vault
from hyperresearch.serve.server import HyperresearchHandler, run_server


def _serve(vault_path, events, timeout):
    """Report the OS-selected port and accepted sockets without replacing request handling."""
    activate = TCPServer.server_activate
    setup = HyperresearchHandler.setup
    event_lock = Lock()

    def report_address(server):
        activate(server)
        events.send(("ready", server.server_address))

    def report_client(handler):
        setup(handler)
        with event_lock:
            events.send(("accepted", handler.client_address))

    TCPServer.server_activate = report_address
    HyperresearchHandler.setup = report_client
    if timeout is not None and HyperresearchHandler.timeout is not None:
        HyperresearchHandler.timeout = min(timeout, HyperresearchHandler.timeout)
    run_server(Vault(vault_path), port=0)


def _wait_for(events, kind):
    while True:
        assert events.poll(5), f"server did not report {kind}"
        event, value = events.recv()
        if event == kind:
            return value


@contextmanager
def _running_server(vault, *, timeout=None):
    context = multiprocessing.get_context("spawn")
    events, sender = context.Pipe(duplex=False)
    process = context.Process(target=_serve, args=(vault.root, sender, timeout))
    process.start()
    sender.close()
    try:
        address = _wait_for(events, "ready")
        yield address, process, events
    finally:
        if process.is_alive():
            process.terminate()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join(5)
        events.close()


def _get(address, path):
    client = HTTPConnection(*address, timeout=2)
    try:
        client.request("GET", path)
        response = client.getresponse()
        return response.status, response.read()
    finally:
        client.close()


def test_idle_preconnection_does_not_block_pages_or_graph(seeded_vault):
    with (
        _running_server(seeded_vault) as (address, _process, events),
        socket.create_connection(address, timeout=2),
    ):
        _wait_for(events, "accepted")
        status, body = _get(address, "/")
        assert status == 200
        assert b"Python Async Patterns" in body
        status, body = _get(address, "/api/graph")
        assert status == 200
        assert any(node["title"] == "Python Async Patterns" for node in json.loads(body)["nodes"])


def test_concurrent_pages_and_searches_render_from_vault(seeded_vault):
    paths = ["/", "/search?q=Python", "/api/graph", "/note/python-async-patterns"] * 3
    with (
        _running_server(seeded_vault) as (address, _process, _events),
        ThreadPoolExecutor(max_workers=4) as clients,
    ):
        results = list(clients.map(lambda path: _get(address, path), paths))
    for status, body in results:
        assert status == 200
        assert b"Python Async Patterns" in body


def test_idle_connection_is_closed_after_read_timeout(seeded_vault):
    with (
        _running_server(seeded_vault, timeout=0.1) as (address, _process, events),
        socket.create_connection(address, timeout=2) as idle,
    ):
        _wait_for(events, "accepted")
        assert idle.recv(1) == b""


@pytest.mark.skipif(sys.platform == "win32", reason="os.kill(SIGINT) requires POSIX signal delivery")
def test_shutdown_does_not_wait_for_idle_preconnection(seeded_vault):
    with (
        _running_server(seeded_vault) as (address, process, events),
        socket.create_connection(address, timeout=2),
    ):
        _wait_for(events, "accepted")
        os.kill(process.pid, signal.SIGINT)
        process.join(3)
        assert process.exitcode == 0


def test_handlers_own_and_close_their_database_connections(seeded_vault, monkeypatch):
    monkeypatch.setattr(HyperresearchHandler, "vault", seeded_vault)
    monkeypatch.setattr(HyperresearchHandler, "_db", None)
    # No sockets are needed to check ownership; socket cleanup belongs to the base handler.
    monkeypatch.setattr(BaseHTTPRequestHandler, "finish", lambda self: None)
    first = object.__new__(HyperresearchHandler)
    second = object.__new__(HyperresearchHandler)
    first_db, second_db = first.db, second.db
    try:
        assert first_db is not second_db
        first.finish()
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            first_db.execute("SELECT 1")
        assert second_db.execute("SELECT 1").fetchone()[0] == 1
        second.finish()
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            second_db.execute("SELECT 1")
    finally:
        first_db.close()
        second_db.close()
