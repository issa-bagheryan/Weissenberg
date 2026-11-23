"""CSV / Excel export."""
import io

from .parsing import parse_amount
from .schema import FIELD_TYPES
from .validation import _d

def _field_columns(records):
    cols = []
    for r in records:
        for k in r["fields"]:
            if k not in cols:
                cols.append(k)
    return cols


def _doc_rows(records):
    cols = _field_columns(records)
    header = ["filename", "document_type", "verified", "errors", "warnings"] + cols
    rows = []
    for r in records:
        errs = sum(1 for i in r["issues"] if i["level"] == "error")
        warns = sum(1 for i in r["issues"] if i["level"] == "warning")
        rows.append([r["filename"], r["doc_type"], "yes" if r["verified"] else "no", errs, warns]
                    + [r["fields"].get(c, {}).get("value", "") for c in cols])
    return header, rows


def _item_rows(records):
    header = ["filename", "description", "quantity", "unit_price", "amount"]
    rows = [[r["filename"], i.get("description"), i.get("quantity"), i.get("unit_price"), i.get("amount")]
            for r in records for i in r["line_items"]]
    return header, rows


def _issue_rows(records):
    header = ["filename", "level", "field", "message"]
    rows = [[r["filename"], i["level"], i["field"], i["message"]] for r in records for i in r["issues"]]
    return header, rows


def export_csv(records, kind="documents") -> bytes:
    import csv
    header, rows = {"documents": _doc_rows, "line_items": _item_rows, "issues": _issue_rows}[kind](records)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return ("\ufeff" + buf.getvalue()).encode("utf-8")        # BOM so Excel reads UTF-8 correctly


def export_excel(records) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    wb.remove(wb.active)
    hdr_font = Font(name="Arial", bold=True, color="FFFFFF")
    hdr_fill = PatternFill("solid", fgColor="1F4E78")
    body_font = Font(name="Arial")
    amount_cols = {k for k, t in FIELD_TYPES.items() if t == "amount"} | {"quantity", "unit_price", "amount"}
    date_cols = {k for k, t in FIELD_TYPES.items() if t == "date"}

    for title, builder in (("Documents", _doc_rows), ("Line items", _item_rows), ("Issues", _issue_rows)):
        header, rows = builder(records)
        ws = wb.create_sheet(title)
        ws.append(header)
        for c in ws[1]:
            c.font, c.fill = hdr_font, hdr_fill
            c.alignment = Alignment(vertical="center")
        for row in rows:
            ws.append(row)
        for r_idx, row in enumerate(ws.iter_rows(min_row=2), 2):
            for c_idx, cell in enumerate(row):
                cell.font = body_font
                name = header[c_idx]
                if name in amount_cols and cell.value not in (None, ""):
                    v = parse_amount(cell.value) if isinstance(cell.value, str) else cell.value
                    if v is not None:
                        cell.value, cell.number_format = v, "#,##0.00"
                elif name in date_cols and isinstance(cell.value, str) and _d(cell.value):
                    cell.value, cell.number_format = _d(cell.value), "yyyy-mm-dd"
        for i, name in enumerate(header, 1):
            width = max([len(str(name))] + [len(str(r[i - 1])) for r in rows if r[i - 1] is not None])
            ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 10), 60)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
