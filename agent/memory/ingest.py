"""Estrazione testo da file locali per l'ingestion (Fase 2)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

TEXT_EXTENSIONS = frozenset(
    {".txt", ".md", ".py", ".js", ".ts", ".json", ".csv", ".log", ".yml", ".yaml", ".toml"}
)
PDF_EXTENSIONS = frozenset({".pdf"})

_SKIP_DIRS = frozenset(
    {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"}
)


class UnsupportedFormatError(ValueError):
    """Estensione non gestita dalla pipeline di ingestion."""


def supported_extensions() -> frozenset[str]:
    """Estensioni che la pipeline sa processare (inclusi i PDF, in Fase 2)."""
    return TEXT_EXTENSIONS | PDF_EXTENSIONS


def extract_text(path: str | Path) -> str:
    """Estrae il testo da un file. UTF-8 con sostituzione dei caratteri invalidi."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        return p.read_text(encoding="utf-8", errors="replace")
    if suffix in PDF_EXTENSIONS:
        raise NotImplementedError(
            f"PDF non ancora supportato ({p.name}): installare pypdf e implementare "
            "l'estrazione in Fase 2."
        )
    raise UnsupportedFormatError(
        f"formato non supportato: {suffix or '(senza estensione)'} ({p.name})"
    )


def iter_source_files(root: str | Path) -> list[Path]:
    """Ricorsione sui file candidati all'ingestion (salta cartelle di cache/tooling)."""
    base = Path(root)
    if base.is_file():
        return [base]
    found: list[Path] = []
    stack: list[Path] = [base]
    while stack:
        current = stack.pop()
        for entry in sorted(current.iterdir()):
            if entry.is_dir():
                if entry.name not in _SKIP_DIRS:
                    stack.append(entry)
            elif entry.is_file():
                found.append(entry)
    return found


def iter_supported(root: str | Path) -> Iterator[Path]:
    """Filtra `iter_source_files` sulle estensioni supportate."""
    for path in iter_source_files(root):
        if path.suffix.lower() in supported_extensions():
            yield path
