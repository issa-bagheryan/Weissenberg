"""
Weissenberg - document processing.

    python run.py                          start the web app (opens your browser)
    python run.py --port 9000              different port
    python run.py invoice.pdf scan.jpg     no UI: process files, write JSON/CSV/Excel to ./output
"""
import shutil
import sys
from pathlib import Path

PY_MODULES = ["schema", "reader", "parsing", "extractors", "validation", "records",
              "exporters", "store", "server", "cli"]
STATIC_FILES = ["index.html", "style.css", "app.js"]
INIT = ('"""docproc - extract, check and export structured data from documents."""\n'
        "from .exporters import export_csv, export_excel\nfrom .records import process_document, re_extract, to_json\n"
        "from .schema import DOC_TYPES\nfrom .validation import validate\n")


def fix_flat_layout():
    """If the files were downloaded one by one into a single folder, sort them into docproc/ and static/."""
    here = Path(__file__).resolve().parent
    pkg, static = here / "docproc", here / "static"
    pkg.mkdir(exist_ok=True)
    static.mkdir(exist_ok=True)
    for m in PY_MODULES:
        src = here / f"{m}.py"
        if src.exists() and not (pkg / src.name).exists():
            shutil.move(str(src), pkg / src.name)
    for f in STATIC_FILES:
        src = here / f
        if src.exists() and not (static / f).exists():
            shutil.move(str(src), static / f)
    if not (pkg / "__init__.py").exists():
        (pkg / "__init__.py").write_text(INIT, encoding="utf-8")
    missing = [f"{m}.py" for m in PY_MODULES if not (pkg / f"{m}.py").exists()] + \
              [f for f in STATIC_FILES if not (static / f).exists()]
    if missing:
        sys.exit("Missing files: " + ", ".join(missing) + "\nPut them next to run.py (or inside docproc/ and static/).")


if __name__ == "__main__":
    fix_flat_layout()
    args = sys.argv[1:]
    if args and not args[0].startswith("-") or "--out" in args:
        from docproc.cli import run
        run(args)
    else:
        import argparse
        from docproc.server import serve
        p = argparse.ArgumentParser()
        p.add_argument("--port", type=int, default=8000)
        p.add_argument("--data", default="data", help="folder for uploaded files and saved work")
        p.add_argument("--no-browser", action="store_true")
        a = p.parse_args(args)
        serve(a.port, a.data, not a.no_browser)
