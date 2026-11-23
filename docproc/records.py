"""Document records: build, edit, serialise."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .extractors import EXTRACTORS, classify
from .parsing import detect_currencies, parse_amount
from .reader import extract_text
from .schema import DOC_TYPES, REQUIRED
from .validation import normalize_value, validate

def _build_fields(doc_type, text, dayfirst):
    raw, items = EXTRACTORS[doc_type](text, dayfirst)
    fields = {}
    for name, meta in raw.items():
        fields[name] = {
            "value": normalize_value(name, meta["value"], dayfirst),
            "confidence": meta["confidence"], "source": meta.get("source", ""),
            "corrected": False,
        }
    for name in REQUIRED[doc_type]:                    # blank rows so users can fill them in
        fields.setdefault(name, {"value": "", "confidence": 0.0, "source": "", "corrected": False})
    return fields, items


def process_document(filename, data, dayfirst=True, force_type=None):
    text, method = extract_text(filename, data)
    if force_type and force_type != "Auto-detect":
        doc_type, type_conf = force_type, 1.0
    else:
        doc_type, type_conf = classify(text)
    fields, items = _build_fields(doc_type, text, dayfirst)
    rec = {
        "id": hashlib.md5(data).hexdigest()[:10],
        "filename": filename,
        "doc_type": doc_type,
        "type_confidence": type_conf,
        "method": method,
        "raw_text": text,
        "fields": fields,
        "line_items": items,
        "issues": [],
        "verified": False,
        "_currencies": dict(detect_currencies(text)),
        "_dayfirst": dayfirst,
    }
    rec["_base_fields"] = {k: dict(v) for k, v in fields.items()}
    rec["_base_items"] = [dict(i) for i in items]
    validate(rec)
    return rec


def re_extract(rec, doc_type):
    """Re-run extraction on stored text with a different document type."""
    rec["doc_type"] = doc_type
    fields, items = _build_fields(doc_type, rec["raw_text"], rec.get("_dayfirst", True))
    rec["fields"], rec["line_items"] = fields, items
    rec["_base_fields"] = {k: dict(v) for k, v in fields.items()}
    rec["_base_items"] = [dict(i) for i in items]
    rec["verified"] = False
    validate(rec)


def apply_field_edits(rec, rows):
    """rows: list of {'field','value'} dicts from the editor. Rebuilds rec['fields']."""
    base = rec["_base_fields"]
    out = {}
    for r in rows:
        name = str(r.get("field") or "").strip().lower().replace(" ", "_")
        if not name:
            continue
        v = r.get("value")
        v = "" if v is None or (isinstance(v, float) and v != v) else str(v)
        v = normalize_value(name, v, rec.get("_dayfirst", True))
        b = base.get(name)
        out[name] = {
            "value": v,
            "confidence": b["confidence"] if b else 1.0,
            "source": b["source"] if b else "added by user",
            "corrected": (v != b["value"]) if b else True,
        }
    rec["fields"] = out


def apply_item_edits(rec, rows):
    items = []
    for r in rows:
        desc = r.get("description")
        if desc is None or (isinstance(desc, float) and desc != desc):
            desc = ""
        item = {"description": str(desc).strip()}
        for k in ("quantity", "unit_price", "amount"):
            x = r.get(k)
            item[k] = None if x is None or (isinstance(x, float) and x != x) else (
                x if isinstance(x, (int, float)) else parse_amount(x))
        if item["description"] or item["amount"] is not None:
            items.append(item)
    rec["line_items"] = items


def to_json(rec, include_meta=True):
    out = {
        "filename": rec["filename"],
        "document_type": rec["doc_type"],
        "fields": {k: v["value"] for k, v in rec["fields"].items() if v["value"] != ""},
        "line_items": rec["line_items"],
        "issues": rec["issues"],
        "verified": rec["verified"],
    }
    if include_meta:
        out["confidence"] = {k: v["confidence"] for k, v in rec["fields"].items() if v["value"] != ""}
        out["corrected_fields"] = [k for k, v in rec["fields"].items() if v.get("corrected")]
    return out


MIMES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".tif": "image/tiff", ".tiff": "image/tiff", ".bmp": "image/bmp", ".webp": "image/webp"}


def status_of(rec) -> str:
    levels = {i["level"] for i in rec["issues"]}
    return "error" if "error" in levels else "warn" if "warning" in levels else "ok"


def public(rec) -> dict:
    """JSON-safe view sent to the browser (no private '_' keys, no bytes)."""
    required = set(REQUIRED[rec["doc_type"]])
    return {
        "id": rec["id"],
        "filename": rec["filename"],
        "doc_type": rec["doc_type"],
        "type_confidence": rec["type_confidence"],
        "method": rec["method"],
        "raw_text": rec["raw_text"],
        "fields": [{"name": k, "value": v["value"], "confidence": v["confidence"],
                    "source": v.get("source", ""), "corrected": v.get("corrected", False),
                    "required": k in required} for k, v in rec["fields"].items()],
        "line_items": rec["line_items"],
        "issues": rec["issues"],
        "verified": rec["verified"],
        "status": status_of(rec),
        "preview": MIMES.get(Path(rec["filename"]).suffix.lower()),
    }
