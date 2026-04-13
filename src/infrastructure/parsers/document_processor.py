"""Document processor: MIME-based dispatch to parsers."""

import logging
from collections.abc import Callable

from infrastructure.parsers.docx import parse_docx
from infrastructure.parsers.pdf import parse_pdf

logger = logging.getLogger(__name__)

# MIME → parser function mapping
MIME_PARSERS: dict[str, Callable[[str], str]] = {
    "application/pdf": parse_pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": parse_docx,
}


def process_document(file_path: str, mime_type: str) -> str:
    """Extract text from a document file based on its MIME type.

    :param file_path: Local path to the downloaded file.
    :param mime_type: MIME type (e.g. "application/pdf").
    :returns: Extracted text.
    :raises ValueError: If MIME type is not supported.
    :raises ParseError: If parsing fails.
    """
    parser = MIME_PARSERS.get(mime_type)
    if parser is None:
        raise ValueError(f"No parser registered for MIME type: {mime_type}")
    return parser(file_path)


def is_document_mime(mime_type: str | None) -> bool:
    """Check if a MIME type has a registered document parser.

    :param mime_type: MIME type string or None.
    :returns: True if a parser exists for this MIME type.
    """
    return mime_type in MIME_PARSERS
