"""Circular ingestion: extract raw text from an uploaded PDF."""
import pdfplumber
from io import BytesIO


def extract_text_from_pdf(file_bytes: bytes) -> str:
    text_parts = []
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    text = "\n".join(text_parts)
    if not text.strip():
        raise ValueError(
            "No extractable text found — this PDF is likely a scanned image. "
            "MVP scope does not include OCR (see Constraints); ask the user to paste text instead."
        )
    return text
