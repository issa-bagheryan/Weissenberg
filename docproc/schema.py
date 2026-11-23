"""Document types, required fields, field kinds and shared regexes."""
import re

DOC_TYPES = ["invoice", "receipt", "contract", "application", "generic"]

# fields that must be present for each document type
REQUIRED = {
    "invoice": ["invoice_number", "vendor", "invoice_date", "total"],
    "receipt": ["merchant", "date", "total"],
    "contract": ["party_1", "party_2", "effective_date"],
    "application": ["full_name", "date_of_birth", "address", "email"],
    "generic": [],
}

# how a field's value is interpreted / validated
FIELD_TYPES = {
    "invoice_date": "date", "due_date": "date", "date": "date",
    "effective_date": "date", "end_date": "date", "date_of_birth": "date",
    "application_date": "date",
    "subtotal": "amount", "tax": "amount", "total": "amount",
    "contract_value": "amount",
    "email": "email",
}

MONTHS = {}
for _i, _names in enumerate(
    [("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"),
     ("may",), ("june", "jun"), ("july", "jul"), ("august", "aug"),
     ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"),
     ("december", "dec"),
     # German month names
     ("januar",), ("februar",), ("märz", "maerz"), (), (), ("juni",), ("juli",),
     (), (), ("oktober", "okt"), (), ("dezember", "dez")], start=0):
    for _n in _names:
        MONTHS[_n] = _i % 12 + 1
_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
AMT_RE = re.compile(
    r"(?:[$€£]\s?)?-?\d{1,3}(?:[.,]\d{3})*[.,]\d{2}(?!\d)|(?:[$€£]\s?)?-?\d+[.,]\d{2}(?!\d)"
)
CURRENCY_MAP = {"$": "USD", "€": "EUR", "£": "GBP", "USD": "USD", "EUR": "EUR",
                "GBP": "GBP", "CHF": "CHF", "CAD": "CAD", "AUD": "AUD"}
