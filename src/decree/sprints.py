"""Sprint directory store (v2) — model, validation, and document scoping.

Storage layout (schema ``decree.sprints.v2``)::

    decree/sprints/
      state.yaml                # changes only at init/pause/resume/rollover
      live/<DOC-ID>.yaml        # one file per live membership
      closed/<SPRINT-ID>.yaml   # one append-only archive per closed sprint

Every write path touches exactly one file. State transitions (init, pause,
resume, rollover) compose multiple single-file writes under an advisory
``fcntl`` lock. Live scope=active items record no sprint id: an item belongs
to whichever sprint is active when it folds into ``closed/``.
"""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from decree.checklists import parse_checkboxes_by_section
from decree.commands.report import load_report_config
from decree.config import get_project_root
from decree.identity import generate_sprint_id, require_doc_id, require_sprint_id

SPRINTS_REL_PATH = Path("decree/sprints")
STATE_REL_PATH = SPRINTS_REL_PATH / "state.yaml"
LIVE_REL_PATH = SPRINTS_REL_PATH / "live"
CLOSED_REL_PATH = SPRINTS_REL_PATH / "closed"
# v1 monolith path — kept only for detection and `decree migrate sprint-ledger`.
LEDGER_REL_PATH = SPRINTS_REL_PATH / "ledger.yaml"
SCHEMA = "decree.sprints.v2"
MODE_ENABLED = "enabled"
BACKLOG_WARN_AFTER_DAYS = 30

ITEM_KINDS = {"execution", "planning"}
LIVE_SCOPES = {"active", "backlog", "draft_pool"}
OUTCOME_KINDS = {"completed", "carried_over", "deferred", "dropped", "superseded"}
# Mid-sprint outcomes on live items; other kinds are rollover-only.
LIVE_OUTCOME_KINDS = {"completed", "dropped"}
OUTCOMES_REQUIRING_REASON = {"carried_over", "deferred", "dropped", "superseded"}

V1_DETECTED_MESSAGE = "sprint ledger v1 detected; run `decree migrate sprint-ledger`"
NOT_ENABLED_MESSAGE = 'sprint mode is not enabled; run `decree sprint init "Sprint 1"`'


class SprintLedgerError(ValueError):
    """Raised when the sprint store cannot be parsed or a transition is invalid."""


@dataclass(frozen=True)
class SprintState:
    """Contents of state.yaml — the only file rewritten by lifecycle transitions."""

    schema: str
    mode: str
    state: str
    active: dict[str, str] | None = None
    paused: dict[str, Any] | None = None

    @classmethod
    def from_raw(cls, raw: Any) -> SprintState:
        data = _expect_mapping(raw, "state")
        active = data.get("active")
        if active is not None:
            active_data = _expect_mapping(active, "state.active")
            active = {
                "id": str(active_data.get("id", "")).strip().upper(),
                "name": str(active_data.get("name", "")).strip(),
                "started": (
                    _date_str(active_data.get("started", ""), "state.active.started")
                    if active_data.get("started")
                    else ""
                ),
            }
        paused = data.get("paused")
        if paused is not None:
            paused_data = _expect_mapping(paused, "state.paused")
            paused = {
                "since": _date_str(paused_data.get("since", ""), "state.paused.since")
                if paused_data.get("since")
                else "",
                "reason": str(paused_data.get("reason", "")).strip(),
            }
        return cls(
            schema=str(data.get("schema", "")).strip(),
            mode=str(data.get("mode", "")).strip(),
            state=str(data.get("state", "")).strip(),
            active=active,
            paused=paused,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "mode": self.mode,
            "state": self.state,
            "active": self.active,
            "paused": self.paused,
        }


