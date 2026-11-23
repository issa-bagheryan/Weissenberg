"""Tiny persistent store: originals + state.json live in a local data folder."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from .records import apply_field_edits, apply_item_edits, process_document, re_extract
from .validation import validate


class Store:
    def __init__(self, data_dir="data"):
        self.dir = Path(data_dir)
        (self.dir / "files").mkdir(parents=True, exist_ok=True)
        self.state = self.dir / "state.json"
        self.lock = threading.RLock()
        self.records: dict[str, dict] = {}
        if self.state.exists():
            try:
                self.records = {r["id"]: r for r in json.loads(self.state.read_text("utf-8"))}
            except (ValueError, KeyError):
                self.records = {}
        self.revalidate()

    # -- persistence ------------------------------------------------------
    def save(self):
        tmp = self.state.with_suffix(".tmp")
        tmp.write_text(json.dumps(list(self.records.values()), ensure_ascii=False), "utf-8")
        tmp.replace(self.state)

    def revalidate(self):
        recs = list(self.records.values())
        for r in recs:
            validate(r, recs)

    def file_path(self, rid):
        rec = self.records.get(rid)
        if not rec:
            return None
        p = self.dir / "files" / f"{rid}{Path(rec['filename']).suffix.lower()}"
        return p if p.exists() else None

    # -- operations ---------------------------------------------------------
    def add(self, filename, data, dayfirst=True, force_type=None):
        rec = process_document(filename, data, dayfirst, force_type)        # slow part, no lock
        with self.lock:
            if rec["id"] in self.records:
                return self.records[rec["id"]], True
            (self.dir / "files" / f"{rec['id']}{Path(filename).suffix.lower()}").write_bytes(data)
            self.records[rec["id"]] = rec
            self.revalidate()
            self.save()
            return rec, False

    def update(self, rid, payload):
        with self.lock:
            rec = self.records[rid]
            if "doc_type" in payload and payload["doc_type"] != rec["doc_type"]:
                re_extract(rec, payload["doc_type"])
            if "fields" in payload:
                apply_field_edits(rec, payload["fields"])
            if "line_items" in payload:
                apply_item_edits(rec, payload["line_items"])
            if "verified" in payload:
                rec["verified"] = bool(payload["verified"])
            self.revalidate()
            self.save()
            return rec

    def delete(self, rid):
        with self.lock:
            f = self.file_path(rid)
            if f:
                f.unlink()
            self.records.pop(rid, None)
            self.revalidate()
            self.save()

    def clear(self):
        with self.lock:
            for rid in list(self.records):
                self.delete(rid)

    def all(self, verified_only=False):
        with self.lock:
            return [r for r in self.records.values() if r["verified"] or not verified_only]
