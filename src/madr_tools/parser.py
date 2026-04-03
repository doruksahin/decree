"""
ADR file parser — read/write MADR v4 files via python-frontmatter + pydantic.

This is the ONLY module that touches ADR files on disk.
All commands go through parser, never raw file I/O.
"""

import frontmatter
from datetime import date
from pathlib import Path
from pydantic import BaseModel, Field, field_serializer, field_validator, model_validator

from .config import (
    STATUSES, STATUS_FIELD_REQUIREMENTS,
    ADR_REF_RE, DATE_FORMAT, FILENAME_RE,
    get_adr_dir, get_required_sections,
)


class ADRFrontmatter(BaseModel):
    """Validated MADR v4 frontmatter. Parsed from YAML, not constructed manually."""

    status: str
    date: date
    supersedes: str | None = None
    superseded_by: str | None = Field(None, alias="superseded-by")
    deciders: list[str] | None = None
    consulted: list[str] | None = None
    informed: list[str] | None = None

    model_config = {"populate_by_name": True}

    @field_serializer("date")
    @classmethod
    def serialize_date(cls, v: date) -> str:
        return v.strftime(DATE_FORMAT)

    @field_validator("status")
    @classmethod
    def status_must_be_valid(cls, v: str) -> str:
        if v not in STATUSES:
            raise ValueError(f"Invalid status '{v}'. Must be one of: {STATUSES}")
        return v

    @field_validator("supersedes", "superseded_by")
    @classmethod
    def adr_ref_format(cls, v: str | None) -> str | None:
        if v is not None and not ADR_REF_RE.match(v):
            raise ValueError(f"ADR reference '{v}' must match format ADR-NNNN")
        return v

    def evolve(self, **overrides) -> "ADRFrontmatter":
        """Create a new instance with selected fields changed."""
        data = self.model_dump(by_alias=True)
        data.update(overrides)
        return ADRFrontmatter(**data)

    @model_validator(mode="after")
    def status_field_invariants(self) -> "ADRFrontmatter":
        required = STATUS_FIELD_REQUIREMENTS.get(self.status, ())
        for field_name in required:
            attr = field_name.replace("-", "_")
            if getattr(self, attr, None) is None:
                raise ValueError(
                    f"Status '{self.status}' requires field '{field_name}'"
                )
        return self


class ADRDocument:
    """A parsed ADR file: validated frontmatter + markdown body."""

    def __init__(self, path: Path, meta: ADRFrontmatter, body: str):
        self.path = path
        self.meta = meta
        self.body = body

    @property
    def adr_id(self) -> str:
        match = FILENAME_RE.match(self.path.name)
        if not match:
            raise ValueError(f"Invalid ADR filename: {self.path.name}")
        return f"ADR-{match.group(1)}"

    @property
    def number(self) -> int:
        match = FILENAME_RE.match(self.path.name)
        if not match:
            raise ValueError(f"Invalid ADR filename: {self.path.name}")
        return int(match.group(1))

    @property
    def title(self) -> str:
        for line in self.body.splitlines():
            if line.startswith("# "):
                return line.lstrip("# ").strip()
        return self.path.stem

    @property
    def sections(self) -> list[str]:
        return [
            line.lstrip("# ").strip()
            for line in self.body.splitlines()
            if line.startswith("## ")
        ]

    @property
    def missing_sections(self) -> list[str]:
        required = get_required_sections()
        present = set(self.sections)
        return [s for s in required if s not in present]


def load(path: Path) -> ADRDocument:
    post = frontmatter.load(str(path))
    meta = ADRFrontmatter(**post.metadata)
    return ADRDocument(path=path, meta=meta, body=post.content)


def load_all(*, strict: bool = True) -> list[ADRDocument]:
    import sys
    adr_dir = get_adr_dir()
    paths = sorted(p for p in adr_dir.glob("[0-9]*.md") if FILENAME_RE.match(p.name))
    docs = []
    for p in paths:
        try:
            docs.append(load(p))
        except Exception as e:
            if strict:
                raise
            print(f"Warning: skipping {p.name}: {e}", file=sys.stderr)
    return docs


def find_by_id(adr_id: str) -> ADRDocument:
    if not ADR_REF_RE.match(adr_id):
        raise ValueError(f"Invalid ADR ID format: '{adr_id}'. Expected ADR-NNNN.")
    number = adr_id.split("-")[1]  # "ADR-0001" -> "0001"
    adr_dir = get_adr_dir()
    matches = list(adr_dir.glob(f"{number}-*.md"))
    if not matches:
        raise FileNotFoundError(f"{adr_id} not found in {adr_dir}")
    if len(matches) > 1:
        raise ValueError(f"Multiple files match {adr_id}: {[m.name for m in matches]}")
    return load(matches[0])


def next_adr_number() -> int:
    adr_dir = get_adr_dir()
    existing = [
        int(m.group(1))
        for p in adr_dir.glob("[0-9]*.md")
        if (m := FILENAME_RE.match(p.name))
    ]
    return max(existing, default=0) + 1


def save(doc: ADRDocument) -> None:
    meta = doc.meta.model_dump(by_alias=True, exclude_none=True, mode="json")
    meta = {k: v for k, v in meta.items() if v != []}
    post = frontmatter.Post(doc.body, **meta)
    content = frontmatter.dumps(post)
    doc.path.write_text(content.rstrip() + "\n")
