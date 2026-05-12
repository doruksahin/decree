"""SQLite provenance-index for decree.

Per ADR-0002 Option C (hybrid): this index is a *derived read-cache*.
Frontmatter remains the authoring source of truth; the index is rebuilt
from it deterministically.

Schema is defined and evolved via `sqlite-utils` so we don't hand-roll
CREATE TABLE / ALTER TABLE plumbing.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import sqlite_utils

SCHEMA_VERSION = 1
INDEX_DIR_NAME = ".decree"
INDEX_FILENAME = "index.sqlite"


# ── Result types ─────────────────────────────────────────────


@dataclass(frozen=True)
class RebuildStats:
    duration_ms: int
    decisions: int
    refs: int
    governs: int
    acceptance_criteria: int
    fts_indexed: int


@dataclass(frozen=True)
class IndexStatus:
    exists: bool
    db_path: Path
    schema_version: int | None
    last_rebuilt_at: str | None
    row_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class DriftFinding:
    decision_id: str
    kind: str         # "body_hash_mismatch" / "missing_in_index" / "stale_in_index"
    detail: str


# ── IndexDB ─────────────────────────────────────────────────


class IndexDB:
    """Wrapper around sqlite-utils.Database for the decree provenance index.

    Lifetimes: instantiate once per command invocation. The wrapped Database
    holds the SQLite connection, which is closed when this object is garbage-
    collected. Tests can pass an explicit path to use a tmp_path location.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite_utils.Database(str(db_path))

    # ── Schema setup ────────────────────────────────────────

    def init_schema(self) -> None:
        """Create tables, indexes, and FTS if they don't already exist."""

        # decisions: one row per parsed document
        if "decisions" not in self.db.table_names():
            self.db["decisions"].create(  # type: ignore[attr-defined]
                {
                    "id": str,
                    "type": str,
                    "status": str,
                    "title": str,
                    "path": str,
                    "date": str,
                    "body_hash": str,
                    "indexed_at": str,
                    "raw_metadata": str,
                },
                pk="id",
            )
            self.db["decisions"].create_index(["type"], if_not_exists=True)
            self.db["decisions"].create_index(["status"], if_not_exists=True)
            self.db["decisions"].create_index(["path"], if_not_exists=True, unique=True)

        # refs: cross-document references
        if "refs" not in self.db.table_names():
            self.db["refs"].create(  # type: ignore[attr-defined]
                {
                    "from_id": str,
                    "to_id": str,
                    "kind": str,
                },
                pk=("from_id", "to_id", "kind"),
            )
            self.db["refs"].create_index(["to_id"], if_not_exists=True)
            self.db["refs"].create_index(["from_id"], if_not_exists=True)
            self.db["refs"].create_index(["kind"], if_not_exists=True)

        # governs: file paths/symbols a decision governs
        if "governs" not in self.db.table_names():
            self.db["governs"].create(  # type: ignore[attr-defined]
                {
                    "decision_id": str,
                    "path": str,
                    "symbol": str,
                    "order_index": int,
                },
                pk=("decision_id", "path", "symbol"),
            )
            self.db["governs"].create_index(["path"], if_not_exists=True)

        # acceptance_criteria: checkboxes parsed from the body
        if "acceptance_criteria" not in self.db.table_names():
            self.db["acceptance_criteria"].create(  # type: ignore[attr-defined]
                {
                    "decision_id": str,
                    "section_title": str,
                    "section_level": int,
                    "text": str,
                    "done": int,
                    "deferred": int,
                    "order_index": int,
                },
                pk=("decision_id", "order_index"),
            )
            self.db["acceptance_criteria"].create_index(["decision_id"], if_not_exists=True)

        # commits: SPEC↔commit links, populated by future SPEC-006
        if "commits" not in self.db.table_names():
            self.db["commits"].create(  # type: ignore[attr-defined]
                {
                    "sha": str,
                    "decision_id": str,
                    "trailer_kind": str,
                    "summary": str,
                    "committed_at": str,
                },
                pk=("sha", "decision_id", "trailer_kind"),
            )
            self.db["commits"].create_index(["decision_id"], if_not_exists=True)

        # index_meta: key-value bookkeeping
        if "index_meta" not in self.db.table_names():
            self.db["index_meta"].create(  # type: ignore[attr-defined]
                {"key": str, "value": str},
                pk="key",
            )

        # FTS5 virtual table over title + body of decisions.
        # We create it manually rather than via `enable_fts` because `body`
        # is not a real column on `decisions` (the body lives only in FTS).
        existing_tables = self.db.table_names()
        if "decisions_fts" not in existing_tables:
            self.db.conn.execute(  # type: ignore[attr-defined]
                "CREATE VIRTUAL TABLE decisions_fts USING fts5("
                "id UNINDEXED, title, body, tokenize='porter unicode61')"
            )

    # ── Mutation: rebuild from corpus ───────────────────────

    def rebuild(self, project_root: Path) -> RebuildStats:
        """Full rebuild from frontmatter + body. Idempotent on content hash."""
        from decree.commands.report import (
            DEFAULT_DEFERRED_SECTION_PATTERNS,
            _parse_checkboxes_by_section,
        )
        from decree.parser import load_all_types

        start = time.monotonic()
        self.init_schema()

        # Wipe markdown-derived tables. Do NOT wipe `commits` (owned by SPEC-006).
        with self.db.conn:  # type: ignore[attr-defined]
            self.db.conn.execute("DELETE FROM decisions")  # type: ignore[attr-defined]
            self.db.conn.execute("DELETE FROM refs")  # type: ignore[attr-defined]
            self.db.conn.execute("DELETE FROM governs")  # type: ignore[attr-defined]
            self.db.conn.execute("DELETE FROM acceptance_criteria")  # type: ignore[attr-defined]
            # body column is FTS-only; sqlite-utils stores FTS in a sibling table that
            # we'll rebuild at the end.

        docs = load_all_types(strict=False)
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

        decisions_rows: list[dict] = []
        body_by_id: dict[str, str] = {}
        refs_rows: list[dict] = []
        governs_rows: list[dict] = []
        ac_rows: list[dict] = []

        for doc in docs:
            type_name = doc.doc_type.name if doc.doc_type else "adr"
            body_hash = hashlib.sha256(doc.body.encode("utf-8")).hexdigest()
            raw_md = doc.raw_metadata or {}
            try:
                rel_path = str(doc.path.relative_to(project_root))
            except ValueError:
                rel_path = str(doc.path)

            decisions_rows.append(
                {
                    "id": doc.doc_id,
                    "type": type_name,
                    "status": doc.meta.status,
                    "title": doc.title,
                    "path": rel_path,
                    "date": doc.meta.date.isoformat() if hasattr(doc.meta.date, "isoformat") else str(doc.meta.date),
                    "body_hash": body_hash,
                    "indexed_at": now_iso,
                    "raw_metadata": json.dumps(raw_md, default=str, sort_keys=True),
                }
            )
            body_by_id[doc.doc_id] = doc.body

            # refs: references / supersedes / superseded-by
            for ref in doc.meta.references or []:
                refs_rows.append({"from_id": doc.doc_id, "to_id": ref, "kind": "references"})
            if doc.meta.supersedes:
                refs_rows.append({"from_id": doc.doc_id, "to_id": doc.meta.supersedes, "kind": "supersedes"})
            if doc.meta.superseded_by:
                refs_rows.append({"from_id": doc.doc_id, "to_id": doc.meta.superseded_by, "kind": "superseded-by"})

            # governs: typed field on DocFrontmatter (SPEC-004). Pydantic already
            # validated syntax at load time; here we just split on `#` and emit rows.
            for i, entry in enumerate(doc.meta.governs or []):
                path_part, _, symbol_part = entry.partition("#")
                governs_rows.append(
                    {
                        "decision_id": doc.doc_id,
                        "path": path_part,
                        "symbol": symbol_part,
                        "order_index": i,
                    }
                )

            # acceptance criteria with primary/deferred split (reused from SPEC-002)
            parsed = _parse_checkboxes_by_section(doc.body, DEFAULT_DEFERRED_SECTION_PATTERNS)
            order = 0
            for section in parsed.primary:
                for item in section.items:
                    ac_rows.append(
                        {
                            "decision_id": doc.doc_id,
                            "section_title": section.title,
                            "section_level": section.level,
                            "text": item.text,
                            "done": 1 if item.done else 0,
                            "deferred": 0,
                            "order_index": order,
                        }
                    )
                    order += 1
            for section in parsed.deferred:
                for item in section.items:
                    ac_rows.append(
                        {
                            "decision_id": doc.doc_id,
                            "section_title": section.title,
                            "section_level": section.level,
                            "text": item.text,
                            "done": 1 if item.done else 0,
                            "deferred": 1,
                            "order_index": order,
                        }
                    )
                    order += 1

        # Bulk insert
        if decisions_rows:
            self.db["decisions"].insert_all(decisions_rows, replace=True)
        if refs_rows:
            self.db["refs"].insert_all(refs_rows, replace=True)
        if governs_rows:
            self.db["governs"].insert_all(governs_rows, replace=True)
        if ac_rows:
            self.db["acceptance_criteria"].insert_all(ac_rows, replace=True)

        # FTS: populate manually since we disabled auto-triggers
        # decisions_fts(id UNINDEXED, title, body) — we need to push title+body in.
        self.db.conn.execute("DELETE FROM decisions_fts")  # type: ignore[attr-defined]
        for d in decisions_rows:
            self.db.conn.execute(  # type: ignore[attr-defined]
                "INSERT INTO decisions_fts (id, title, body) VALUES (?, ?, ?)",
                (d["id"], d["title"], body_by_id.get(d["id"], "")),
            )

        # Meta
        meta_rows = [
            {"key": "schema_version", "value": str(SCHEMA_VERSION)},
            {"key": "last_rebuilt_at", "value": now_iso},
            {"key": "corpus_root", "value": str(project_root)},
        ]
        self.db["index_meta"].insert_all(meta_rows, replace=True)
        self.db.conn.commit()  # type: ignore[attr-defined]

        return RebuildStats(
            duration_ms=int((time.monotonic() - start) * 1000),
            decisions=len(decisions_rows),
            refs=len(refs_rows),
            governs=len(governs_rows),
            acceptance_criteria=len(ac_rows),
            fts_indexed=len(decisions_rows),
        )

    # ── Read-only: status ───────────────────────────────────

    def status(self) -> IndexStatus:
        """Return schema version, last-rebuilt-at, row counts. Cheap (<50ms).

        Reports `exists=False` if either the file was never created OR the file
        exists but has not yet been initialized with `init_schema` (no
        `index_meta` table). The constructor opens the SQLite file eagerly,
        which would otherwise misreport "exists=True" before any rebuild.
        """
        if not self.db_path.exists():
            return IndexStatus(exists=False, db_path=self.db_path, schema_version=None, last_rebuilt_at=None)

        if "index_meta" not in self.db.table_names():
            return IndexStatus(exists=False, db_path=self.db_path, schema_version=None, last_rebuilt_at=None)

        meta = {row["key"]: row["value"] for row in self.db["index_meta"].rows}
        if not meta:
            # Schema exists but has not been populated by a rebuild yet.
            return IndexStatus(exists=False, db_path=self.db_path, schema_version=None, last_rebuilt_at=None)

        counts: dict[str, int] = {}
        for table in ("decisions", "refs", "governs", "acceptance_criteria", "commits"):
            if table in self.db.table_names():
                counts[table] = self.db[table].count
            else:
                counts[table] = 0

        schema_v = int(meta.get("schema_version", 0)) or None
        return IndexStatus(
            exists=True,
            db_path=self.db_path,
            schema_version=schema_v,
            last_rebuilt_at=meta.get("last_rebuilt_at"),
            row_counts=counts,
        )

    # ── Drift detection ─────────────────────────────────────

    def verify(self, project_root: Path) -> list[DriftFinding]:
        """Compare on-disk frontmatter against the index. Reports drift; does not mutate."""
        from decree.parser import load_all_types

        findings: list[DriftFinding] = []
        if not self.db_path.exists() or "decisions" not in self.db.table_names():
            findings.append(DriftFinding(decision_id="", kind="index_missing", detail=str(self.db_path)))
            return findings

        # Map indexed body_hash by id
        indexed: dict[str, str] = {row["id"]: row["body_hash"] for row in self.db["decisions"].rows}
        seen_on_disk: set[str] = set()

        for doc in load_all_types(strict=False):
            seen_on_disk.add(doc.doc_id)
            body_hash = hashlib.sha256(doc.body.encode("utf-8")).hexdigest()
            if doc.doc_id not in indexed:
                findings.append(
                    DriftFinding(
                        decision_id=doc.doc_id,
                        kind="missing_in_index",
                        detail=f"on disk but not in index ({doc.path.name})",
                    )
                )
                continue
            if indexed[doc.doc_id] != body_hash:
                findings.append(
                    DriftFinding(
                        decision_id=doc.doc_id,
                        kind="body_hash_mismatch",
                        detail=f"index hash={indexed[doc.doc_id][:8]}, disk hash={body_hash[:8]}",
                    )
                )

        for indexed_id in indexed:
            if indexed_id not in seen_on_disk:
                findings.append(
                    DriftFinding(
                        decision_id=indexed_id,
                        kind="stale_in_index",
                        detail="in index but not on disk",
                    )
                )

        return findings


# ── Path resolution ─────────────────────────────────────────


def default_db_path(project_root: Path) -> Path:
    """The canonical location of the index file inside a project."""
    return project_root / INDEX_DIR_NAME / INDEX_FILENAME
