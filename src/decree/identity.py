"""Document identity helpers.

Canonical decree IDs are stored in frontmatter as ``TYPE-ULID``. This module
owns generation, validation, and filename construction so parser and commands
do not duplicate identity rules.
"""

from __future__ import annotations

import re
import secrets
import time

CROCKFORD32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ULID_PATTERN = r"[0-7][0-9A-HJKMNP-TV-Z]{25}"
ULID_RE = re.compile(rf"^{ULID_PATTERN}$")
DOC_ID_RE = re.compile(rf"^(?P<prefix>[A-Z][A-Z0-9]*)-(?P<ulid>{ULID_PATTERN})$")
SPRINT_ID_RE = re.compile(rf"^SPRINT-(?P<ulid>{ULID_PATTERN})$")

_LOWER_ULID_PATTERN = ULID_PATTERN.lower()
_DOC_FILENAME_RE = re.compile(rf"^(?P<prefix>[a-z][a-z0-9]*)-(?P<ulid>{_LOWER_ULID_PATTERN})-(?P<slug>.+)\.md$")


def generate_ulid(*, timestamp_ms: int | None = None, random_bits: int | None = None) -> str:
    """Generate a ULID string.

    ULID layout is 48 bits of millisecond timestamp plus 80 bits of randomness,
    encoded as 26 Crockford Base32 characters.
    """
    ts = int(time.time_ns() // 1_000_000) if timestamp_ms is None else timestamp_ms
    if ts < 0 or ts >= 2**48:
        raise ValueError("ULID timestamp_ms must fit in 48 bits")

    rand = secrets.randbits(80) if random_bits is None else random_bits
    if rand < 0 or rand >= 2**80:
        raise ValueError("ULID random_bits must fit in 80 bits")

    return _encode_crockford((ts << 80) | rand, 26)


def generate_doc_id(prefix: str) -> str:
    """Generate a canonical ``TYPE-ULID`` document ID."""
    cleaned = prefix.strip().upper()
    if not re.match(r"^[A-Z][A-Z0-9]*$", cleaned):
        raise ValueError(f"invalid document prefix: {prefix!r}")
    return f"{cleaned}-{generate_ulid()}"


def generate_sprint_id() -> str:
    """Generate a canonical ``SPRINT-ULID`` sprint ID."""
    return f"SPRINT-{generate_ulid()}"


def is_doc_id(value: str, *, prefix: str | None = None) -> bool:
    """Return True when ``value`` is a valid canonical document ID."""
    match = DOC_ID_RE.match(value)
    if not match:
        return False
    if match.group("prefix") == "SPRINT":
        return False
    return not (prefix is not None and match.group("prefix") != prefix.upper())


def require_doc_id(value: str, *, prefix: str | None = None) -> str:
    """Validate and normalize a document ID or raise ``ValueError``."""
    normalized = value.strip().upper()
    if not is_doc_id(normalized, prefix=prefix):
        expected = f"{prefix.upper()}-ULID" if prefix else "TYPE-ULID"
        raise ValueError(f"Document ID '{value}' must match {expected}")
    return normalized


def is_sprint_id(value: str) -> bool:
    """Return True when ``value`` is a valid canonical sprint ID."""
    return bool(SPRINT_ID_RE.match(value))


def require_sprint_id(value: str) -> str:
    """Validate and normalize a sprint ID or raise ``ValueError``."""
    normalized = value.strip().upper()
    if not is_sprint_id(normalized):
        raise ValueError(f"Sprint ID '{value}' must match SPRINT-ULID")
    return normalized


def filename_for_doc_id(doc_id: str, slug: str) -> str:
    """Build the canonical markdown filename for a document ID and slug."""
    valid_id = require_doc_id(doc_id)
    cleaned_slug = slug.strip().lower()
    if not cleaned_slug:
        raise ValueError("slug must not be empty")
    return f"{valid_id.lower()}-{cleaned_slug}.md"


def doc_id_from_filename(filename: str) -> str | None:
    """Return the canonical ID encoded in a canonical filename, if any."""
    match = _DOC_FILENAME_RE.match(filename)
    if not match:
        return None
    return f"{match.group('prefix').upper()}-{match.group('ulid').upper()}"


def filename_matches_doc_id(filename: str, doc_id: str) -> bool:
    """Return True when ``filename`` is the canonical filename for ``doc_id``."""
    return doc_id_from_filename(filename) == require_doc_id(doc_id)


def _encode_crockford(value: int, length: int) -> str:
    chars: list[str] = []
    for _ in range(length):
        chars.append(CROCKFORD32[value & 31])
        value >>= 5
    if value:
        raise ValueError("value does not fit requested Crockford Base32 length")
    return "".join(reversed(chars))
