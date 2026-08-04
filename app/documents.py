"""Turning uploaded files into text the model can read.

Extraction happens entirely in memory. The previous version wrote every
upload into an `uploads/` folder that nothing ever cleaned up - an odd
property for a tool whose selling point is that your data stays with you.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import PdfReadError

DEFAULT_CHAR_LIMIT = 20_000

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv", ".json", ".yaml", ".yml",
    ".xml", ".html", ".htm", ".ini", ".cfg", ".toml", ".env", ".sql",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".kt", ".c", ".h", ".cpp", ".hpp",
    ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".sh", ".bash", ".zsh", ".ps1",
    ".css", ".scss", ".vue", ".svelte", ".r", ".m", ".pl", ".lua", ".dart", ".scala",
}

SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | {".pdf", ".docx"}


class UnsupportedDocument(ValueError):
    """The file cannot be turned into text."""


@dataclass(frozen=True)
class ExtractedDocument:
    name: str
    kind: str
    text: str
    chars: int
    truncated: bool
    pages: int | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "chars": self.chars,
            "truncated": self.truncated,
            "pages": self.pages,
        }

    def as_prompt_section(self) -> str:
        """How the document is handed to the model."""
        header = f"--- file: {self.name}"
        if self.pages:
            header += f" ({self.pages} pages)"
        if self.truncated:
            header += " [truncated]"
        return f"{header} ---\n{self.text}\n--- end of {self.name} ---"


def extension_of(filename: str) -> str:
    _, _, ext = filename.rpartition(".")
    return f".{ext.lower()}" if ext and ext != filename else ""


def _looks_binary(data: bytes) -> bool:
    """NUL bytes essentially never appear in text files."""
    return b"\x00" in data[:4096]


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _extract_pdf(data: bytes) -> tuple[str, int]:
    try:
        reader = PdfReader(io.BytesIO(data))
    except (PdfReadError, ValueError, OSError) as exc:
        raise UnsupportedDocument("This PDF could not be read - it may be corrupt.") from exc

    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:  # pypdf raises several types here
            raise UnsupportedDocument("This PDF is password protected.") from exc

    parts = []
    for page in reader.pages:
        try:
            # Pages without a text layer (scans) return None.
            parts.append(page.extract_text() or "")
        except Exception:  # a single broken page must not fail the upload
            parts.append("")

    return "\n\n".join(parts), len(reader.pages)


def _extract_docx(data: bytes) -> str:
    try:
        import docx  # imported lazily: only .docx uploads need it
    except ImportError as exc:
        raise UnsupportedDocument(
            "Reading .docx files needs python-docx (pip install -r requirements.txt)."
        ) from exc

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # python-docx raises loosely typed errors
        raise UnsupportedDocument("This .docx could not be read.") from exc

    blocks = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            blocks.append(" | ".join(cell.text.strip() for cell in row.cells))

    return "\n".join(block for block in blocks if block.strip())


def _pretty_csv(text: str) -> str:
    """Align CSV rows so the model sees columns instead of comma soup."""
    try:
        dialect = csv.Sniffer().sniff(text[:2000])
    except csv.Error:
        return text
    rows = list(csv.reader(io.StringIO(text), dialect))
    return "\n".join(" | ".join(cell.strip() for cell in row) for row in rows[:500])


def extract(
    filename: str, data: bytes, *, char_limit: int = DEFAULT_CHAR_LIMIT
) -> ExtractedDocument:
    """Extract text from an uploaded file.

    Raises UnsupportedDocument with a message meant for the user.
    """
    name = filename.strip() or "upload"
    ext = extension_of(name)

    if not data:
        raise UnsupportedDocument(f"'{name}' is empty.")

    pages: int | None = None

    if ext == ".pdf":
        kind = "pdf"
        text, pages = _extract_pdf(data)
        if not text.strip():
            raise UnsupportedDocument(
                f"'{name}' contains no selectable text - it is probably a scan. "
                "Run OCR on it first."
            )
    elif ext == ".docx":
        kind = "docx"
        text = _extract_docx(data)
    elif ext in TEXT_EXTENSIONS or not ext:
        if _looks_binary(data):
            raise UnsupportedDocument(f"'{name}' looks like a binary file.")
        kind = "text"
        text = _decode(data)
        if ext in {".csv", ".tsv"}:
            text = _pretty_csv(text)
        elif ext == ".json":
            # Pretty-print so the model sees structure, but keep the raw text
            # if it does not parse.
            with contextlib.suppress(json.JSONDecodeError):
                text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    else:
        supported = ", ".join(sorted({".pdf", ".docx", ".txt", ".md", ".csv", ".json"}))
        raise UnsupportedDocument(f"'{ext}' files are not supported. Try: {supported}, code files.")

    text = text.replace("\r\n", "\n").strip()
    if not text:
        raise UnsupportedDocument(f"No text could be extracted from '{name}'.")

    truncated = len(text) > char_limit
    if truncated:
        text = text[:char_limit].rstrip()

    return ExtractedDocument(
        name=name,
        kind=kind,
        text=text,
        chars=len(text),
        truncated=truncated,
        pages=pages,
    )
