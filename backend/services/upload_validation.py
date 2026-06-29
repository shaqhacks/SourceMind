"""Upload validation: extension + magic-byte (content-sniffing) checks.

The router accepts user-supplied files by extension, but an attacker can rename
arbitrary content to ``.pdf``/``.docx``. :func:`validate_upload` re-validates the
declared type against the file's leading bytes so a content/extension mismatch
is rejected before the file is ever handed to an extractor or the LLM.

Magic bytes:
  * PDF  -> starts with ``%PDF-``
  * DOCX / PPTX (OOXML, ZIP containers) -> start with ``PK\\x03\\x04``
  * TXT / MD -> no reliable magic; any bytes accepted (text is text).
"""
from __future__ import annotations

from SourceMind.backend.extract.material import detect_kind

# Number of leading bytes the router needs to capture for the magic check.
MAGIC_PREFIX_LEN = 8

_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"


class UploadValidationError(Exception):
    """The file content does not match its declared extension/type."""


def validate_upload(filename: str, head_bytes: bytes) -> str:
    """Return the validated *kind* for *filename*, or raise.

    Raises :class:`ValueError` (from :func:`detect_kind`) when the extension is
    unsupported, and :class:`UploadValidationError` when the leading bytes do
    not match the declared type.

    Args:
        filename:   Original (already basename-sanitized) file name.
        head_bytes: The first bytes of the file (>= :data:`MAGIC_PREFIX_LEN`
                    recommended); may be shorter for tiny/empty files.
    """
    kind = detect_kind(filename)  # raises ValueError on unsupported extension
    head = head_bytes or b""

    if kind == "pdf":
        if not head.startswith(_PDF_MAGIC):
            raise UploadValidationError(
                f"File {filename!r} is not a valid PDF (missing %PDF- header)."
            )
    elif kind in ("docx", "pptx"):
        if not head.startswith(_ZIP_MAGIC):
            raise UploadValidationError(
                f"File {filename!r} is not a valid {kind} "
                "(missing ZIP/OOXML container header)."
            )
    # txt / md: no magic check — any byte content is acceptable text.

    return kind
