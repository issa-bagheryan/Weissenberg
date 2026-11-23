"""Read text out of PDFs, images (OCR), Word and plain-text files."""
import io
from pathlib import Path

def ocr_available() -> bool:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _ocr_image(img) -> str:
    """OCR with --psm 6 (one uniform block) so 'Total ..... 3.85' stays on one line."""
    import pytesseract
    return pytesseract.image_to_string(img.convert("L"), config="--psm 6")


def extract_text(filename: str, data: bytes) -> tuple[str, str]:
    """Return (text, method). Falls back to OCR for scanned PDFs."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        import pdfplumber
        pages, scanned = [], []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                txt = page.extract_text() or ""
                if len(txt.strip()) < 20 and ocr_available():
                    txt = _ocr_image(page.to_image(resolution=200).original)
                    scanned.append(True)
                pages.append(txt)
        return "\n".join(pages), "pdf+ocr" if scanned else "pdf"
    if ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"):
        if not ocr_available():
            raise RuntimeError(
                "Image files need OCR: install Tesseract and `pip install pytesseract`.")
        from PIL import Image
        return _ocr_image(Image.open(io.BytesIO(data))), "ocr"
    if ext == ".docx":
        import docx
        d = docx.Document(io.BytesIO(data))
        parts = [p.text for p in d.paragraphs]
        for table in d.tables:
            for row in table.rows:
                parts.append("   ".join(c.text.strip() for c in row.cells))
        return "\n".join(parts), "docx"
    for enc in ("utf-8", "latin-1"):
        try:
            return data.decode(enc), "text"
        except UnicodeDecodeError:
            continue
    raise ValueError("Unsupported file format")
