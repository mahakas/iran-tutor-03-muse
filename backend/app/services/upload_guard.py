"""Content verification for user and admin uploads.

Declared MIME types and file extensions are client-controlled, so every upload is
checked against its real leading bytes (magic numbers) before it is stored or
parsed. Text formats must be valid UTF-8 with no NUL bytes (binary disguised as text
is rejected). Stored filenames never reuse the client name; see `safe_suffix`.
"""

from __future__ import annotations

from fastapi import HTTPException

# Magic-number signatures per kind. A kind matches when any signature matches.
_SIGNATURES: dict[str, tuple[tuple[int, bytes], ...]] = {
    "pdf": ((0, b"%PDF-"),),
    "png": ((0, b"\x89PNG\r\n\x1a\n"),),
    "jpeg": ((0, b"\xff\xd8\xff"),),
    "webp": ((0, b"RIFF"),),  # refined below: bytes 8..12 == WEBP
    "wav": ((0, b"RIFF"),),  # refined below: bytes 8..12 == WAVE
    "mp3": ((0, b"ID3"), (0, b"\xff\xfb"), (0, b"\xff\xf3"), (0, b"\xff\xf2")),
    "ogg": ((0, b"OggS"),),
    "webm": ((0, b"\x1a\x45\xdf\xa3"),),
    "m4a": ((4, b"ftyp"),),
}

# Declared extension -> acceptable kinds.
EXTENSION_KINDS: dict[str, tuple[str, ...]] = {
    ".pdf": ("pdf",),
    ".png": ("png",),
    ".jpg": ("jpeg",),
    ".jpeg": ("jpeg",),
    ".webp": ("webp",),
    ".mp3": ("mp3",),
    ".wav": ("wav",),
    ".m4a": ("m4a",),
    ".webm": ("webm",),
    ".ogg": ("ogg",),
    ".md": ("text",),
    ".markdown": ("text",),
    ".txt": ("text",),
    ".json": ("text",),
    ".html": ("text",),
    ".htm": ("text",),
}

# Declared MIME type (audio uploads in chat) -> acceptable kinds.
MIME_KINDS: dict[str, tuple[str, ...]] = {
    "audio/mpeg": ("mp3",),
    "audio/mp3": ("mp3",),
    "audio/wav": ("wav",),
    "audio/x-wav": ("wav",),
    "audio/ogg": ("ogg",),
    "audio/webm": ("webm",),
    "audio/mp4": ("m4a",),
    "audio/x-m4a": ("m4a",),
}

# Extension used for stored copies. Client suffixes are never trusted.
KIND_SUFFIX: dict[str, str] = {
    "pdf": ".pdf",
    "text": ".txt",
    "png": ".png",
    "jpeg": ".jpg",
    "webp": ".webp",
    "mp3": ".mp3",
    "wav": ".wav",
    "ogg": ".ogg",
    "webm": ".webm",
    "m4a": ".m4a",
}


def _matches_signature(data: bytes, kind: str) -> bool:
    head = data[:64]
    for offset, magic in _SIGNATURES[kind]:
        if head[offset : offset + len(magic)] == magic:
            if kind == "webp":
                return data[8:12] == b"WEBP"
            if kind == "wav":
                return data[8:12] == b"WAVE"
            return True
    return False


def _is_text(data: bytes) -> bool:
    """Valid UTF-8 without NUL bytes. Only the sample tail may be cut mid-character."""
    if b"\x00" in data[:4096]:
        return False
    sample = data[:200_000]
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError as error:
        return len(data) > len(sample) and error.start >= len(sample) - 4
    return True


def detect_kinds(data: bytes) -> set[str]:
    """Every kind whose signature matches the leading bytes (empty set = unknown)."""
    kinds = {kind for kind in _SIGNATURES if _matches_signature(data, kind)}
    if _is_text(data):
        kinds.add("text")
    return kinds


def verify_extension(filename: str, data: bytes) -> str:
    """Return the verified kind for a file whose extension is in `EXTENSION_KINDS`.

    Raises 415 when the content does not match the extension, or the extension is unknown.
    """
    import os

    ext = os.path.splitext(filename or "")[1].lower()
    allowed = EXTENSION_KINDS.get(ext)
    if not allowed:
        raise HTTPException(status_code=415, detail="فرمت فایل پشتیبانی نمی‌شود.")
    found = detect_kinds(data)
    for kind in allowed:
        if kind in found:
            return kind
    raise HTTPException(status_code=415, detail="محتوای فایل با پسوند آن هم‌خوان نیست.")


def verify_audio(declared_mime: str, data: bytes) -> str:
    """Verify chat audio against its declared MIME type; returns the verified kind."""
    allowed = MIME_KINDS.get((declared_mime or "").lower())
    if not allowed:
        raise HTTPException(status_code=415, detail="فرمت صوت پشتیبانی نمی‌شود.")
    found = detect_kinds(data)
    for kind in allowed:
        if kind in found:
            return kind
    raise HTTPException(status_code=415, detail="محتوای صوتی با فرمت اعلام‌شده هم‌خوان نیست.")


def verify_pdf(data: bytes) -> None:
    """Admin book upload: same 422 contract the PDF parser uses (message keeps 'not a valid PDF')."""
    if not _matches_signature(data, "pdf"):
        raise HTTPException(status_code=422, detail="not a valid PDF file (missing %PDF header)")


def safe_suffix(kind: str) -> str:
    """Server-chosen stored suffix for a verified kind (never the client's suffix)."""
    return KIND_SUFFIX.get(kind, ".bin")
