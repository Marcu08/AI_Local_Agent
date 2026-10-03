"""Test dello scaffold Fase 2: ingestion, vector store lazy, search_memory."""

from __future__ import annotations

import builtins
import subprocess
import sys
from pathlib import Path

import pytest

from agent.memory.ingest import (
    UnsupportedFormatError,
    extract_text,
    iter_source_files,
)
from agent.memory.retrieval import search
from agent.memory.store import VectorStore, VectorStoreUnavailableError
from agent.tools import create_default_registry
from agent.tools.base import ToolContext

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# --- ingest -----------------------------------------------------------------

def test_extract_md(tmp_path: Path) -> None:
    file = tmp_path / "appunti.md"
    file.write_text("# Titolo\ncontenuto", encoding="utf-8")
    assert extract_text(file) == "# Titolo\ncontenuto"


def test_extract_py(tmp_path: Path) -> None:
    file = tmp_path / "modulo.py"
    file.write_text("def f():\n    return 1\n", encoding="utf-8")
    assert "def f()" in extract_text(file)


def test_extract_pdf_stub(tmp_path: Path) -> None:
    file = tmp_path / "tesi.pdf"
    file.write_bytes(b"%PDF-1.4 fake")
    with pytest.raises(NotImplementedError, match="pypdf"):
        extract_text(file)


def test_extract_formato_sconosciuto(tmp_path: Path) -> None:
    file = tmp_path / "immagine.bin"
    file.write_bytes(b"\x00\x01")
    with pytest.raises(UnsupportedFormatError):
        extract_text(file)


def test_iter_source_files_salta_cache(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "main.cpython-314.pyc").write_bytes(b"\x00")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref", encoding="utf-8")
    (tmp_path / "readme.md").write_text("# x", encoding="utf-8")

    names = {p.name for p in iter_source_files(tmp_path)}
    assert names == {"main.py", "readme.md"}


# --- retrieval / store ------------------------------------------------------

def test_search_stub_vuoto() -> None:
    assert search("come avevo fatto l'OCR?") == []
    assert search("   ") == []


def test_vector_store_senza_chromadb(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Anche se chromadb fosse installato, il test blocca l'import: errore chiaro."""
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):  # noqa: ANN001
        if name == "chromadb":
            raise ImportError("chromadb bloccato per il test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    store = VectorStore(tmp_path / "vs")
    with pytest.raises(VectorStoreUnavailableError, match="chromadb non installato"):
        store.add(ids=["1"], documents=["x"])


def test_vector_store_chunks() -> None:
    chunks = VectorStore.chunks("a" * 2500, size=1000, overlap=100)
    # 0-1000, 900-1900, 1800-2500: l'ultimo chunk è il rimanente
    assert [len(c) for c in chunks] == [1000, 1000, 700]
    assert VectorStore.chunks("") == []
    with pytest.raises(ValueError):
        VectorStore.chunks("x", size=10, overlap=20)


# --- tool search_memory -----------------------------------------------------

def test_search_memory_non_implementato(config, allow_confirm) -> None:
    registry = create_default_registry()
    ctx = ToolContext(config=config, confirm=allow_confirm)
    result = registry.dispatch("search_memory", {"query": "OCR progetto X"}, ctx)
    assert result.ok
    output = result.output or ""
    assert "non ancora implementata" in output
    assert "OCR progetto X" in output


def test_search_memory_query_mancante(config, allow_confirm) -> None:
    registry = create_default_registry()
    ctx = ToolContext(config=config, confirm=allow_confirm)
    result = registry.dispatch("search_memory", {}, ctx)
    assert not result.ok
    assert "query" in (result.error or "")


def test_search_memory_registrato() -> None:
    assert "search_memory" in create_default_registry().names()


# --- scripts/ingest.py ------------------------------------------------------

def test_ingest_dry_run(tmp_path: Path) -> None:
    (tmp_path / "nota.md").write_text("# nota", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.ingest", "--path", str(tmp_path), "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        cwd=str(_PROJECT_ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    assert "Piano di ingestion" in proc.stdout
    assert "estraibili:        1" in proc.stdout
    assert "Dry-run" in proc.stdout


def test_ingest_senza_dry_run_non_implementato(tmp_path: Path) -> None:
    (tmp_path / "nota.md").write_text("# nota", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.ingest", "--path", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        cwd=str(_PROJECT_ROOT),
    )
    assert proc.returncode == 1
    assert "non ancora implementata" in proc.stdout


def test_ingest_path_assente(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.ingest", "--path", str(tmp_path / "nope"), "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        cwd=str(_PROJECT_ROOT),
    )
    assert proc.returncode == 2
