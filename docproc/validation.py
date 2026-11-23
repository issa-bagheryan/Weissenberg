"""Normalise values and detect missing / inconsistent information."""
from __future__ import annotations

import datetime as dt

from .parsing import find_dates, parse_amount
from .schema import EMAIL_RE, FIELD_TYPES, REQUIRED

def normalize_value(name, value, dayfirst=True):
    v = (value or "").strip()
    kind = FIELD_TYPES.get(name)
    if not v:
        return v
    if kind == "date":
        d = find_dates(v, dayfirst)
        return d[0] if d else v
    if kind == "amount":
        a = parse_amount(v)
        return f"{a:.2f}" if a is not None else v
    if kind == "email":
        return v.lower()
    return v


def _d(s):
    try:
        return dt.date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _close(a, b, tol=0.02):
    return abs(a - b) <= tol


def validate(rec: dict, others: list[dict] | None = None) -> list[dict]:
    """Detect missing and inconsistent information. Returns (and stores) issues."""
    issues = []

    def add(level, field, msg):
        issues.append({"level": level, "field": field, "message": msg})

    dtype = rec["doc_type"]
    fields = rec["fields"]
    val = {k: v["value"] for k, v in fields.items()}
    today = dt.date.today()

    for name in REQUIRED.get(dtype, []):
        if not val.get(name):
            add("error", name, "Required field is missing")

    for name, meta in fields.items():
        v = meta["value"]
        if not v:
            continue
        kind = FIELD_TYPES.get(name)
        if kind == "date":
            d = _d(v)
            if d is None:
                add("error", name, f"'{v}' is not a valid date (use YYYY-MM-DD)")
            elif d > today + dt.timedelta(days=366):
                add("warning", name, f"Date {v} is more than a year in the future")
            elif d.year < 1900:
                add("warning", name, f"Date {v} looks too old")
        elif kind == "amount" and parse_amount(v) is None:
            add("error", name, f"'{v}' is not a valid amount")
        elif kind == "email" and not EMAIL_RE.fullmatch(v):
            add("warning", name, f"'{v}' does not look like a valid email address")
        if meta.get("confidence", 1) < 0.6 and not meta.get("corrected") and name not in ("signed", "signature_present"):
            add("warning", name, "Low-confidence extraction - please verify")

    num = lambda k: parse_amount(val.get(k)) if val.get(k) else None
    items = rec.get("line_items", [])

    if dtype in ("invoice", "receipt"):
        sub, tax, tot = num("subtotal"), num("tax"), num("total")
        if tot is not None and tot <= 0:
            add("warning", "total", "Total is zero or negative")
        if None not in (sub, tax, tot) and not _close(sub + tax, tot):
            add("error", "total",
                f"Subtotal ({sub:.2f}) + tax ({tax:.2f}) = {sub + tax:.2f}, but total is {tot:.2f}")
        amounts = [i["amount"] for i in items if isinstance(i.get("amount"), (int, float))]
        if amounts:
            s = sum(amounts)
            ref, ref_name = (sub, "subtotal") if sub is not None else (
                (tot - tax, "total minus tax") if tot is not None and tax is not None else (tot, "total"))
            if ref is not None and not _close(s, ref, 0.05):
                add("warning", "line_items", f"Line items sum to {s:.2f}, but {ref_name} is {ref:.2f}")
        for n, it in enumerate(items, 1):
            q, u, a = it.get("quantity"), it.get("unit_price"), it.get("amount")
            if all(isinstance(x, (int, float)) for x in (q, u, a)) and not _close(q * u, a, 0.05):
                add("warning", "line_items", f"Line {n}: {q:g} x {u:.2f} = {q * u:.2f}, but amount is {a:.2f}")

    if dtype == "invoice":
        di, dd = _d(val.get("invoice_date")), _d(val.get("due_date"))
        if di and dd and dd < di:
            add("error", "due_date", "Due date is before the invoice date")
    if dtype == "contract":
        e, x = _d(val.get("effective_date")), _d(val.get("end_date"))
        if e and x and x < e:
            add("error", "end_date", "End date is before the effective date")
        if val.get("signed") == "no":
            add("warning", "signed", "No signature detected")
    if dtype == "application":
        b, a = _d(val.get("date_of_birth")), _d(val.get("application_date"))
        if b:
            if b > today:
                add("error", "date_of_birth", "Date of birth is in the future")
            else:
                age = (today - b).days // 365
                if age > 110:
                    add("warning", "date_of_birth", f"Implied age of {age} looks wrong")
                elif age < 18:
                    add("warning", "date_of_birth", f"Applicant appears to be a minor ({age})")
            if a and a < b:
                add("error", "application_date", "Application date is before date of birth")
        if val.get("signature_present") == "no":
            add("warning", "signature_present", "No signature detected")

    cur = rec.get("_currencies", {})
    if len(cur) > 1:
        add("warning", "currency", "Multiple currencies found: " + ", ".join(sorted(cur)))

    # duplicates across the batch
    if others:
        key = _dup_key(rec)
        if key:
            for o in others:
                if o is not rec and o["doc_type"] == dtype and _dup_key(o) == key:
                    add("warning", "duplicate", f"Possible duplicate of '{o['filename']}'")

    rec["issues"] = issues
    return issues


def _dup_key(rec):
    v = {k: x["value"].lower() for k, x in rec["fields"].items() if x["value"]}
    if rec["doc_type"] == "invoice" and v.get("invoice_number"):
        return (v["invoice_number"], v.get("vendor", ""))
    if rec["doc_type"] == "receipt" and v.get("total") and v.get("date"):
        return (v.get("merchant", ""), v["date"], v["total"])
    return None
