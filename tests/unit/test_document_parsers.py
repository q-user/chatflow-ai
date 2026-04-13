"""Unit tests for document parsers (PDF, DOCX, processor)."""

from unittest.mock import MagicMock, patch

import pytest

from infrastructure.parsers.docx import parse_docx
from infrastructure.parsers.document_processor import (
    is_document_mime,
    process_document,
)
from infrastructure.parsers.exceptions import ParseError
from infrastructure.parsers.pdf import parse_pdf


# ──────────────────────────────────────────────
# PDF parser tests (pymupdf4llm)
# ──────────────────────────────────────────────


def test_parse_pdf_file_not_found():
    """Non-existent file → ParseError."""
    with pytest.raises(ParseError, match="PDF file not found"):
        parse_pdf("/nonexistent/file.pdf")


def test_parse_pdf_success(tmp_path):
    """Valid PDF → Markdown text with tables preserved."""
    pdf_file = tmp_path / "test.pdf"
    pdf_file.write_bytes(b"fake_pdf_data")

    md_output = "# Header\n\n| Col1 | Col2 |\n|------|------|\n| A | B |"

    with patch("pymupdf4llm.to_markdown", return_value=md_output):
        result = parse_pdf(str(pdf_file))

    assert "# Header" in result
    assert "| Col1 | Col2 |" in result


def test_parse_pdf_no_text(tmp_path):
    """PDF with no extractable text → ParseError."""
    pdf_file = tmp_path / "empty.pdf"
    pdf_file.write_bytes(b"fake_pdf_data")

    with patch("pymupdf4llm.to_markdown", return_value="   "):
        with pytest.raises(ParseError, match="no extractable text"):
            parse_pdf(str(pdf_file))


# ──────────────────────────────────────────────
# DOCX parser tests
# ──────────────────────────────────────────────


def test_parse_docx_file_not_found():
    """Non-existent file → ParseError."""
    with pytest.raises(ParseError, match="DOCX file not found"):
        parse_docx("/nonexistent/file.docx")


def test_parse_docx_success(tmp_path):
    """Valid DOCX → extracted text from paragraphs."""
    mock_para = MagicMock()
    mock_para.text = "Hello world"

    mock_doc = MagicMock()
    mock_doc.paragraphs = [mock_para]
    mock_doc.tables = []

    docx_file = tmp_path / "test.docx"
    docx_file.write_bytes(b"fake_docx_data")

    with patch("docx.Document", return_value=mock_doc):
        result = parse_docx(str(docx_file))

    assert result == "Hello world"


def test_parse_docx_with_tables(tmp_path):
    """DOCX with tables → text with | separators."""
    mock_para = MagicMock()
    mock_para.text = "Paragraph text"

    mock_cell1 = MagicMock()
    mock_cell1.text = "Item"
    mock_cell2 = MagicMock()
    mock_cell2.text = "Amount"
    mock_row = MagicMock()
    mock_row.cells = [mock_cell1, mock_cell2]
    mock_table = MagicMock()
    mock_table.rows = [mock_row]

    mock_doc = MagicMock()
    mock_doc.paragraphs = [mock_para]
    mock_doc.tables = [mock_table]

    docx_file = tmp_path / "table.docx"
    docx_file.write_bytes(b"fake_docx_data")

    with patch("docx.Document", return_value=mock_doc):
        result = parse_docx(str(docx_file))

    assert "Paragraph text" in result
    assert "Item | Amount" in result


def test_parse_docx_empty(tmp_path):
    """Empty DOCX → ParseError."""
    mock_doc = MagicMock()
    mock_doc.paragraphs = []
    mock_doc.tables = []

    docx_file = tmp_path / "empty.docx"
    docx_file.write_bytes(b"fake_docx_data")

    with patch("docx.Document", return_value=mock_doc):
        with pytest.raises(ParseError, match="no extractable text"):
            parse_docx(str(docx_file))


# ──────────────────────────────────────────────
# Document processor tests
# ──────────────────────────────────────────────


def test_process_document_pdf(tmp_path):
    """process_document dispatches to parse_pdf for application/pdf."""
    pdf_file = tmp_path / "test.pdf"
    pdf_file.write_bytes(b"fake_pdf")

    with patch("pymupdf4llm.to_markdown", return_value="# Invoice\nTotal: 100 USD"):
        result = process_document(str(pdf_file), "application/pdf")

    assert "# Invoice" in result


def test_process_document_docx(tmp_path):
    """process_document dispatches to parse_docx for DOCX MIME."""
    docx_file = tmp_path / "test.docx"
    docx_file.write_bytes(b"fake_docx")

    mock_para = MagicMock()
    mock_para.text = "DOCX text"
    mock_doc = MagicMock()
    mock_doc.paragraphs = [mock_para]
    mock_doc.tables = []

    with patch("docx.Document", return_value=mock_doc):
        result = process_document(
            str(docx_file),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    assert result == "DOCX text"


def test_process_document_unsupported_mime():
    """Unsupported MIME → ValueError."""
    with pytest.raises(ValueError, match="No parser registered"):
        process_document("/tmp/file.txt", "text/plain")


def test_is_document_mime_known():
    """is_document_mime returns True for known MIMEs."""
    assert is_document_mime("application/pdf") is True
    assert (
        is_document_mime(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        is True
    )


def test_is_document_mime_unknown():
    """is_document_mime returns False for unknown MIMEs."""
    assert is_document_mime("text/plain") is False
    assert is_document_mime("image/jpeg") is False
    assert is_document_mime(None) is False
