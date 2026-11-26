"""Extract text from uploaded PDF documents using pypdf."""

import io
import logging

from pypdf import PdfReader

from app.services.rag.errors import RagDocumentError

logger = logging.getLogger(__name__)


def extract_pdf_pages(data: bytes) -> list[str]:
    """Return the extracted text of each PDF page, in order (1-based when indexed).

    Raises RagDocumentError when the bytes are not a readable PDF, the file is
    password-protected, or no page contains extractable text (for example a
    scanned, image-only PDF).
    """
    if not data:
        raise RagDocumentError("The uploaded file is empty.")

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            # Some PDFs open with an empty password; try that once before giving up.
            try:
                reader.decrypt("")
            except Exception:  # noqa: BLE001 - any failure means it stays locked
                pass
            if reader.is_encrypted:
                raise RagDocumentError("The PDF is password-protected and cannot be read.")

        pages: list[str] = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception as exc:  # noqa: BLE001 - one bad page must not fail the file
                logger.warning("Failed to extract text from a PDF page (%s)", type(exc).__name__)
                pages.append("")
    except RagDocumentError:
        raise
    except Exception as exc:  # noqa: BLE001 - any parser failure becomes a clean error
        logger.warning("PDF parsing failed (%s)", type(exc).__name__)
        raise RagDocumentError("The uploaded file could not be read as a PDF.") from exc

    if not any(page.strip() for page in pages):
        raise RagDocumentError(
            "No extractable text was found in the PDF. It may be a scanned image "
            "or contain only images."
        )
    return pages
