"""Classify a document and extract its fields."""
import re

from .parsing import (_lab, collapse, detect_currencies, find_dates, grab_amount, grab_date,
                      grab_ident, grab_text, parse_amount, put)
from .schema import AMT_RE, EMAIL_RE, REQUIRED

KEYWORDS = {
    "invoice": ["invoice", "bill to", "due date", "amount due", "rechnung",
                "payment terms", "po number", "balance due"],
    "receipt": ["receipt", "thank you", "cash", "change", "transaction",
                "tendered", "visa", "mastercard", "card", "beleg", "kassenbon"],
    "contract": ["agreement", "contract", "parties", "hereby", "whereas",
                 "governing law", "terminat", "effective date", "witness", "vertrag"],
    "application": ["application", "applicant", "date of birth", "dob",
                    "please print", "employment", "signature of applicant", "antrag"],
}


def classify(text: str) -> tuple[str, float]:
    low = text.lower()
    head = " ".join(low.split("\n")[:4])
    scores = {}
    for dtype, words in KEYWORDS.items():
        s = sum(min(low.count(w), 3) for w in words)
        s += 5 * sum(1 for w in words[:1] if w in head)       # title match
        scores[dtype] = s
    best = max(scores, key=scores.get)
    total = sum(scores.values())
    if scores[best] < 2:
        return "generic", 0.0
    return best, round(scores[best] / total, 2) if total else 0.0


TOTAL_WORDS = r"total|tax|vat|subtotal|change|cash|visa|mastercard|card|amount|balance|tip|discount|summe|mwst"
ITEM_RE = re.compile(
    rf"^\s*(?P<desc>.*?[A-Za-z].*?)\s+(?P<qty>\d+(?:[.,]\d+)?)\s*(?:x|×)?\s+"
    rf"[$€£]?\s?(?P<unit>{AMT_RE.pattern})\s+[$€£]?\s?(?P<amt>{AMT_RE.pattern})\s*$"
)
SIMPLE_ITEM_RE = re.compile(rf"^\s*(?P<desc>[A-Za-z][^\n]*?)\s{{2,}}[$€£]?\s?(?P<amt>{AMT_RE.pattern})\s*$")


def _guess_org(text):
    for line in text.split("\n")[:8]:
        line = line.strip()
        if 3 <= len(line) <= 60 and re.search(r"[A-Za-z]{3}", line) and not re.search(
                r"invoice|receipt|rechnung|date|bill|tax|page|^\d|total|beleg", line, re.I):
            return line, line
    return None


def _items_full(text):
    items = []
    for line in text.split("\n"):
        if re.search(TOTAL_WORDS, line, re.I):
            continue
        m = ITEM_RE.match(line)
        if m:
            items.append({
                "description": collapse(m["desc"]),
                "quantity": float(m["qty"].replace(",", ".")),
                "unit_price": parse_amount(m["unit"]),
                "amount": parse_amount(m["amt"]),
            })
    return items


def _items_simple(text):
    items = []
    for line in text.split("\n"):
        if re.search(TOTAL_WORDS, line, re.I):
            continue
        m = SIMPLE_ITEM_RE.match(line)
        if m:
            items.append({"description": collapse(m["desc"]), "quantity": None,
                          "unit_price": None, "amount": parse_amount(m["amt"])})
    return items


def extract_invoice(t, dayfirst):
    f = {}
    put(f, "invoice_number", grab_ident(t, ["rechnungs?nummer", "rechnungs?nr", "invoice", "inv"]))
    put(f, "po_number", grab_ident(t, ["po", "purchase order", "bestellnummer"]))
    put(f, "invoice_date", grab_date(t, ["invoice date", "date of issue", "issued", "rechnungsdatum", "date", "datum"], dayfirst))
    put(f, "due_date", grab_date(t, ["due date", "payment due", "due by", "due", "fällig(?:keitsdatum)?", "zahlungsziel"], dayfirst))
    v = grab_text(t, ["from", "vendor", "seller", "supplier", "issued by", "lieferant"])
    if v:
        put(f, "vendor", v, 0.85)
    else:
        put(f, "vendor", _guess_org(t), 0.65)
    put(f, "bill_to", grab_text(t, ["bill(?:ed)? to", "customer", "client", "sold to", "rechnungsempfänger", "kunde"]))
    put(f, "subtotal", grab_amount(t, ["subtotal", "sub-total", "net amount", "zwischensumme", "netto"]))
    put(f, "tax", grab_amount(t, ["vat", "sales tax", "tax", "mwst", "ust", "umsatzsteuer"]))
    tot = grab_amount(t, ["amount due", "balance due", "total due", "grand total", "total amount",
                          "amount payable", "gesamtbetrag", "total", "summe"])
    if tot:
        put(f, "total", tot)
    else:
        amts = [parse_amount(a) for a in AMT_RE.findall(t)]
        amts = [a for a in amts if a is not None]
        if amts:
            put(f, "total", (f"{max(amts):.2f}", "largest amount in document"), 0.4)
    put(f, "email", _first_email(t), 0.8)
    return f, _items_full(t)


