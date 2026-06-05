from __future__ import annotations

import subprocess
from pathlib import Path


def extract_pdf_text(path: Path) -> str:
    """Extract text locally with poppler, falling back to pypdf.

    `pdftotext` handles the encrypted Barclays statements available in this
    dataset without requiring raw PDF modification.
    """
    try:
        proc = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            check=True,
            capture_output=True,
            text=True,
            timeout=90,
        )
        if proc.stdout.strip():
            return proc.stdout
    except Exception:
        pass

    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)

