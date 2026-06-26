"""Bucket path helpers for physical document organization."""

from pathlib import Path

from decree.config import SLUG_RE

ROOT_BUCKET = "."
GENERATED_BUCKET_SEGMENTS = frozenset({"reports"})


class BucketPathError(ValueError):
    """Raised when a user-supplied bucket path is unsafe or unsupported."""


def normalize_bucket(bucket: str | None) -> Path:
    """Validate and normalize a CLI bucket path relative to a document type dir."""
    if bucket is None:
        return Path()

    raw = bucket.strip()
    if raw in ("", ROOT_BUCKET):
        return Path()
    if raw.startswith(("/", "\\")):
        raise BucketPathError("bucket path must be relative")
    if "\\" in raw:
        raise BucketPathError("bucket path must use '/' separators")
    if ":" in raw:
        raise BucketPathError("bucket path must not contain ':'")

    parts = raw.split("/")
    if any(part == "" for part in parts):
        raise BucketPathError("bucket path must not contain empty segments")

    for part in parts:
        if part in (".", ".."):
            raise BucketPathError("bucket path must not contain '.' or '..' segments")
        if part.startswith("."):
            raise BucketPathError("bucket path must not contain hidden segments")
        if part in GENERATED_BUCKET_SEGMENTS:
            raise BucketPathError(f"bucket path must not contain generated segment '{part}'")
        if not SLUG_RE.match(part):
            raise BucketPathError("bucket segments must be lowercase slugs")

    return Path(*parts)


def bucket_for_path(path: Path, type_dir: Path) -> str:
    """Return the bucket string for a document path under a configured type dir."""
    rel_parent = path.parent.relative_to(type_dir)
    if rel_parent == Path("."):
        return ROOT_BUCKET
    return rel_parent.as_posix()


def bucket_matches(path: Path, type_dir: Path, bucket: Path) -> bool:
    """Return True when a document path belongs exactly to the normalized bucket."""
    return path.parent.relative_to(type_dir) == bucket