@dataclass(frozen=True)
class LiveItem:
    """Contents of one live/<DOC-ID>.yaml membership file."""

    document: str
    scope: str
    kind: str = "execution"
    source: str = "manual"
    added: str = field(default_factory=lambda: _today())
    since: str | None = None
    reason: str | None = None
    review_after: str | None = None
    carryover_from: str | None = None
    outcome: dict[str, Any] | None = None

    @classmethod
    def from_raw(cls, raw: Any, *, where: str) -> LiveItem:
        data = _expect_mapping(raw, where)
        return cls(
            document=str(data.get("document", "")).strip().upper(),
            scope=str(data.get("scope", "")).strip(),
            kind=str(data.get("kind", "execution")).strip(),
            source=str(data.get("source", "")).strip(),
            added=_date_str(data.get("added", _today()), f"{where}.added"),
            since=_date_str(data.get("since"), f"{where}.since") if data.get("since") else None,
            reason=str(data.get("reason", "")).strip() or None,
            review_after=(
                _date_str(data.get("review_after"), f"{where}.review_after") if data.get("review_after") else None
            ),
            carryover_from=_optional_sprint_id(data.get("carryover_from")),
            outcome=_optional_mapping(data.get("outcome"), f"{where}.outcome"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "document": self.document,
            "scope": self.scope,
            "kind": self.kind,
            # Empty source (e.g. migrated v1 draft_pool items) is omitted, not written as ''.
            "source": self.source or None,
            "added": self.added,
            "since": self.since,
            "reason": self.reason,
            "review_after": self.review_after,
            "carryover_from": self.carryover_from,
            "outcome": self.outcome,
        }


@dataclass(frozen=True)
class SprintItem:
    """One item inside a closed sprint archive (v1-compatible shape)."""

    document: str
    kind: str = "execution"
    source: str = "manual"
    added: str = field(default_factory=lambda: _today())
    carryover_from: str | None = None
    outcome: dict[str, Any] | None = None

    @classmethod
    def from_raw(cls, raw: Any, *, where: str) -> SprintItem:
        data = _expect_mapping(raw, where)
        return cls(
            document=str(data.get("document", "")).strip().upper(),
            kind=str(data.get("kind", "execution")).strip(),
            source=str(data.get("source", "manual")).strip(),
            added=_date_str(data.get("added", _today()), f"{where}.added"),
            carryover_from=_optional_sprint_id(data.get("carryover_from")),
            outcome=_optional_mapping(data.get("outcome"), f"{where}.outcome"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "document": self.document,
            "kind": self.kind,
            "source": self.source,
            "added": self.added,
            "carryover_from": self.carryover_from,
            "outcome": self.outcome,
        }


@dataclass(frozen=True)
class SprintRecord:
    """One closed/<SPRINT-ID>.yaml archive (v1-compatible shape)."""

    id: str
    name: str
    status: str
    started: str
    closed: str | None = None
    items: tuple[SprintItem, ...] = ()

    @classmethod
    def from_raw(cls, raw: Any, *, where: str) -> SprintRecord:
        data = _expect_mapping(raw, where)
        return cls(
            id=str(data.get("id", "")).strip().upper(),
            name=str(data.get("name", "")).strip(),
            status=str(data.get("status", "")).strip(),
            started=_date_str(data.get("started", ""), f"{where}.started") if data.get("started") else "",
            closed=_date_str(data.get("closed"), f"{where}.closed") if data.get("closed") else None,
            items=tuple(
                SprintItem.from_raw(item, where=f"{where}.items[{idx}]")
                for idx, item in enumerate(data.get("items", []))
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "started": self.started,
            "closed": self.closed,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True)
class LedgerView:
    """Assembled view of the whole sprint directory store."""

    state: SprintState
    live: dict[str, LiveItem]
    closed: tuple[SprintRecord, ...]

    @property
    def active_items(self) -> tuple[LiveItem, ...]:
        return tuple(item for item in self.live.values() if item.scope == "active")

    @property
    def active_open_items(self) -> tuple[LiveItem, ...]:
        return tuple(item for item in self.active_items if item.outcome is None)

    @property
    def active_done_items(self) -> tuple[LiveItem, ...]:
        return tuple(item for item in self.active_items if item.outcome is not None)

    @property
    def backlog_items(self) -> tuple[LiveItem, ...]:
        return tuple(item for item in self.live.values() if item.scope == "backlog")

    @property
    def draft_pool_items(self) -> tuple[LiveItem, ...]:
        return tuple(item for item in self.live.values() if item.scope == "draft_pool")

    def live_membership(self) -> dict[str, str]:
        """Map document id -> scope, counting only outcome-less live files."""
        return {item.document: item.scope for item in self.live.values() if item.outcome is None}


@dataclass(frozen=True)
class SprintValidation:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SprintScope:
    label: str
    tasks: tuple[Any, ...] = ()
    planning: tuple[Any, ...] = ()
    context: tuple[Any, ...] = ()
    all_documents: tuple[Any, ...] = ()

    @property
    def selected_documents(self) -> tuple[Any, ...]:
        if self.all_documents:
            return self.all_documents
        return self.tasks + self.planning + self.context


# ─── paths and detection ────────────────────────────────────────────────────


def sprints_path(root: Path | None = None) -> Path:
    project_root = get_project_root() if root is None else root
    return project_root / SPRINTS_REL_PATH


def state_path(root: Path | None = None) -> Path:
    project_root = get_project_root() if root is None else root
    return project_root / STATE_REL_PATH


def live_path(root: Path | None = None) -> Path:
    project_root = get_project_root() if root is None else root
    return project_root / LIVE_REL_PATH


def closed_path(root: Path | None = None) -> Path:
    project_root = get_project_root() if root is None else root
    return project_root / CLOSED_REL_PATH


def ledger_path(root: Path | None = None) -> Path:
    """v1 ledger.yaml path — detection and migration only."""
    project_root = get_project_root() if root is None else root
    return project_root / LEDGER_REL_PATH


def sprint_mode_enabled(root: Path | None = None) -> bool:
    """True when a v2 state.yaml or a legacy v1 ledger.yaml exists.

    A v1 ledger counts as enabled so lint surfaces the migration error loudly
    instead of silently skipping sprint checks.
    """
    return state_path(root).exists() or ledger_path(root).exists()


def _require_no_v1_ledger(root: Path | None) -> None:
    if ledger_path(root).exists() and not state_path(root).exists():
        raise SprintLedgerError(V1_DETECTED_MESSAGE)


# ─── I/O (each write touches exactly one file) ──────────────────────────────


def load_state(root: Path | None = None) -> SprintState:
    """Cheap read of state.yaml only (used by new-document gating)."""
    _require_no_v1_ledger(root)
    path = state_path(root)
    if not path.exists():
        raise SprintLedgerError(NOT_ENABLED_MESSAGE)
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise SprintLedgerError(f"{STATE_REL_PATH}: invalid YAML: {e}") from e
    state = SprintState.from_raw(raw)
    if state.schema != SCHEMA:
        raise SprintLedgerError(f"{STATE_REL_PATH}: schema must be {SCHEMA!r}")
    if state.mode != MODE_ENABLED:
        raise SprintLedgerError(f"{STATE_REL_PATH}: mode must be {MODE_ENABLED!r}")
    return state


def load_view(root: Path | None = None) -> LedgerView:
    """Assemble the full directory store; raises on the first malformed file."""
    state = load_state(root)
    live_entries, live_errors = _read_live_files(root)
    closed_records, closed_errors = _read_closed_files(root)
    problems = live_errors + closed_errors
    if problems:
        raise SprintLedgerError(problems[0])
    return LedgerView(
        state=state,
        live={item.document: item for _, item in live_entries},
        closed=tuple(record for _, record in closed_records),
    )


def save_state(state: SprintState, root: Path | None = None) -> None:
    """Atomically rewrite state.yaml. Callers hold ``_ledger_lock`` for transitions."""
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_yaml(path, state.to_dict(), prefix=".state.")


def create_live_item(item: LiveItem, root: Path | None = None) -> None:
    """Create live/<DOC-ID>.yaml; O_EXCL makes the exists-check atomic."""
    directory = live_path(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{item.document}.yaml"
    rendered = yaml.safe_dump(_strip_none(item.to_dict()), sort_keys=False)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        raise SprintLedgerError(_duplicate_live_message(item.document, path)) from None
    with os.fdopen(fd, "w") as handle:
        handle.write(rendered)


def rewrite_live_item(item: LiveItem, root: Path | None = None) -> None:
    """Atomically rewrite one existing live file (used by complete/drop)."""
    path = live_path(root) / f"{item.document}.yaml"
    if not path.exists():
        raise SprintLedgerError(f"{item.document} is not an active sprint item")
    _atomic_write_yaml(path, item.to_dict(), prefix=f".{item.document}.")


def remove_live_item(doc_id: str, root: Path | None = None) -> None:
    """Remove one live file. Fold-time only (rollover/pause)."""
    (live_path(root) / f"{require_doc_id(doc_id)}.yaml").unlink(missing_ok=True)


def write_closed_sprint(record: SprintRecord, root: Path | None = None) -> None:
    """Create closed/<SPRINT-ID>.yaml; archives are append-only, never rewritten."""
    directory = closed_path(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{record.id}.yaml"
    rendered = yaml.safe_dump(_strip_none(record.to_dict()), sort_keys=False)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        raise SprintLedgerError(f"closed sprint archive already exists: {CLOSED_REL_PATH / path.name}") from None
    with os.fdopen(fd, "w") as handle:
        handle.write(rendered)


@contextmanager
def _ledger_lock(root: Path | None = None):
    """Advisory exclusive lock for composite state transitions.

    Without ``fcntl`` (non-POSIX platforms) this is a documented no-op:
    single-file writes stay atomic, only transition composites lose mutual
    exclusion.
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover - platform without fcntl
        yield
        return
    # The lock lives under .decree/ (derived state, gitignored) so it is never
    # committed alongside the sprint store it guards.
    project_root = get_project_root() if root is None else root
    lock_dir = project_root / ".decree"
    lock_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_dir / "sprints.lock", os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _read_live_files(root: Path | None) -> tuple[list[tuple[str, LiveItem]], list[str]]:
    entries: list[tuple[str, LiveItem]] = []
    errors: list[str] = []
    directory = live_path(root)
    if not directory.exists():
        return entries, errors
    for path in sorted(directory.glob("*.yaml")):
        where = (LIVE_REL_PATH / path.name).as_posix()
        try:
            raw = yaml.safe_load(path.read_text())
        except OSError as e:
            errors.append(f"{where}: unreadable: {e}")
            continue
        except yaml.YAMLError as e:
            errors.append(f"{where}: invalid YAML: {e}")
            continue
        try:
            entries.append((path.name, LiveItem.from_raw(raw, where=where)))
        except ValueError as e:
            # ValueError covers SprintLedgerError plus raw identity errors
            # (e.g. malformed carryover_from); both must stay per-file.
            message = str(e)
            errors.append(message if message.startswith(where) else f"{where}: {message}")
    return entries, errors


def _read_closed_files(root: Path | None) -> tuple[list[tuple[str, SprintRecord]], list[str]]:
    # Sorted filenames give chronological order: SPRINT-<ULID> is ULID-lexicographic.
    records: list[tuple[str, SprintRecord]] = []
    errors: list[str] = []
    directory = closed_path(root)
    if not directory.exists():
        return records, errors
    for path in sorted(directory.glob("*.yaml")):
        where = (CLOSED_REL_PATH / path.name).as_posix()
        try:
            raw = yaml.safe_load(path.read_text())
        except OSError as e:
            errors.append(f"{where}: unreadable: {e}")
            continue
        except yaml.YAMLError as e:
            errors.append(f"{where}: invalid YAML: {e}")
            continue
        try:
            records.append((path.name, SprintRecord.from_raw(raw, where=where)))
        except ValueError as e:
            message = str(e)
            errors.append(message if message.startswith(where) else f"{where}: {message}")
    return records, errors


def _duplicate_live_message(doc_id: str, path: Path) -> str:
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        raw = None
    scope = str(raw.get("scope", "")).strip() if isinstance(raw, dict) else ""
    outcome = raw.get("outcome") if isinstance(raw, dict) else None
    if outcome is not None:
        kind = str(outcome.get("kind", "")).strip() if isinstance(outcome, dict) else ""
        detail = f" ({kind})" if kind else ""
        return f"{doc_id} already has a resolved live record{detail}; resolved record folds at next rollover"
    labels = {"active": "active sprint", "backlog": "backlog", "draft_pool": "draft_pool"}
    return f"{doc_id} is already in {labels.get(scope, scope or 'a live sprint file')}"


def _atomic_write_yaml(path: Path, data: dict[str, Any], *, prefix: str) -> None:
    rendered = yaml.safe_dump(_strip_none(data), sort_keys=False)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=prefix, suffix=".tmp", delete=False) as tmp:
        tmp.write(rendered)
        tmp_path = Path(tmp.name)
    # NamedTemporaryFile creates 0600; match the 0644 used for O_EXCL creates.
    os.chmod(tmp_path, 0o644)
    tmp_path.replace(path)


# ─── operations ─────────────────────────────────────────────────────────────


def init_ledger(name: str, *, root: Path | None = None, today: str | None = None) -> SprintState:
    state = SprintState(
        schema=SCHEMA,
        mode=MODE_ENABLED,
        state="active",
        active={"id": generate_sprint_id(), "name": name, "started": today or _today()},
        paused=None,
    )
    with _ledger_lock(root):
        # Checked under the lock so two concurrent inits cannot both succeed.
        if state_path(root).exists():
            raise SprintLedgerError("sprint ledger already exists")
        _require_no_v1_ledger(root)
        live_path(root).mkdir(parents=True, exist_ok=True)
        closed_path(root).mkdir(parents=True, exist_ok=True)
        save_state(state, root=root)
    return state


def add_to_active_sprint(
    document: str,
    *,
    kind: str = "execution",
    source: str = "manual",
    root: Path | None = None,
    today: str | None = None,
) -> LiveItem:
    state = load_state(root)
    if state.state != "active" or not state.active:
        raise SprintLedgerError("sprint ledger is paused; use --backlog or --draft-pool")
    _validate_item_kind(kind)
    item = LiveItem(
        document=require_doc_id(document),
        scope="active",
        kind=kind,
        source=source,
        added=today or _today(),
    )
    create_live_item(item, root=root)
    return item


def add_to_backlog(
    document: str,
    *,
    reason: str,
    kind: str = "execution",
    source: str = "manual",
    root: Path | None = None,
    today: str | None = None,
    review_after: str | None = None,
) -> LiveItem:
    load_state(root)
    _validate_item_kind(kind)
    item = LiveItem(
        document=require_doc_id(document),
        scope="backlog",
        kind=kind,
        source=source,
        added=today or _today(),
        since=today or _today(),
        reason=_require_reason(reason),
        review_after=review_after,
    )
    create_live_item(item, root=root)
    return item


def add_to_draft_pool(
    document: str,
    *,
    reason: str,
    kind: str = "execution",
    root: Path | None = None,
    today: str | None = None,
) -> LiveItem:
    load_state(root)
    _validate_item_kind(kind)
    item = LiveItem(
        document=require_doc_id(document),
        scope="draft_pool",
        kind=kind,
        added=today or _today(),
        reason=_require_reason(reason),
    )
    create_live_item(item, root=root)
    return item


def complete_item(
    document: str,
    *,
    commits: tuple[str, ...] = (),
    root: Path | None = None,
    today: str | None = None,
) -> LiveItem:
    """Record a completed outcome on one live active item, touching only its file."""
    # Locked so a concurrent rollover/pause in the same checkout cannot fold
    # this item mid-rewrite (worktrees have their own store; this guards
    # same-checkout sessions).
    with _ledger_lock(root):
        item = _open_active_item(document, root)
        snapshot = _snapshot_for_doc(_find_doc(item.document))
        incomplete = snapshot["primary_total"] > 0 and snapshot["primary_done"] != snapshot["primary_total"]
        if incomplete:
            raise SprintLedgerError(f"{item.document} cannot be completed unless primary acceptance criteria are 100%")
        outcome = {
            "kind": "completed",
            "at": today or _today(),
            "reason": None,
            "to_sprint": None,
            "to_document": None,
            "evidence": {"commits": list(commits)},
            "snapshot": snapshot,
        }
        updated = replace(item, outcome=outcome)
        rewrite_live_item(updated, root=root)
    return updated


def drop_item(
    document: str,
    *,
    reason: str,
    root: Path | None = None,
    today: str | None = None,
) -> LiveItem:
    """Record a dropped outcome on one live active item, touching only its file."""
    clean_reason = _require_reason(reason)
    with _ledger_lock(root):
        item = _open_active_item(document, root)
        outcome = {
            "kind": "dropped",
            "at": today or _today(),
            "reason": clean_reason,
            "to_sprint": None,
            "to_document": None,
            "evidence": {"commits": []},
            "snapshot": _snapshot_for_doc(_find_doc(item.document)),
        }
        updated = replace(item, outcome=outcome)
        rewrite_live_item(updated, root=root)
    return updated


def pause_ledger(reason: str, *, root: Path | None = None, today: str | None = None) -> SprintState:
    clean_reason = _require_reason(reason)
    with _ledger_lock(root):
        view = load_view(root)
        if view.state.state != "active" or not view.state.active:
            raise SprintLedgerError("sprint ledger is not active")
        if view.active_open_items:
            raise SprintLedgerError(
                "cannot pause with open active-sprint items; complete, drop, or rollover them first"
            )
        today_str = today or _today()
        active = view.state.active
        record = SprintRecord(
            id=active["id"],
            name=active["name"],
            status="closed",
            started=active["started"],
            closed=today_str,
            items=tuple(_fold_item(item) for item in view.active_items),
        )
        write_closed_sprint(record, root=root)
        for item in view.active_items:
            remove_live_item(item.document, root=root)
        updated = replace(view.state, state="paused", active=None, paused={"since": today_str, "reason": clean_reason})
        save_state(updated, root=root)
    return updated


def resume_ledger(name: str, *, root: Path | None = None, today: str | None = None) -> SprintState:
    with _ledger_lock(root):
        state = load_state(root)
        if state.state != "paused":
            raise SprintLedgerError("sprint ledger is not paused")
        updated = replace(
            state,
            state="active",
            active={"id": generate_sprint_id(), "name": name, "started": today or _today()},
            paused=None,
        )
        save_state(updated, root=root)
    return updated


def rollover_ledger(
    name: str,
    outcomes: dict[str, dict[str, Any]],
    docs: list[Any],
    *,
    root: Path | None = None,
    today: str | None = None,
) -> SprintState:
    with _ledger_lock(root):
        view = load_view(root)
        if view.state.state != "active" or not view.state.active:
            raise SprintLedgerError("sprint ledger is not active")
        open_docs = {item.document for item in view.active_open_items}
        outcome_docs = {require_doc_id(doc_id) for doc_id in outcomes}
        missing = sorted(open_docs - outcome_docs)
        extra = sorted(outcome_docs - open_docs)
        if missing:
            raise SprintLedgerError(f"outcomes missing active sprint item(s): {', '.join(missing)}")
        if extra:
            raise SprintLedgerError(f"outcomes include document(s) not open in active sprint: {', '.join(extra)}")

        by_id = {doc.doc_id: doc for doc in docs}
        today_str = today or _today()
        next_id = generate_sprint_id()
        closed_items: list[SprintItem] = []
        carryovers: list[LiveItem] = []
        for item in view.active_items:
            if item.outcome is not None:
                closed_items.append(_fold_item(item))
                continue
            outcome = _build_rollover_outcome(item, outcomes[item.document], by_id, next_id, today_str)
            closed_items.append(replace(_fold_item(item), outcome=outcome))
            if outcome["kind"] == "carried_over":
                carryovers.append(
                    LiveItem(
                        document=item.document,
                        scope="active",
                        kind=item.kind,
                        source="carryover",
                        added=today_str,
                        carryover_from=view.state.active["id"],
                    )
                )
        active = view.state.active
        record = SprintRecord(
            id=active["id"],
            name=active["name"],
            status="closed",
            started=active["started"],
            closed=today_str,
            items=tuple(closed_items),
        )
        write_closed_sprint(record, root=root)
        for item in view.active_items:
            remove_live_item(item.document, root=root)
        for carryover in carryovers:
            create_live_item(carryover, root=root)
        updated = replace(
            view.state,
            state="active",
            active={"id": next_id, "name": name, "started": today_str},
            paused=None,
        )
        save_state(updated, root=root)
    return updated


def load_outcomes_file(path: Path) -> dict[str, dict[str, Any]]:
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise SprintLedgerError(f"{path}: invalid YAML: {e}") from e
    if isinstance(raw, dict) and "outcomes" in raw:
        raw = raw["outcomes"]
    if not isinstance(raw, dict):
        raise SprintLedgerError("outcomes file must be a mapping or contain an `outcomes` mapping")
    return {require_doc_id(str(doc_id)): value for doc_id, value in raw.items()}


def _build_rollover_outcome(
    item: LiveItem,
    raw: Any,
    by_id: dict[str, Any],
    next_sprint_id: str,
    today_str: str,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SprintLedgerError(f"outcome for {item.document} must be a mapping")
    kind = str(raw.get("kind", "")).strip()
    if kind == "carryover":
        kind = "carried_over"
    if kind not in OUTCOME_KINDS:
        raise SprintLedgerError(f"outcome for {item.document} has invalid kind: {kind!r}")
    reason = str(raw.get("reason", "")).strip()
    if kind in OUTCOMES_REQUIRING_REASON and not reason:
        raise SprintLedgerError(f"outcome for {item.document} requires reason")
    snapshot = _snapshot_for_doc(by_id.get(item.document))
    completed_incomplete = (
        kind == "completed" and snapshot["primary_total"] > 0 and snapshot["primary_done"] != snapshot["primary_total"]
    )
    if completed_incomplete:
        raise SprintLedgerError(f"{item.document} cannot be completed unless primary acceptance criteria are 100%")
    return {
        "kind": kind,
        "at": today_str,
        "reason": reason or None,
        "to_sprint": next_sprint_id if kind == "carried_over" else raw.get("to_sprint"),
        "to_document": str(raw.get("to_document", "")).strip().upper() if raw.get("to_document") else None,
        "evidence": raw.get("evidence") or {"commits": []},
        "snapshot": snapshot,
    }


def _fold_item(item: LiveItem) -> SprintItem:
    return SprintItem(
        document=item.document,
        kind=item.kind,
        source=item.source or "manual",
        added=item.added,
        carryover_from=item.carryover_from,
        outcome=item.outcome,
    )


def _open_active_item(document: str, root: Path | None) -> LiveItem:
    view = load_view(root)
    doc_id = require_doc_id(document)
    item = view.live.get(doc_id)
    if item is None:
        raise SprintLedgerError(f"{doc_id} is not an active sprint item")
    if item.scope != "active":
        raise SprintLedgerError(f"{doc_id} is in {item.scope}, not the active sprint")
    if item.outcome is not None:
        kind = str(item.outcome.get("kind", "")).strip() or "resolved"
        raise SprintLedgerError(f"{doc_id} already has a recorded outcome ({kind})")
    return item


def _find_doc(doc_id: str) -> Any:
    from decree.parser import find_by_id

    try:
        return find_by_id(doc_id)
    except (FileNotFoundError, ValueError) as e:
        raise SprintLedgerError(str(e)) from e


# ─── validation ─────────────────────────────────────────────────────────────


def validate_ledger(root: Path, docs: list[Any]) -> SprintValidation:
    if not sprint_mode_enabled(root):
        return SprintValidation()
    try:
        state = load_state(root)
    except Exception as e:
        return SprintValidation(errors=(str(e),))

    errors: list[str] = []
    warnings: list[str] = []
    if ledger_path(root).exists():
        errors.append(
            "legacy decree/sprints/ledger.yaml present alongside the v2 store; "
            "merge its entries into the directory store manually and delete it"
        )
    live_entries, live_errors = _read_live_files(root)
    closed_records, closed_errors = _read_closed_files(root)
    errors.extend(live_errors)
    errors.extend(closed_errors)

    by_id = {doc.doc_id: doc for doc in docs}
    _validate_state_block(errors, state, live_entries)
    for filename, item in live_entries:
        _validate_live_entry(errors, warnings, filename, item, by_id)
    _validate_live_duplicates(errors, live_entries)
    _validate_closed_records(errors, closed_records, by_id, state)
    _validate_carryover_linearity(errors, closed_records, state, live_entries)
    _validate_live_reference_health(errors, live_entries, by_id)

    live_docs = {item.document for _, item in live_entries}
    closed = [record for _, record in closed_records]
    for doc in _missing_post_init_specs(state, closed, live_docs, docs):
        errors.append(
            f"{doc.doc_id}: non-terminal SPEC created after sprint mode was initialized must be in active sprint, "
            "backlog, or draft_pool"
        )
    return SprintValidation(errors=tuple(errors), warnings=tuple(warnings))


def _validate_state_block(errors: list[str], state: SprintState, live_entries: list[tuple[str, LiveItem]]) -> None:
    if state.state == "active":
        if not state.active or not state.active.get("id"):
            errors.append("active state requires active sprint id")
        else:
            try:
                require_sprint_id(state.active["id"])
            except ValueError as e:
                errors.append(f"state.active.id: {e}")
            if not state.active.get("name"):
                errors.append("active sprint requires name")
            if not state.active.get("started"):
                errors.append("active sprint requires started date")
        if state.paused is not None:
            errors.append("active state must not include paused metadata")
    elif state.state == "paused":
        if state.active is not None:
            errors.append("paused state must not have active sprint id")
        if not state.paused or not state.paused.get("since") or not state.paused.get("reason"):
            errors.append("paused state requires paused.since and paused.reason")
        for filename, item in live_entries:
            if item.scope == "active":
                where = (LIVE_REL_PATH / filename).as_posix()
                errors.append(f"{where}: scope=active live item is not allowed while sprint mode is paused")
    else:
        errors.append("state must be active or paused")


def _validate_live_entry(
    errors: list[str],
    warnings: list[str],
    filename: str,
    item: LiveItem,
    by_id: dict[str, Any],
) -> None:
    where = (LIVE_REL_PATH / filename).as_posix()
    if Path(filename).stem != item.document:
        errors.append(f"{where}: filename stem must equal document field {item.document or '<missing>'}")
    _validate_common_item(errors, item.document, item.kind, where, by_id)
    if item.scope not in LIVE_SCOPES:
        errors.append(f"{where}: scope must be one of {sorted(LIVE_SCOPES)}")
    if item.scope == "backlog":
        if not item.source:
            errors.append(f"{where}: source is required")
        if not item.since:
            errors.append(f"{where}: since is required")
        if not item.reason:
            errors.append(f"{where}: reason is required")
        if item.since:
            age = (_date_obj(_today()) - _date_obj(item.since)).days
            review_due = item.review_after is None or _date_obj(item.review_after) <= _date_obj(_today())
            if age > BACKLOG_WARN_AFTER_DAYS and review_due:
                warnings.append(f"{where}: backlog item is {age} days old; review or update review_after")
    if item.scope == "draft_pool" and not item.reason:
        errors.append(f"{where}: reason is required")
    if item.outcome is not None:
        if item.scope != "active":
            errors.append(f"{where}: outcome is only allowed on scope=active items")
        kind = str(item.outcome.get("kind", "")).strip() if isinstance(item.outcome, dict) else ""
        if kind not in LIVE_OUTCOME_KINDS:
            errors.append(f"{where}: live outcome kind must be one of {sorted(LIVE_OUTCOME_KINDS)}")
        else:
            _validate_outcome(errors, item.outcome, where)
    terminal_live = (
        item.kind == "execution"
        and item.document in by_id
        and item.outcome is None
        and _is_terminal(by_id[item.document])
    )
    if terminal_live:
        errors.append(f"{where}: terminal SPEC requires explicit reopen semantics before sprint membership")


def _validate_live_duplicates(errors: list[str], live_entries: list[tuple[str, LiveItem]]) -> None:
    # Structurally one file per document; two files can still declare the same
    # document field when a filename does not match. Keep the defensive error.
    labels = {"active": "active sprint", "backlog": "backlog", "draft_pool": "draft_pool"}
    seen: dict[str, str] = {}
    for _, item in live_entries:
        scope = labels.get(item.scope, item.scope)
        previous = seen.get(item.document)
        if previous:
            errors.append(f"{item.document}: live document appears in both {previous} and {scope}")
            continue
        seen[item.document] = scope


def _validate_closed_records(
    errors: list[str],
    closed_records: list[tuple[str, SprintRecord]],
    by_id: dict[str, Any],
    state: SprintState,
) -> None:
    active_id = state.active.get("id") if state.active else None
    seen_ids: set[str] = set()
    for filename, record in closed_records:
        where = (CLOSED_REL_PATH / filename).as_posix()
        if Path(filename).stem != record.id:
            errors.append(f"{where}: filename stem must equal sprint id {record.id or '<missing>'}")
        try:
            sid = require_sprint_id(record.id)
        except ValueError as e:
            errors.append(f"{where}: {e}")
            sid = record.id
        if sid in seen_ids:
            errors.append(f"{where}: duplicate sprint id {sid}")
        seen_ids.add(sid)
        if not record.name:
            errors.append(f"{where}: name is required")
        if not record.started:
            errors.append(f"{where}: started is required")
        if record.status != "closed":
            errors.append(f"{where}: closed archive must have status closed")
        if not record.closed:
            errors.append(f"{where}: closed sprint requires closed date")
        if active_id and record.id == active_id:
            errors.append(f"{where}: archive id matches the active sprint id {active_id}")
        _validate_closed_items(errors, record, by_id)


def _validate_closed_items(errors: list[str], record: SprintRecord, by_id: dict[str, Any]) -> None:
    seen_docs: set[str] = set()
    for idx, item in enumerate(record.items):
        where = f"{record.id}.items[{idx}] {item.document or '<missing>'}"
        _validate_common_item(errors, item.document, item.kind, where, by_id)
        if item.document in seen_docs:
            errors.append(f"{where}: duplicate document in sprint")
        seen_docs.add(item.document)
        if item.outcome is None:
            errors.append(f"{where}: closed sprint item requires outcome")
        else:
            _validate_outcome(errors, item.outcome, where)


def _validate_common_item(errors: list[str], document: str, kind: str, where: str, by_id: dict[str, Any]) -> None:
    try:
        require_doc_id(document)
    except ValueError as e:
        errors.append(f"{where}: {e}")
    if document not in by_id:
        errors.append(f"{where}: document not found")
    if kind not in ITEM_KINDS:
        errors.append(f"{where}: kind must be one of {sorted(ITEM_KINDS)}")
    if kind == "execution" and document in by_id and not _is_execution_doc(by_id[document]):
        errors.append(f"{where}: execution items must reference configured SPEC documents")


def _validate_outcome(errors: list[str], outcome: dict[str, Any], where: str) -> None:
    if not isinstance(outcome, dict):
        errors.append(f"{where}: outcome must be a mapping")
        return
    kind = str(outcome.get("kind", "")).strip()
    if kind not in OUTCOME_KINDS:
        errors.append(f"{where}: outcome.kind must be one of {sorted(OUTCOME_KINDS)}")
    if not outcome.get("at"):
        errors.append(f"{where}: outcome.at is required")
    if kind in OUTCOMES_REQUIRING_REASON and not str(outcome.get("reason", "") or "").strip():
        errors.append(f"{where}: outcome.reason is required for {kind}")
    snapshot = outcome.get("snapshot")
    if not isinstance(snapshot, dict):
        errors.append(f"{where}: outcome.snapshot is required")
        return
    if kind == "completed":
        done = _snapshot_count(snapshot.get("primary_done", -1))
        total = _snapshot_count(snapshot.get("primary_total", -1))
        if total < 0 or done < 0 or (total > 0 and done != total):
            errors.append(f"{where}: completed outcome requires snapshot primary progress at 100%")
    if kind == "carried_over" and not str(outcome.get("to_sprint", "") or "").strip():
        errors.append(f"{where}: carried_over outcome requires to_sprint")
    if kind == "superseded" and not outcome.get("to_document"):
        errors.append(f"{where}: superseded outcome requires to_document")


def _validate_carryover_linearity(
    errors: list[str],
    closed_records: list[tuple[str, SprintRecord]],
    state: SprintState,
    live_entries: list[tuple[str, LiveItem]],
) -> None:
    closed = [record for _, record in closed_records]
    known_ids = {record.id for record in closed}
    active_id = state.active.get("id") if state.active else None
    live_by_doc = {item.document: item for _, item in live_entries}
    for idx, record in enumerate(closed):
        successor = closed[idx + 1] if idx + 1 < len(closed) else None
        for item in record.items:
            if not item.outcome or item.outcome.get("kind") != "carried_over":
                continue
            to_sprint = str(item.outcome.get("to_sprint", "")).strip().upper()
            if not to_sprint:
                continue  # missing to_sprint already reported by _validate_outcome
            if successor is not None:
                if to_sprint != successor.id:
                    if to_sprint in known_ids or to_sprint == active_id:
                        errors.append(
                            f"{record.id} {item.document}: carryover must target the immediate successor sprint"
                        )
                    else:
                        errors.append(f"{record.id} {item.document}: carryover target sprint not found: {to_sprint}")
                    continue
                found = any(x.document == item.document and x.carryover_from == record.id for x in successor.items)
                if not found:
                    errors.append(f"{record.id} {item.document}: successor sprint missing matching carryover item")
                continue
            # Last archive: the carryover may target the current active sprint,
            # in which case a matching live file must exist.
            if to_sprint != active_id:
                if to_sprint in known_ids:
                    errors.append(f"{record.id} {item.document}: carryover must target the immediate successor sprint")
                else:
                    errors.append(f"{record.id} {item.document}: carryover target sprint not found: {to_sprint}")
                continue
            live_item = live_by_doc.get(item.document)
            found = live_item is not None and live_item.scope == "active" and live_item.carryover_from == record.id
            if not found:
                errors.append(f"{record.id} {item.document}: successor sprint missing matching carryover item")

    # Reverse direction: every live carryover_from must be provenance the last
    # closed sprint actually recorded (guards stale/fabricated files surviving a merge).
    last_id = closed[-1].id if closed else None
    for name, item in live_entries:
        if item.carryover_from is None:
            continue
        where = (LIVE_REL_PATH / name).as_posix()
        if item.scope != "active":
            errors.append(f"{where}: carryover_from is only valid on scope=active items")
            continue
        if item.carryover_from not in known_ids:
            errors.append(f"{where}: carryover_from target sprint not found: {item.carryover_from}")
            continue
        if item.carryover_from != last_id:
            errors.append(f"{where}: carryover_from must reference the most recent closed sprint {last_id}")
            continue
        recorded = any(
            x.document == item.document and x.outcome and x.outcome.get("kind") == "carried_over"
            for x in closed[-1].items
        )
        if not recorded:
            errors.append(f"{where}: {item.carryover_from} does not record {item.document} as carried over")


def _validate_live_reference_health(
    errors: list[str],
    live_entries: list[tuple[str, LiveItem]],
    by_id: dict[str, Any],
) -> None:
    for _, item in live_entries:
        if item.scope != "active" or item.outcome is not None:
            continue
        doc = by_id.get(item.document)
        if doc is None:
            continue
        for ref in doc.meta.references or []:
            target = by_id.get(ref)
            if target is None or target.doc_type is None:
                continue
            if target.meta.status in target.doc_type.warn_on_reference:
                errors.append(
                    f"{item.document}: active sprint item references stale/dead document {ref} ({target.meta.status})"
                )


def _missing_post_init_specs(
    state: SprintState,
    closed: list[SprintRecord],
    live_docs: set[str],
    docs: list[Any],
) -> list[Any]:
    started_dates = [record.started for record in closed if record.started]
    if state.active and state.active.get("started"):
        started_dates.append(state.active["started"])
    if not started_dates:
        return []
    first_started = min(_date_obj(value) for value in started_dates)
    closed_members = {item.document for record in closed for item in record.items}
    missing: list[Any] = []
    for doc in docs:
        if not _is_execution_doc(doc):
            continue
        if _is_terminal(doc):
            continue
        if doc.doc_id in live_docs or doc.doc_id in closed_members:
            continue
        if doc.meta.date >= first_started:
            missing.append(doc)
    return missing


# ─── scoping ────────────────────────────────────────────────────────────────


def select_sprint_scope(docs: list[Any], args: Any | None, *, root: Path | None = None) -> SprintScope | None:
    project_root = get_project_root() if root is None else root
    if getattr(args, "corpus", False):
        return SprintScope(label="all documents", all_documents=tuple(docs))
    has_sprint_scope = any(
        (
            getattr(args, "sprint", None),
            getattr(args, "all_sprints", False),
            getattr(args, "backlog", False),
            getattr(args, "draft_pool", False),
        )
    )
    if not sprint_mode_enabled(project_root):
        if has_sprint_scope:
            raise SprintLedgerError(NOT_ENABLED_MESSAGE)
        return None
    view = load_view(project_root)
    include_context = bool(getattr(args, "include_context", False))
    by_id = {doc.doc_id: doc for doc in docs}

    if getattr(args, "backlog", False):
        items = view.backlog_items
        return _scope_from_items(f"backlog ({len(items)} items)", items, by_id, include_context=include_context)
    if getattr(args, "draft_pool", False):
        items = view.draft_pool_items
        return _scope_from_items(f"draft pool ({len(items)} items)", items, by_id, include_context=include_context)
    if getattr(args, "all_sprints", False):
        items = [item for record in view.closed for item in record.items]
        items.extend(view.active_items)
        return _scope_from_items("all sprints", items, by_id, include_context=include_context)
    sprint_id = getattr(args, "sprint", None)
    if sprint_id:
        sprint_id = require_sprint_id(sprint_id)
        if view.state.active and view.state.active.get("id") == sprint_id:
            # The active sprint by explicit id includes resolved items too.
            return _scope_from_items(
                f"sprint {sprint_id} ({view.state.active.get('name', '')})",
                view.active_items,
                by_id,
                include_context=include_context,
            )
        for record in view.closed:
            if record.id == sprint_id:
                return _scope_from_items(
                    f"sprint {record.id} ({record.name})",
                    record.items,
                    by_id,
                    include_context=include_context,
                )
        raise SprintLedgerError(f"sprint not found: {sprint_id}")
    if view.state.state == "paused":
        reason = view.state.paused.get("reason") if view.state.paused else "no reason recorded"
        raise SprintLedgerError(f"sprint mode is paused ({reason}); pass --backlog, --draft-pool, or --corpus")
    active = view.state.active
    if not active:
        raise SprintLedgerError("active sprint not found")
    return _scope_from_items(
        f"active sprint {active.get('id')} ({active.get('name')})",
        view.active_items,
        by_id,
        include_context=include_context,
        active_only=True,
    )


def document_context_for(items: list[Any], by_id: dict[str, Any]) -> tuple[Any, ...]:
    selected = {doc.doc_id for doc in items}
    refs: list[Any] = []
    seen: set[str] = set()
    for doc in items:
        for ref in doc.meta.references or []:
            if ref in selected or ref in seen:
                continue
            target = by_id.get(ref)
            if target is not None:
                refs.append(target)
                seen.add(ref)
    return tuple(refs)


def _scope_from_items(
    label: str,
    items: Any,
    by_id: dict[str, Any],
    *,
    include_context: bool,
    active_only: bool = False,
) -> SprintScope:
    tasks: list[Any] = []
    planning: list[Any] = []
    for item in items:
        if active_only and getattr(item, "outcome", None) is not None:
            continue
        doc = by_id.get(item.document)
        if doc is None:
            continue
        if item.kind == "planning":
            planning.append(doc)
        else:
            tasks.append(doc)
    context = document_context_for(tasks + planning, by_id) if include_context else ()
    return SprintScope(label=label, tasks=tuple(tasks), planning=tuple(planning), context=context)


# ─── shared helpers ─────────────────────────────────────────────────────────


def _is_execution_doc(doc: Any) -> bool:
    return doc.doc_type is not None and doc.doc_type.name == "spec"


def _is_terminal(doc: Any) -> bool:
    if doc.doc_type is None:
        return False
    return not doc.doc_type.transitions.get(doc.meta.status, ())


def _snapshot_for_doc(doc: Any | None) -> dict[str, Any]:
    if doc is None:
        raise SprintLedgerError("cannot snapshot missing document")
    root = get_project_root()
    type_name = doc.doc_type.name if doc.doc_type else "adr"
    cfg = load_report_config(root, type_name)
    parsed = parse_checkboxes_by_section(doc.body, cfg.deferred_section_patterns)
    return {
        "status": doc.meta.status,
        "primary_done": parsed.primary_done,
        "primary_total": parsed.primary_total,
        "deferred_done": parsed.deferred_done,
        "deferred_total": parsed.deferred_total,
    }


def _validate_item_kind(kind: str) -> None:
    if kind not in ITEM_KINDS:
        raise SprintLedgerError(f"kind must be one of {sorted(ITEM_KINDS)}")


def _require_reason(reason: str) -> str:
    clean = reason.strip()
    if not clean:
        raise SprintLedgerError("reason is required")
    return clean


def _optional_sprint_id(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return require_sprint_id(str(value))


def _expect_mapping(raw: Any, where: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SprintLedgerError(f"{where}: expected mapping, got {type(raw).__name__}")
    return raw


def _optional_mapping(value: Any, where: str) -> dict[str, Any] | None:
    if value is None:
        return None
    return _stringify_dates(_expect_mapping(value, where))


def _snapshot_count(value: Any) -> int:
    """Coerce a snapshot counter defensively; garbage becomes -1 (a validation error)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _strip_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_none(v) for v in value]
    return value


def _stringify_dates(value: Any) -> Any:
    """Normalize YAML-parsed date objects to ISO strings (outcome dicts stay JSON-safe)."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _stringify_dates(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_stringify_dates(v) for v in value]
    return value


def _date_str(value: Any, where: str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        raise SprintLedgerError(f"{where}: date is required")
    try:
        date.fromisoformat(text)
    except ValueError as e:
        raise SprintLedgerError(f"{where}: date must be YYYY-MM-DD") from e
    return text


def _date_obj(value: str) -> date:
    return date.fromisoformat(str(value))


def _today() -> str:
    return date.today().isoformat()
