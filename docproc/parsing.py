"""Low-level parsing: amounts, dates, labelled values."""
import datetime as dt
import re
from collections import Counter

from .schema import AMT_RE, CURRENCY_MAP, EMAIL_RE, MONTHS, _MONTH_RE

def parse_amount(s: str):
    """'1,234.56' / '1.234,56' / '$12.00' / '(5.00)' -> float, else None."""
    if s is None:
        return None
    s = str(s).strip()
    neg = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[^\d.,\-]", "", s)
    if not s:
        return None
    m = re.search(r"[.,](\d{1,2})$", s)
    if m:
        int_part = re.sub(r"[.,]", "", s[:m.start()])
        s = f"{int_part}.{m.group(1)}"
    else:
        s = re.sub(r"[.,]", "", s)
    try:
        v = float(s)
    except ValueError:
        return None
    return -abs(v) if neg else v


def _mk_date(y, m, d):
    try:
        return dt.date(y, m, d).isoformat()
    except ValueError:
        return None


def find_dates(s: str, dayfirst: bool = True) -> list[str]:
    """Find all dates in a string, return as ISO strings in order of appearance."""
    hits = []  # (start, end, iso)

    for m in re.finditer(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", s):
        iso = _mk_date(int(m[1]), int(m[2]), int(m[3]))
        if iso:
            hits.append((m.start(), m.end(), iso))

    for m in re.finditer(r"\b(\d{1,2})([./-])(\d{1,2})\2(\d{2,4})\b", s):
        a, sep, b, y = int(m[1]), m[2], int(m[3]), int(m[4])
        if y < 100:
            y += 2000 if y < 70 else 1900
        if sep == ".":
            day, mon = a, b                     # European dotted dates
        elif a > 12:
            day, mon = a, b
        elif b > 12:
            day, mon = b, a
        else:
            day, mon = (a, b) if dayfirst else (b, a)
        iso = _mk_date(y, mon, day)
        if iso:
            hits.append((m.start(), m.end(), iso))

    for m in re.finditer(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\.?\s+({_MONTH_RE})\.?,?\s+(\d{{4}})\b", s, re.I):
        iso = _mk_date(int(m[3]), MONTHS[m[2].lower()], int(m[1]))
        if iso:
            hits.append((m.start(), m.end(), iso))

    for m in re.finditer(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", s, re.I):
        iso = _mk_date(int(m[3]), MONTHS[m[1].lower()], int(m[2]))
        if iso:
            hits.append((m.start(), m.end(), iso))

    hits.sort()
    out, last_end = [], -1
    for start, end, iso in hits:
        if start >= last_end:
            out.append(iso)
            last_end = end
    return out


def _lab(labels):
    return r"(?<![A-Za-z])(?:" + "|".join(labels) + r")"


def _rest_of_line(text, m, include_next=True):
    """Text after a regex match on the same line, plus the next non-empty line."""
    end = text.find("\n", m.end())
    end = len(text) if end == -1 else end
    same = text[m.end():end]
    nxt = ""
    if include_next:
        for line in text[end + 1:].split("\n"):
            if line.strip():
                nxt = line
                break
    return same, nxt


def grab_text(text, labels):
    """Value following a label ('Bill To: Acme'); uses next line if same line empty."""
    for m in re.finditer(_lab(labels) + r"[ \t]*[:#\-–]?[ \t]*", text, re.I):
        same, nxt = _rest_of_line(text, m)
        val = same.strip() or nxt.strip()
        if val:
            return val[:200], text[m.start():m.end()] + val[:60]
    return None


def grab_ident(text, labels):
    pat = (_lab(labels) + r"[ \t]*(?:no\.?|number|nr\.?|num\.?|#|id)?[ \t]*[:#]?[ \t]*"
           r"(?=[A-Z0-9\-/_.]*\d)([A-Z0-9][A-Z0-9\-/_.]*)")
    m = re.search(pat, text, re.I)
    if m:
        return m.group(1).rstrip(".-/_"), m.group(0).strip()
    return None


def grab_date(text, labels, dayfirst=True):
    for m in re.finditer(_lab(labels), text, re.I):
        same, nxt = _rest_of_line(text, m)
        for chunk in (same, nxt if not same.strip() else ""):
            found = find_dates(chunk, dayfirst)
            if found:
                return found[0], (m.group(0) + " " + chunk.strip())[:80]
    return None


def grab_amount(text, labels):
    for m in re.finditer(_lab(labels), text, re.I):
        same, nxt = _rest_of_line(text, m)
        for chunk in (same, nxt if not AMT_RE.search(same) else ""):
            chunk = re.sub(r"\d+(?:[.,]\d+)?\s*%", "", chunk)   # drop percentages
            amts = AMT_RE.findall(chunk)
            if amts:
                v = parse_amount(amts[-1])
                if v is not None:
                    return f"{v:.2f}", (m.group(0) + " " + chunk.strip())[:80]
    return None


def detect_currencies(text):
    found = Counter()
    for sym in re.findall(r"[$€£]|\b(?:USD|EUR|GBP|CHF|CAD|AUD)\b", text):
        found[CURRENCY_MAP[sym]] += 1
    return found


def put(fields, name, res, conf=0.9):
    if res:
        value, snippet = res
        fields[name] = {"value": value, "confidence": conf, "source": snippet}


def collapse(s):
    return re.sub(r"\s+", " ", s).strip(" ,.;:")
