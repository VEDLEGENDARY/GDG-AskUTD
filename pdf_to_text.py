#!/usr/bin/env python3
"""Extract text from PDFs in ``backend/data/raw_pdfs``.

Install the dependency with ``python -m pip install pypdf`` (PyMuPDF or pypdfium2
are used as a fallback for files pypdf cannot parse), then run:
    python pdf_to_text.py

Text files are written to ``backend/data/raw_text`` with the same base names as
their PDFs. A single PDF can also be passed to write its text to standard
output, or to an optional output file. Scanned/image-only PDFs need OCR.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = ROOT / "backend" / "data" / "raw_pdfs"
DEFAULT_OUTPUT_DIR = ROOT / "backend" / "data" / "raw_text"


def _extract_with_pypdf(pdf_path: Path) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    return [(page.extract_text() or "").strip() for page in reader.pages]


def _extract_with_fallback(pdf_path: Path) -> list[str]:
    """Used when pypdf cannot parse a file; tries PyMuPDF, then pypdfium2."""
    try:
        import fitz  # PyMuPDF

        with fitz.open(str(pdf_path)) as document:
            return [page.get_text().strip() for page in document]
    except ImportError:
        pass
    import pypdfium2

    document = pypdfium2.PdfDocument(str(pdf_path))
    return [page.get_textpage().get_text_range().strip() for page in document]


def extract_text(pdf_path: Path) -> str:
    try:
        pages = _extract_with_pypdf(pdf_path)
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency: install pypdf with `python -m pip install pypdf`."
        ) from exc
    except Exception:
        try:
            pages = _extract_with_fallback(pdf_path)
        except ImportError as exc:
            raise RuntimeError(
                f"pypdf could not read {pdf_path.name}; install pymupdf or pypdfium2 as a fallback."
            ) from exc
    return "\n\n".join(pages).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract text from PDFs in backend/data/raw_pdfs.")
    parser.add_argument("pdf", type=Path, nargs="?", help="one PDF to read (default: process the input directory)")
    parser.add_argument("output", type=Path, nargs="?", help="text file for a single PDF (default: stdout)")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR, help="directory of PDFs (default: backend/data/raw_pdfs)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="directory for extracted text (default: backend/data/raw_text)")
    args = parser.parse_args()

    if args.pdf:
        if not args.pdf.is_file():
            parser.error(f"input file does not exist: {args.pdf}")
        try:
            text = extract_text(args.pdf)
            if args.output:
                args.output.write_text(text, encoding="utf-8")
            else:
                sys.stdout.write(text)
        except Exception as exc:
            print(f"pdf_to_text: {args.pdf}: {exc}", file=sys.stderr)
            return 1
        return 0

    if not args.input_dir.is_dir():
        parser.error(f"input directory does not exist: {args.input_dir}")

    pdfs = sorted(path for path in args.input_dir.iterdir() if path.is_file() and path.suffix.lower() == ".pdf")
    if not pdfs:
        print(f"No PDF files found in {args.input_dir}", file=sys.stderr)
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for pdf_path in pdfs:
        output_path = args.output_dir / f"{pdf_path.stem}.txt"
        try:
            output_path.write_text(extract_text(pdf_path), encoding="utf-8")
            print(f"Converted {pdf_path.name} -> {output_path}")
        except Exception as exc:
            failures += 1
            print(f"pdf_to_text: {pdf_path}: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())