"""Batch processing from the terminal."""
import argparse
import json
import sys
from pathlib import Path

from .exporters import export_csv, export_excel
from .records import process_document, to_json
from .schema import DOC_TYPES
from .validation import validate


def run(argv=None):
    p = argparse.ArgumentParser(description="Weissenberg - extract structured data from documents.")
    p.add_argument("files", nargs="+", help="PDF, image, DOCX or TXT files")
    p.add_argument("--out", default="output", help="output directory")
    p.add_argument("--type", default=None, choices=DOC_TYPES, help="force a document type")
    p.add_argument("--monthfirst", action="store_true", help="treat ambiguous dates as MM/DD")
    a = p.parse_args(argv)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for fn in a.files:
        try:
            records.append(process_document(Path(fn).name, Path(fn).read_bytes(), not a.monthfirst, a.type))
        except Exception as e:
            print(f"! {fn}: {e}", file=sys.stderr)
    for r in records:
        validate(r, records)
        (out / f"{Path(r['filename']).stem}.json").write_text(
            json.dumps(to_json(r), indent=2, ensure_ascii=False), encoding="utf-8")
        n_err = sum(i["level"] == "error" for i in r["issues"])
        n_warn = sum(i["level"] == "warning" for i in r["issues"])
        print(f"{r['filename']}: {r['doc_type']}, {len(r['fields'])} fields, {n_err} errors, {n_warn} warnings")
    if records:
        (out / "documents.csv").write_bytes(export_csv(records))
        (out / "line_items.csv").write_bytes(export_csv(records, "line_items"))
        (out / "documents.xlsx").write_bytes(export_excel(records))
        print(f"Wrote JSON, CSV and Excel files to {out}/")
