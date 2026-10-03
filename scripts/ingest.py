#!/usr/bin/env python
"""Pipeline di ingestion (scaffold Fase 2): analizza i file, non indicizza ancora."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent.memory.ingest import UnsupportedFormatError, extract_text, iter_source_files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingestion documenti per la memoria RAG (Fase 2 — scaffold)"
    )
    parser.add_argument("--path", required=True, help="Cartella o file da analizzare")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo analisi: stampa il piano di ingestion senza indicizzare",
    )
    args = parser.parse_args(argv)

    root = Path(args.path).expanduser().resolve()
    if not root.exists():
        print(f"ERRORE: percorso inesistente: {root}", file=sys.stderr)
        return 2

    files = iter_source_files(root)
    extractable = 0
    skipped = 0
    total_chars = 0
    pending: list[tuple[Path, int]] = []
    for file_path in files:
        try:
            text = extract_text(file_path)
        except NotImplementedError:
            skipped += 1
            print(f"  [PDF, non processato] {file_path.name}")
        except (UnsupportedFormatError, OSError):
            skipped += 1
        else:
            extractable += 1
            total_chars += len(text)
            pending.append((file_path, len(text)))

    print(f"Piano di ingestion per: {root}")
    print(f"  file trovati:      {len(files)}")
    print(f"  estraibili:        {extractable} ({total_chars} caratteri)")
    print(f"  saltati:           {skipped}")
    if args.dry_run:
        print("Dry-run: nessuna indicizzazione eseguita (come richiesto).")
        return 0
    print(
        "Indicizzazione non ancora implementata (Fase 2): completare agent/memory/store.py "
        "e i embeddings, oppure usare --dry-run."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
