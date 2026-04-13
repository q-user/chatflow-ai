"""PDF text extraction using pymupdf4llm (Markdown output)."""

import logging
from pathlib import Path

from infrastructure.parsers.exceptions import ParseError

logger = logging.getLogger(__name__)


def parse_pdf(file_path: str) -> str:
    """Extract text from a PDF file as Markdown.

    Uses pymupdf4llm which preserves table structure, headings,
    and multi-column layout — optimal for LLM consumption.

    :param file_path: Local path to the PDF file.
    :returns: Markdown-formatted text (all pages concatenated).
    :raises ParseError: If file cannot be read or parsed.
    """
    path = Path(file_path)
    if not path.exists():
        raise ParseError(f"PDF file not found: {file_path}")

    try:
        import pymupdf4llm  # lazy import — optional dependency

        md_text = pymupdf4llm.to_markdown(str(path))

        if not md_text.strip():
            raise ParseError(f"PDF contains no extractable text: {file_path}")

        return md_text

    except ImportError as e:
        raise ParseError(
            "pymupdf4llm is not installed. Add it to pyproject.toml."
        ) from e
    except Exception as e:
        raise ParseError(f"Failed to parse PDF {file_path}: {e}") from e
