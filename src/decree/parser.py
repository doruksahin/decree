"""
Document file parser — read/write MADR v4 and other doc type files via python-frontmatter + pydantic.

This is the ONLY module that touches document files on disk.
All commands go through parser, never raw file I/O.
"""

from datetime import date
from pathlib import Path
from typing import Any

import frontmatter
from pydantic import (
    BaseModel,
    Field,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_validator,
)

from .config import DATE_FORMAT
from .doctypes import ADR_DEFAULT
from .identity import require_doc_id


class DocFrontmatter(BaseModel):
    """Validated document frontmatter. Parsed from YAML, not constructed manually."""

    id: str | None = None
    status: str
    date: date
    supersedes: str | None = None
    superseded_by: str | None = Field(None, alias="superseded-by")
    deciders: list[str] | None = None
    consulted: list[str] | None = None
    informed: list[str] | None = None
    references: list[str] | None = None
    attachments: list[str] | None = None
    governs: list[str] | None = None

    model_config = {"populate_by_name": True}

    @field_serializer("date")
    @classmethod
    def serialize_date(cls, v: date) -> str:
        return v.strftime(DATE_FORMAT)

    @field_validator("status")
    @classmethod
    def status_must_be_valid(cls, v: str, info: ValidationInfo) -> str:
        ctx = info.context or {} if info else {}
        doc_type = ctx.get("doc_type") if ctx else None
        valid = doc_type.statuses if doc_type is not None else ADR_DEFAULT.statuses
        if v not in valid:
            raise ValueError(f"Invalid status '{v}'. Must be one of: {valid}")
        return v

    @field_validator("id")
    @classmethod
    def id_format(cls, v: str | None, info: ValidationInfo) -> str | None:
        if v is None:
            return v
        ctx = info.context or {} if info else {}
        doc_type = ctx.get("doc_type") if ctx else None
        effective_type = doc_type if doc_type is not None else ADR_DEFAULT
        normalized = v.strip().upper()
        return require_doc_id(normalized, prefix=effective_type.prefix)

    @field_validator("supersedes", "superseded_by")
    @classmethod
    def ref_format(cls, v: str | None, info: ValidationInfo) -> str | None:
        if v is None:
            return v
        ctx = info.context or {} if info else {}
        doc_type = ctx.get("doc_type") if ctx else None
        pattern = doc_type.ref_re if doc_type is not None else ADR_DEFAULT.ref_re
        if not pattern.match(v):
            if doc_type is not None:
                fmt = f"{doc_type.prefix}-ULID"
                raise ValueError(f"Reference '{v}' must match format {fmt}")
            raise ValueError(f"ADR reference '{v}' must match format ADR-ULID")
        return v

    @field_validator("references")
    @classmethod
    def references_format(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        return [require_doc_id(ref) for ref in v]

    @field_validator("governs")
    @classmethod
    def governs_syntax(cls, v: list[str] | None) -> list[str] | None:
        """Per SPEC-01KT22NMRXFWNE61NSETKATHBA: each entry is `<path>` or `<path>#<symbol>` (repo-relative path)."""
        if v is None:
            return v
        for entry in v:
            if not isinstance(entry, str):
                raise ValueError(f"governs entries must be strings; got {type(entry).__name__}: {entry!r}")
            path_part = entry.split("#", 1)[0]
            if not path_part:
                raise ValueError(f"governs entry has empty path: {entry!r}")
            if path_part.startswith("/"):
                raise ValueError(f"governs path must be repo-relative (no leading '/'): {entry!r}")
            if ".." in path_part.split("/"):
                raise ValueError(f"governs path must not contain '..' segments: {entry!r}")
        return v

    def evolve(self, doc_type=None, **overrides) -> "DocFrontmatter":
        """Create a new instance with selected fields changed."""
        data = self.model_dump(by_alias=True)
        data.update(overrides)
        context = {"doc_type": doc_type} if doc_type is not None else None
        return DocFrontmatter.model_validate(data, context=context)

    @model_validator(mode="wrap")
    @classmethod
    def status_field_invariants(cls, values: Any, handler: Any, info: ValidationInfo) -> "DocFrontmatter":
        instance = handler(values)
        ctx = info.context or {} if info else {}
        doc_type = ctx.get("doc_type") if ctx else None
        if doc_type is not None:
            field_reqs = doc_type.status_field_requirements
        else:
            field_reqs = ADR_DEFAULT.status_field_requirements
        required = field_reqs.get(instance.status, ())
        for field_name in required:
            attr = field_name.replace("-", "_")
            if getattr(instance, attr, None) is None:
                raise ValueError(f"Status '{instance.status}' requires field '{field_name}'")
        return instance


class DocDocument:
    """A parsed document file: validated frontmatter + markdown body."""

    def __init__(
        self,
        path: Path,
        meta: DocFrontmatter,
        body: str,
        doc_type=None,
        raw_metadata: dict | None = None,
    ):
        self.path = path
        self.meta = meta
        self.body = body
        self.doc_type = doc_type
        self.raw_metadata: dict = raw_metadata if raw_metadata is not None else {}

    @property
    def doc_id(self) -> str:
        if self.meta.id is None:
            raise ValueError(f"{self.path}: missing required frontmatter field 'id'")
        return self.meta.id

    @property
    def number(self) -> int:
        raise ValueError("Numeric document numbers are not part of the canonical identity model")

    @property
    def title(self) -> str:
        for line in self.body.splitlines():
            if line.startswith("# "):
                title = line.lstrip("# ").strip()
                prefix = f"{self.doc_id} "
                if title.startswith(prefix):
                    return title[len(prefix) :]
                return title
        return self.path.stem

    @property
    def sections(self) -> list[str]:
        return [line.lstrip("# ").strip() for line in self.body.splitlines() if line.startswith("## ")]

    @property
    def missing_sections(self) -> list[str]:
        required = self.doc_type.required_sections if self.doc_type is not None else ADR_DEFAULT.required_sections
        present = set(self.sections)
        return [s for s in required if s not in present]


def load(path: Path, doc_type=None) -> DocDocument:
    """Load a document file."""
    post = frontmatter.load(str(path))
    context = {"doc_type": doc_type} if doc_type is not None else None
    meta = DocFrontmatter.model_validate(post.metadata, context=context)
    effective_type = doc_type if doc_type is not None else ADR_DEFAULT
    if meta.id is None:
        raise ValueError(f"{path}: missing required frontmatter field 'id'")
    if not effective_type.ref_re.match(meta.id):
        raise ValueError(f"{path}: id '{meta.id}' must match {effective_type.prefix}-ULID")
    expected_prefix = f"{meta.id.lower()}-"
    if not path.name.startswith(expected_prefix) or path.suffix != ".md":
        raise ValueError(f"{path}: filename must start with '{expected_prefix}'")
    return DocDocument(
        path=path,
        meta=meta,
        body=post.content,
        doc_type=doc_type,
        raw_metadata=post.metadata,
    )


def load_all(*, strict: bool = True, doc_type) -> list[DocDocument]:
    """Load all docs for a single type."""
    from .config import get_project_root
    from .log import error as log_error

    type_dir = get_project_root() / doc_type.dir
    paths = sorted(p for p in type_dir.glob("*.md") if p.name != "index.md")
    docs = []
    for p in paths:
        try:
            docs.append(load(p, doc_type=doc_type))
        except Exception as e:
            if strict:
                raise
            log_error("load", f"skipping {p.name}: {e}")
    return docs


def load_all_types(*, strict: bool = True) -> list[DocDocument]:
    """Load all documents across all configured types."""
    from .config import get_project_root, load_doc_types
    from .log import error as log_error

    all_docs = []
    for dt in load_doc_types():
        type_dir = get_project_root() / dt.dir
        if not type_dir.exists():
            continue
        paths = sorted(p for p in type_dir.glob("*.md") if p.name != "index.md")
        for p in paths:
            try:
                all_docs.append(load(p, doc_type=dt))
            except Exception as e:
                if strict:
                    raise
                log_error("load", f"skipping {p.name}: {e}")
    return all_docs


def find_by_id(doc_id: str) -> DocDocument:
    """Find a document by ID, auto-detecting type from the ID prefix."""
    from .config import find_doc_type, get_project_root

    doc_type = find_doc_type(doc_id)
    type_dir = get_project_root() / doc_type.dir
    matches = list(type_dir.glob(f"{doc_id.lower()}-*.md"))

    if not matches:
        raise FileNotFoundError(f"{doc_id} not found")
    if len(matches) > 1:
        raise ValueError(f"Multiple files match {doc_id}: {[m.name for m in matches]}")
    return load(matches[0], doc_type=doc_type)


def save(doc: DocDocument) -> None:
    meta = doc.meta.model_dump(by_alias=True, exclude_none=True, mode="json")
    meta = {k: v for k, v in meta.items() if v != []}
    post = frontmatter.Post(doc.body, **meta)
    content = frontmatter.dumps(post)
    doc.path.write_text(content.rstrip() + "\n")
