"""Test 1.6.5: UTF-8 forzato sugli std stream (Windows, pipe, non-TTY)."""

from __future__ import annotations

import io
import os
import sys

from agent.cli import force_utf8_stdio


def test_forza_utf8_riconfigura_e_stampa_utf8(monkeypatch) -> None:
    """Uno stream cp1252 (caso pipe/redirect) diventa utf-8 e scrive i byte giusti."""
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    buf = io.BytesIO()
    stream = io.TextIOWrapper(buf, encoding="cp1252", newline="")
    monkeypatch.setattr(sys, "stdout", stream)

    force_utf8_stdio()

    assert stream.encoding == "utf-8"
    stream.write("caff\u00e0 \u2713")
    stream.flush()
    assert buf.getvalue() == "caff\u00e0 \u2713".encode("utf-8")
    stream.detach()  # isola il buffer: il GC non deve chiudere BytesIO


def test_forza_utf8_non_cade_su_stream_senza_reconfigure(monkeypatch) -> None:
    """Stream catturati (pytest), binari o chiusi: nessuna eccezione, nessun crash."""

    class _NessunReconfigure:
        def reconfigure(self, **kwargs: object) -> None:
            raise io.UnsupportedOperation("non supportato")

    monkeypatch.setattr(sys, "stdout", _NessunReconfigure())
    monkeypatch.setattr(sys, "stderr", _NessunReconfigure())
    monkeypatch.setattr(sys, "stdin", _NessunReconfigure())

    force_utf8_stdio()  # non deve alzare


def test_forza_utf8_imposta_pythonutf8_per_i_figli(monkeypatch) -> None:
    monkeypatch.delenv("PYTHONUTF8", raising=False)

    force_utf8_stdio()

    assert os.environ.get("PYTHONUTF8") == "1", "ereditato dai processi figli"