def extract_receipt(t, dayfirst):
    f = {}
    put(f, "merchant", _guess_org(t), 0.6)
    put(f, "date", grab_date(t, ["date", "datum"], dayfirst) or _any_date(t, dayfirst), 0.8)
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?\s*(?:AM|PM)?\b", t, re.I)
    if m:
        f["time"] = {"value": m.group(0), "confidence": 0.8, "source": m.group(0)}
    put(f, "receipt_number", grab_ident(t, ["receipt", "transaction", "trans", "order", "beleg"]))
    put(f, "subtotal", grab_amount(t, ["subtotal", "sub-total", "zwischensumme"]))
    put(f, "tax", grab_amount(t, ["vat", "sales tax", "tax", "mwst", "ust"]))
    tot = grab_amount(t, ["grand total", "total due", "amount due", "total", "summe", "gesamt"])
    put(f, "total", tot)
    pm = re.search(r"\b(visa|mastercard|master card|amex|american express|maestro|girocard|ec-karte|paypal|cash|bar)\b", t, re.I)
    if pm:
        f["payment_method"] = {"value": pm.group(1).title(), "confidence": 0.8, "source": pm.group(0)}
    l4 = re.search(r"(?:[*•xX]{2,}|ending in)[ \t]*(\d{4})\b", t, re.I)
    if l4:
        f["card_last4"] = {"value": l4.group(1), "confidence": 0.8, "source": l4.group(0)}
    return f, _items_simple(t)


def extract_contract(t, dayfirst):
    f = {}
    head = t[:2500]
    m = re.search(r"between\s+(.{3,150}?)\s+(?:\([^)]*\)\s*)?and\s+(.{3,150}?)(?:\s*\(|,|\.\s|\n\n|$)",
                  head, re.I | re.S)
    if m:
        put(f, "party_1", (collapse(m[1]), m[0][:80]), 0.7)
        put(f, "party_2", (collapse(m[2]), m[0][:80]), 0.7)
    put(f, "contract_number", grab_ident(t, ["contract", "agreement"]))
    put(f, "effective_date", grab_date(t, ["effective date", "effective as of", "dated as of",
                                           "commenc(?:es|ing) on", "dated", "start date"], dayfirst))
    put(f, "end_date", grab_date(t, ["end date", "expir(?:es|ation date)", "terminat(?:es|ion date) on",
                                     "until"], dayfirst))
    tm = re.search(r"term of\s+((?:\w+\s*)?\(?\d+\)?|\w+)\s+(years?|months?|days?)", t, re.I)
    if tm:
        f["term"] = {"value": collapse(tm.group(0)[8:]), "confidence": 0.75, "source": tm.group(0)}
    gl = re.search(r"governed by (?:and construed in accordance with )?the laws? of (?:the )?([A-Z][\w ,]{2,40}?)[.,;\n]", t)
    if gl:
        f["governing_law"] = {"value": gl.group(1).strip(), "confidence": 0.8, "source": gl.group(0)[:80]}
    put(f, "contract_value", grab_amount(t, ["total contract value", "contract value", "contract price",
                                             "purchase price", "total fee", "fee of", "total price"]), 0.75)
    signed = "yes" if _has_signature(t) else "no"
    f["signed"] = {"value": signed, "confidence": 0.5, "source": "signature heuristic"}
    put(f, "email", _first_email(t), 0.7)
    return f, []


def extract_application(t, dayfirst):
    f = {}
    put(f, "full_name", grab_text(t, ["full name", "applicant(?:'s)? name", "name of applicant", "name"]))
    put(f, "date_of_birth", grab_date(t, ["date of birth", "birth date", "dob", "geburtsdatum", "born"], dayfirst))
    put(f, "email", _first_email(t), 0.9)
    ph = grab_text(t, ["phone", "telephone", "mobile", "tel", "telefon"])
    if ph:
        pm = re.search(r"\+?\d[\d\s().\-/]{6,}\d", ph[0])
        if pm:
            put(f, "phone", (pm.group(0).strip(), ph[1]), 0.85)
    put(f, "address", grab_text(t, ["address", "street", "adresse", "anschrift"]))
    put(f, "id_number", grab_ident(t, ["passport", "national id", "id number", "id", "ssn", "tax id", "ausweisnummer"]), 0.8)
    put(f, "application_date", grab_date(t, ["application date", "date of application", "date signed", "date(?! of birth)", "datum"], dayfirst), 0.7)
    f["signature_present"] = {
        "value": "yes" if _has_signature(t) else "no",
        "confidence": 0.5, "source": "signature heuristic"}
    return f, []


def extract_generic(t, dayfirst):
    f = {}
    d = find_dates(t, dayfirst)
    for i, x in enumerate(d[:5], 1):
        f[f"date_{i}"] = {"value": x, "confidence": 0.5, "source": x}
    amts = [parse_amount(a) for a in AMT_RE.findall(t)]
    amts = [a for a in amts if a is not None]
    if amts:
        f["largest_amount"] = {"value": f"{max(amts):.2f}", "confidence": 0.4, "source": "largest amount"}
    put(f, "email", _first_email(t), 0.8)
    put(f, "identifier", grab_ident(t, ["id", "no", "number", "ref(?:erence)?", "nr"]), 0.5)
    return f, []


def _has_signature(t):
    """True if a signature line has text after it (blank '____' lines don't count)."""
    return bool(re.search(
        r"/s/|signed (?:electronically )?by|signature(?:\s+of\s+\w+)?[ \t]*:[ \t]*[A-Za-z/]{2,}", t, re.I))


def _first_email(t):
    m = EMAIL_RE.search(t)
    return (m.group(0), m.group(0)) if m else None


def _any_date(t, dayfirst):
    d = find_dates(t, dayfirst)
    return (d[0], d[0]) if d else None


EXTRACTORS = {"invoice": extract_invoice, "receipt": extract_receipt, "contract": extract_contract,
              "application": extract_application, "generic": extract_generic}
