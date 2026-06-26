"""Sprint ledger model, validation, and document scoping."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from decree.checklists import parse_checkboxes_by_section
from decree.commands.report import load_report_config
from decree.config import get_project_root
from decree.identity import generate_sprint_id, require_doc_id, require_sprint_id

LEDGER_REL_PATH = Path("decree/sprints/ledger.yaml")
SCHEMA = "decree.sprints.v1"
MODE_ENABLED = "enabled"
BACKLOG_WARN_AFTER_DAYS = 30

ITEM_KINDS = {"execution", "planning"}
OUTCOME_KINDS = {"completed", "carried_over", "deferred", "dropped", "superseded"}
OUTCOMES_REQUIRING_REASON = {"carried_over", "deferred", "dropped", "superseded"}


class SprintLedgerError(ValueError):
    """Raised when the sprint ledger cannot be parsed or a transition is invalid."""


@dataclass(frozen=True)
class SprintItem:
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
            outcome=data.get("outcome"),
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "document": self.document,
            "kind": self.kind,
            "source": self.source,
            "added": self.added,
            "carryover_from": self.carryover_from,
            "outcome": self.outcome,
        }
        return data


@dataclass(frozen=True)
class BacklogItem:
    document: str
    kind: str = "execution"
    source: str = "manual"
    since: str = field(default_factory=lambda: _today())
    added: str = field(default_factory=lambda: _today())
    review_after: str | None = None
    reason: str = ""

    @classmethod
    def from_raw(cls, raw: Any, *, where: str) -> BacklogItem:
        data = _expect_mapping(raw, where)
        return cls(
            document=str(data.get("document", "")).strip().upper(),
            kind=str(data.get("kind", "execution")).strip(),
            source=str(data.get("source", "")).strip(),
            since=_date_str(data.get("since", ""), f"{where}.since") if data.get("since") else "",
            added=_date_str(data.get("added", data.get("since", _today())), f"{where}.added"),
            review_after=(
                _date_str(data.get("review_after"), f"{where}.review_after") if data.get("review_after") else None
            ),
            reason=str(data.get("reason", "")).strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "document": self.document,
            "kind": self.kind,
            "source": self.source,
            "since": self.since,
            "added": self.added,
            "review_after": self.review_after,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DraftPoolItem:
    document: str
    kind: str = "execution"
    added: str = field(default_factory=lambda: _today())
    reason: str = ""

    @classmethod
    def from_raw(cls, raw: Any, *, where: str) -> DraftPoolItem:
        data = _expect_mapping(raw, where)
        return cls(
            document=str(data.get("document", "")).strip().upper(),
            kind=str(data.get("kind", "execution")).strip(),
            added=_date_str(data.get("added", _today()), f"{where}.added"),
            reason=str(data.get("reason", "")).strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "document": self.document,
            "kind": self.kind,
            "added": self.added,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SprintRecord:
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
class SprintLedger:
    schema: str
    mode: str
    state: str
    active: str | None
    paused: dict[str, Any] | None
    sprints: tuple[SprintRecord, ...]
    backlog: tuple[BacklogItem, ...] = ()
    draft_pool: tuple[DraftPoolItem, ...] = ()

    @classmethod
    def from_raw(cls, raw: Any) -> SprintLedger:
        data = _expect_mapping(raw, "ledger")
        schema = str(data.get("schema", "")).strip()
        mode = str(data.get("mode", "")).strip()
        state = str(data.get("state", "")).strip()
        active = data.get("active")
        if active is not None:
            active = str(active).strip().upper()
        paused = data.get("paused")
        if paused is not None:
            paused_data = _expect_mapping(paused, "ledger.paused")
            paused = {
                "since": _date_str(paused_data.get("since", ""), "ledger.paused.since")
                if paused_data.get("since")
                else "",
                "reason": str(paused_data.get("reason", "")).strip(),
            }
        return cls(
            schema=schema,
            mode=mode,
            state=state,
            active=active,
            paused=paused,
            sprints=tuple(
                SprintRecord.from_raw(sprint, where=f"ledger.sprints[{idx}]")
                for idx, sprint in enumerate(data.get("sprints", []))
            ),
            backlog=tuple(
                BacklogItem.from_raw(item, where=f"ledger.backlog[{idx}]")
                for idx, item in enumerate(data.get("backlog", []))
            ),
            draft_pool=tuple(
                DraftPoolItem.from_raw(item, where=f"ledger.draft_pool[{idx}]")
                for idx, item in enumerate(data.get("draft_pool", []))
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "mode": self.mode,
            "state": self.state,
            "active": self.active,
            "paused": self.paused,
            "sprints": [sprint.to_dict() for sprint in self.sprints],
            "backlog": [item.to_dict() for item in self.backlog],
            "draft_pool": [item.to_dict() for item in self.draft_pool],
        }

    @property
    def active_sprint(self) -> SprintRecord | None:
        if not self.active:
            return None
        for sprint in self.sprints:
            if sprint.id == self.active:
                return sprint
        return None

    def with_state(self, *, state: str, active: str | None, paused: dict[str, Any] | None) -> SprintLedger:
        return SprintLedger(
            schema=self.schema,
            mode=self.mode,
            state=state,
            active=active,
            paused=paused,
            sprints=self.sprints,
            backlog=self.backlog,
            draft_pool=self.draft_pool,
        )


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


def ledger_path(root: Path | None = None) -> Path:
    project_root = get_project_root() if root is None else root
    return project_root / LEDGER_REL_PATH


def sprint_mode_enabled(root: Path | None = None) -> bool:
    return ledger_path(root).exists()


def load_ledger(root: Path | None = None) -> SprintLedger:
    path = ledger_path(root)
    if not path.exists():
        raise SprintLedgerError('sprint mode is not enabled; run `decree sprint init "Sprint 1"`')
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise SprintLedgerError(f"{LEDGER_REL_PATH}: invalid YAML: {e}") from e
    ledger = SprintLedger.from_raw(raw)
    if ledger.schema != SCHEMA:
        raise SprintLedgerError(f"{LEDGER_REL_PATH}: schema must be {SCHEMA!r}")
    if ledger.mode != MODE_ENABLED:
        raise SprintLedgerError(f"{LEDGER_REL_PATH}: mode must be {MODE_ENABLED!r}")
    return ledger


def save_ledger(ledger: SprintLedger, root: Path | None = None) -> None:
    path = ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = yaml.safe_dump(_strip_none(ledger.to_dict()), sort_keys=False)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=".ledger.", suffix=".tmp", delete=False) as tmp:
        tmp.write(rendered)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def init_ledger(name: str, *, root: Path | None = None, today: str | None = None) -> SprintLedger:
    path = ledger_path(root)
    if path.exists():
        raise SprintLedgerError("sprint ledger already exists")
    started = today or _today()
    sprint = SprintRecord(
        id=generate_sprint_id(),
        name=name,
        status="active",
        started=started,
        closed=None,
        items=(),
    )
    ledger = SprintLedger(
        schema=SCHEMA,
        mode=MODE_ENABLED,
        state="active",
        active=sprint.id,
        paused=None,
        sprints=(sprint,),
        backlog=(),
        draft_pool=(),
    )
    save_ledger(ledger, root=root)
    return ledger


def pause_ledger(reason: str, *, root: Path | None = None, today: str | None = None) -> SprintLedger:
    ledger = load_ledger(root)
    if ledger.state != "active" or not ledger.active_sprint:
        raise SprintLedgerError("sprint ledger is not active")
    active = ledger.active_sprint
    open_items = [item.document for item in active.items if item.outcome is None]
    if open_items:
        raise SprintLedgerError("cannot pause with open active-sprint items; rollover, defer, or drop them first")
    closed = _replace_sprint(active, status="closed", closed=today or _today())
    updated = _replace_sprints(ledger, closed).with_state(
        state="paused",
        active=None,
        paused={"since": today or _today(), "reason": _require_reason(reason)},
    )
    save_ledger(updated, root=root)
    return updated


def resume_ledger(name: str, *, root: Path | None = None, today: str | None = None) -> SprintLedger:
    ledger = load_ledger(root)
    if ledger.state != "paused":
        raise SprintLedgerError("sprint ledger is not paused")
    sprint = SprintRecord(
        id=generate_sprint_id(),
        name=name,
        status="active",
        started=today or _today(),
        closed=None,
        items=(),
    )
    updated = SprintLedger(
        schema=ledger.schema,
        mode=ledger.mode,
        state="active",
        active=sprint.id,
        paused=None,
        sprints=(*ledger.sprints, sprint),
        backlog=ledger.backlog,
        draft_pool=ledger.draft_pool,
    )
    save_ledger(updated, root=root)
    return updated


def add_to_active_sprint(
    document: str,
    *,
    kind: str = "execution",
    source: str = "manual",
    root: Path | None = None,
    today: str | None = None,
) -> SprintLedger:
    ledger = load_ledger(root)
    if ledger.state != "active" or not ledger.active_sprint:
        raise SprintLedgerError("sprint ledger is paused; use --backlog or --draft-pool")
    _validate_item_kind(kind)
    doc_id = require_doc_id(document)
    if _live_membership(ledger).get(doc_id):
        raise SprintLedgerError(f"{doc_id} is already in {_live_membership(ledger)[doc_id]}")
    item = SprintItem(document=doc_id, kind=kind, source=source, added=today or _today())
    active = ledger.active_sprint
    updated_active = _replace_sprint(active, items=(*active.items, item))
    updated = _replace_sprints(ledger, updated_active)
    save_ledger(updated, root=root)
    return updated


def add_to_backlog(
    document: str,
    *,
    reason: str,
    kind: str = "execution",
    source: str = "manual",
    root: Path | None = None,
    today: str | None = None,
    review_after: str | None = None,
) -> SprintLedger:
    ledger = load_ledger(root)
    _validate_item_kind(kind)
    doc_id = require_doc_id(document)
    if _live_membership(ledger).get(doc_id):
        raise SprintLedgerError(f"{doc_id} is already in {_live_membership(ledger)[doc_id]}")
    item = BacklogItem(
        document=doc_id,
        kind=kind,
        source=source,
        since=today or _today(),
        added=today or _today(),
        review_after=review_after,
        reason=_require_reason(reason),
    )
    updated = SprintLedger(
        schema=ledger.schema,
        mode=ledger.mode,
        state=ledger.state,
        active=ledger.active,
        paused=ledger.paused,
        sprints=ledger.sprints,
        backlog=(*ledger.backlog, item),
        draft_pool=ledger.draft_pool,
    )
    save_ledger(updated, root=root)
    return updated


def add_to_draft_pool(
    document: str,
    *,
    reason: str,
    kind: str = "execution",
    root: Path | None = None,
    today: str | None = None,
) -> SprintLedger:
    ledger = load_ledger(root)
    _validate_item_kind(kind)
    doc_id = require_doc_id(document)
    if _live_membership(ledger).get(doc_id):
        raise SprintLedgerError(f"{doc_id} is already in {_live_membership(ledger)[doc_id]}")
    item = DraftPoolItem(document=doc_id, kind=kind, added=today or _today(), reason=_require_reason(reason))
    updated = SprintLedger(
        schema=ledger.schema,
        mode=ledger.mode,
        state=ledger.state,
        active=ledger.active,
        paused=ledger.paused,
        sprints=ledger.sprints,
        backlog=ledger.backlog,
        draft_pool=(*ledger.draft_pool, item),
    )
    save_ledger(updated, root=root)
    return updated


def rollover_ledger(
    name: str,
    outcomes: dict[str, dict[str, Any]],
    docs: list[Any],
    *,
    root: Path | None = None,
    today: str | None = None,
) -> SprintLedger:
    ledger = load_ledger(root)
    if ledger.state != "active" or not ledger.active_sprint:
        raise SprintLedgerError("sprint ledger is not active")
    active = ledger.active_sprint
    active_open = [item for item in active.items if item.outcome is None]
    outcome_docs = {require_doc_id(doc_id) for doc_id in outcomes}
    active_docs = {item.document for item in active_open}
    missing = sorted(active_docs - outcome_docs)
    extra = sorted(outcome_docs - active_docs)
    if missing:
        raise SprintLedgerError(f"outcomes missing active sprint item(s): {', '.join(missing)}")
    if extra:
        raise SprintLedgerError(f"outcomes include document(s) not open in active sprint: {', '.join(extra)}")

    by_id = {doc.doc_id: doc for doc in docs}
    today_str = today or _today()
    next_sprint = SprintRecord(
        id=generate_sprint_id(),
        name=name,
        status="active",
        started=today_str,
        closed=None,
        items=(),
    )
    closed_items: list[SprintItem] = []
    next_items: list[SprintItem] = []
    for item in active.items:
        if item.outcome is not None:
            closed_items.append(item)
            continue
        raw = outcomes[item.document]
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
            kind == "completed"
            and snapshot["primary_total"] > 0
            and snapshot["primary_done"] != snapshot["primary_total"]
        )
        if completed_incomplete:
            raise SprintLedgerError(f"{item.document} cannot be completed unless primary acceptance criteria are 100%")
        outcome = {
            "kind": kind,
            "at": today_str,
            "reason": reason or None,
            "to_sprint": next_sprint.id if kind == "carried_over" else raw.get("to_sprint"),
            "to_document": str(raw.get("to_document", "")).strip().upper() if raw.get("to_document") else None,
            "evidence": raw.get("evidence") or {"commits": []},
            "snapshot": snapshot,
        }
        closed_items.append(_replace_item(item, outcome=outcome))
        if kind == "carried_over":
            next_items.append(
                SprintItem(
                    document=item.document,
                    kind=item.kind,
                    source="carryover",
                    added=today_str,
                    carryover_from=active.id,
                    outcome=None,
                )
            )
    closed_active = _replace_sprint(active, status="closed", closed=today_str, items=tuple(closed_items))
    next_sprint = _replace_sprint(next_sprint, items=tuple(next_items))
    updated = SprintLedger(
        schema=ledger.schema,
        mode=ledger.mode,
        state="active",
        active=next_sprint.id,
        paused=None,
        sprints=(*(s if s.id != active.id else closed_active for s in ledger.sprints), next_sprint),
        backlog=ledger.backlog,
        draft_pool=ledger.draft_pool,
    )
    save_ledger(updated, root=root)
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


def validate_ledger(root: Path, docs: list[Any]) -> SprintValidation:
    if not sprint_mode_enabled(root):
        return SprintValidation()
    errors: list[str] = []
    warnings: list[str] = []
    try:
        ledger = load_ledger(root)
    except Exception as e:
        return SprintValidation(errors=(str(e),))

    by_id = {doc.doc_id: doc for doc in docs}
    sprint_ids: set[str] = set()
    active_sprints: list[str] = []
    for idx, sprint in enumerate(ledger.sprints):
        where = f"sprints[{idx}] {sprint.id or '<missing>'}"
        try:
            sid = require_sprint_id(sprint.id)
        except ValueError as e:
            errors.append(f"{where}: {e}")
            sid = sprint.id
        if sid in sprint_ids:
            errors.append(f"{where}: duplicate sprint id {sid}")
        sprint_ids.add(sid)
        if not sprint.name:
            errors.append(f"{where}: name is required")
        if sprint.status not in {"active", "closed"}:
            errors.append(f"{where}: status must be active or closed")
        if not sprint.started:
            errors.append(f"{where}: started is required")
        if sprint.status == "active":
            active_sprints.append(sprint.id)
            if sprint.closed:
                errors.append(f"{where}: active sprint must not have closed date")
        if sprint.status == "closed" and not sprint.closed:
            errors.append(f"{where}: closed sprint requires closed date")
        _validate_sprint_items(errors, sprint, by_id, sprint_ids)

    if ledger.state == "active":
        if ledger.active is None:
            errors.append("active state requires active sprint id")
        elif ledger.active not in active_sprints:
            errors.append(f"active sprint {ledger.active} does not match an active sprint record")
        if len(active_sprints) != 1:
            errors.append(f"active state requires exactly one active sprint, found {len(active_sprints)}")
        if ledger.paused is not None:
            errors.append("active state must not include paused metadata")
    elif ledger.state == "paused":
        if ledger.active is not None:
            errors.append("paused state must not have active sprint id")
        if active_sprints:
            errors.append("paused state must not include active sprint records")
        if not ledger.paused or not ledger.paused.get("since") or not ledger.paused.get("reason"):
            errors.append("paused state requires paused.since and paused.reason")
    else:
        errors.append("state must be active or paused")

    live = _live_membership(ledger)
    _validate_live_membership(errors, ledger)
    for item in ledger.backlog:
        _validate_backlog_item(errors, warnings, item, by_id)
    for item in ledger.draft_pool:
        _validate_draft_pool_item(errors, item, by_id)

    missing = _missing_post_init_specs(ledger, docs, live)
    for doc in missing:
        errors.append(
            f"{doc.doc_id}: non-terminal SPEC created after sprint mode was initialized must be in active sprint, "
            "backlog, or draft_pool"
        )

    _validate_live_reference_health(errors, ledger, by_id)
    _validate_carryover_linearity(errors, ledger)
    return SprintValidation(errors=tuple(errors), warnings=tuple(warnings))


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
            raise SprintLedgerError('sprint mode is not enabled; run `decree sprint init "Sprint 1"`')
        return None
    ledger = load_ledger(project_root)
    include_context = bool(getattr(args, "include_context", False))
    by_id = {doc.doc_id: doc for doc in docs}

    if getattr(args, "backlog", False):
        return _scope_from_items(
            f"backlog ({len(ledger.backlog)} items)",
            ledger.backlog,
            by_id,
            include_context=include_context,
        )
    if getattr(args, "draft_pool", False):
        return _scope_from_items(
            f"draft pool ({len(ledger.draft_pool)} items)",
            ledger.draft_pool,
            by_id,
            include_context=include_context,
        )
    if getattr(args, "all_sprints", False):
        items = [item for sprint in ledger.sprints for item in sprint.items]
        return _scope_from_items("all sprints", items, by_id, include_context=include_context)
    sprint_id = getattr(args, "sprint", None)
    if sprint_id:
        sprint_id = require_sprint_id(sprint_id)
        for sprint in ledger.sprints:
            if sprint.id == sprint_id:
                return _scope_from_items(
                    f"sprint {sprint.id} ({sprint.name})",
                    sprint.items,
                    by_id,
                    include_context=include_context,
                )
        raise SprintLedgerError(f"sprint not found: {sprint_id}")
    if ledger.state == "paused":
        reason = ledger.paused.get("reason") if ledger.paused else "no reason recorded"
        raise SprintLedgerError(f"sprint mode is paused ({reason}); pass --backlog, --draft-pool, or --corpus")
    active = ledger.active_sprint
    if not active:
        raise SprintLedgerError("active sprint not found")
    return _scope_from_items(
        f"active sprint {active.id} ({active.name})",
        active.items,
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


def _validate_sprint_items(
    errors: list[str],
    sprint: SprintRecord,
    by_id: dict[str, Any],
    sprint_ids: set[str],
) -> None:
    seen_docs: set[str] = set()
    for idx, item in enumerate(sprint.items):
        where = f"{sprint.id}.items[{idx}] {item.document or '<missing>'}"
        _validate_common_item(errors, item.document, item.kind, where, by_id)
        if item.document in seen_docs:
            errors.append(f"{where}: duplicate document in sprint")
        seen_docs.add(item.document)
        if sprint.status == "active" and item.outcome is not None:
            errors.append(f"{where}: active sprint item must not have outcome")
        if sprint.status == "closed":
            if item.outcome is None:
                errors.append(f"{where}: closed sprint item requires outcome")
            else:
                _validate_outcome(errors, item.outcome, where, sprint_ids)
        if item.kind == "execution" and item.document in by_id and not _is_execution_doc(by_id[item.document]):
            errors.append(f"{where}: execution items must reference configured SPEC documents")
        is_live_active_item = sprint.status == "active" and item.outcome is None
        terminal_live_execution = (
            item.kind == "execution"
            and item.document in by_id
            and is_live_active_item
            and _is_terminal(by_id[item.document])
        )
        if terminal_live_execution:
            errors.append(f"{where}: terminal SPEC requires explicit reopen semantics before sprint membership")


def _validate_common_item(errors: list[str], document: str, kind: str, where: str, by_id: dict[str, Any]) -> None:
    try:
        require_doc_id(document)
    except ValueError as e:
        errors.append(f"{where}: {e}")
    if document not in by_id:
        errors.append(f"{where}: document not found")
    if kind not in ITEM_KINDS:
        errors.append(f"{where}: kind must be one of {sorted(ITEM_KINDS)}")


def _validate_backlog_item(errors: list[str], warnings: list[str], item: BacklogItem, by_id: dict[str, Any]) -> None:
    where = f"backlog {item.document or '<missing>'}"
    _validate_common_item(errors, item.document, item.kind, where, by_id)
    if not item.source:
        errors.append(f"{where}: source is required")
    if not item.since:
        errors.append(f"{where}: since is required")
    if not item.reason:
        errors.append(f"{where}: reason is required")
    if item.kind == "execution" and item.document in by_id and not _is_execution_doc(by_id[item.document]):
        errors.append(f"{where}: execution items must reference configured SPEC documents")
    if item.kind == "execution" and item.document in by_id and _is_terminal(by_id[item.document]):
        errors.append(f"{where}: terminal SPEC requires explicit reopen semantics before sprint membership")
    if item.since:
        age = (_date_obj(_today()) - _date_obj(item.since)).days
        review_due = item.review_after is None or _date_obj(item.review_after) <= _date_obj(_today())
        if age > BACKLOG_WARN_AFTER_DAYS and review_due:
            warnings.append(f"{where}: backlog item is {age} days old; review or update review_after")


def _validate_draft_pool_item(errors: list[str], item: DraftPoolItem, by_id: dict[str, Any]) -> None:
    where = f"draft_pool {item.document or '<missing>'}"
    _validate_common_item(errors, item.document, item.kind, where, by_id)
    if not item.reason:
        errors.append(f"{where}: reason is required")
    if item.kind == "execution" and item.document in by_id and not _is_execution_doc(by_id[item.document]):
        errors.append(f"{where}: execution items must reference configured SPEC documents")
    if item.kind == "execution" and item.document in by_id and _is_terminal(by_id[item.document]):
        errors.append(f"{where}: terminal SPEC requires explicit reopen semantics before sprint membership")


def _validate_outcome(errors: list[str], outcome: dict[str, Any], where: str, sprint_ids: set[str]) -> None:
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
        done = int(snapshot.get("primary_done", -1))
        total = int(snapshot.get("primary_total", -1))
        if total < 0 or done < 0 or (total > 0 and done != total):
            errors.append(f"{where}: completed outcome requires snapshot primary progress at 100%")
    if kind == "carried_over":
        to_sprint = str(outcome.get("to_sprint", "")).strip().upper()
        if not to_sprint:
            errors.append(f"{where}: carried_over outcome requires to_sprint")
        elif to_sprint not in sprint_ids:
            # The successor can be later in the file; linearity validation gives
            # the definitive verdict after all sprint IDs have been collected.
            pass
    if kind == "superseded" and not outcome.get("to_document"):
        errors.append(f"{where}: superseded outcome requires to_document")


def _validate_carryover_linearity(errors: list[str], ledger: SprintLedger) -> None:
    sprint_index = {sprint.id: idx for idx, sprint in enumerate(ledger.sprints)}
    sprint_by_id = {sprint.id: sprint for sprint in ledger.sprints}
    for idx, sprint in enumerate(ledger.sprints):
        for item in sprint.items:
            if not item.outcome or item.outcome.get("kind") != "carried_over":
                continue
            to_sprint = str(item.outcome.get("to_sprint", "")).strip().upper()
            if to_sprint not in sprint_index:
                errors.append(f"{sprint.id} {item.document}: carryover target sprint not found: {to_sprint}")
                continue
            if sprint_index[to_sprint] != idx + 1:
                errors.append(f"{sprint.id} {item.document}: carryover must target the immediate successor sprint")
                continue
            target = sprint_by_id[to_sprint]
            if not any(i.document == item.document and i.carryover_from == sprint.id for i in target.items):
                errors.append(f"{sprint.id} {item.document}: successor sprint missing matching carryover item")


def _validate_live_reference_health(errors: list[str], ledger: SprintLedger, by_id: dict[str, Any]) -> None:
    live_ids = [doc_id for doc_id, scope in _live_membership(ledger).items() if scope.startswith("active sprint")]
    for doc_id in live_ids:
        doc = by_id.get(doc_id)
        if doc is None:
            continue
        for ref in doc.meta.references or []:
            target = by_id.get(ref)
            if target is None or target.doc_type is None:
                continue
            if target.meta.status in target.doc_type.warn_on_reference:
                errors.append(
                    f"{doc_id}: active sprint item references stale/dead document {ref} ({target.meta.status})"
                )


def _missing_post_init_specs(ledger: SprintLedger, docs: list[Any], live: dict[str, str]) -> list[Any]:
    if not ledger.sprints:
        return []
    first_started = _date_obj(ledger.sprints[0].started)
    closed_members = {item.document for sprint in ledger.sprints for item in sprint.items if item.outcome is not None}
    missing: list[Any] = []
    for doc in docs:
        if not _is_execution_doc(doc):
            continue
        if _is_terminal(doc):
            continue
        if doc.doc_id in live or doc.doc_id in closed_members:
            continue
        if doc.meta.date >= first_started:
            missing.append(doc)
    return missing


def _live_membership(ledger: SprintLedger) -> dict[str, str]:
    membership: dict[str, str] = {}
    active = ledger.active_sprint
    if active is not None:
        for item in active.items:
            if item.outcome is None:
                membership[item.document] = f"active sprint {active.id}"
    for item in ledger.backlog:
        membership[item.document] = "backlog"
    for item in ledger.draft_pool:
        membership[item.document] = "draft_pool"
    return membership


def _validate_live_membership(errors: list[str], ledger: SprintLedger) -> None:
    seen: dict[str, str] = {}
    active = ledger.active_sprint
    if active is not None:
        for item in active.items:
            if item.outcome is not None:
                continue
            _record_live(errors, seen, item.document, f"active sprint {active.id}")
    for item in ledger.backlog:
        _record_live(errors, seen, item.document, "backlog")
    for item in ledger.draft_pool:
        _record_live(errors, seen, item.document, "draft_pool")


def _record_live(errors: list[str], seen: dict[str, str], document: str, scope: str) -> None:
    previous = seen.get(document)
    if previous:
        errors.append(f"{document}: live document appears in both {previous} and {scope}")
        return
    seen[document] = scope


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


def _replace_sprint(sprint: SprintRecord, **changes: Any) -> SprintRecord:
    data = {
        "id": sprint.id,
        "name": sprint.name,
        "status": sprint.status,
        "started": sprint.started,
        "closed": sprint.closed,
        "items": sprint.items,
    }
    data.update(changes)
    return SprintRecord(**data)


def _replace_item(item: SprintItem, **changes: Any) -> SprintItem:
    data = {
        "document": item.document,
        "kind": item.kind,
        "source": item.source,
        "added": item.added,
        "carryover_from": item.carryover_from,
        "outcome": item.outcome,
    }
    data.update(changes)
    return SprintItem(**data)


def _replace_sprints(ledger: SprintLedger, replacement: SprintRecord) -> SprintLedger:
    return SprintLedger(
        schema=ledger.schema,
        mode=ledger.mode,
        state=ledger.state,
        active=ledger.active,
        paused=ledger.paused,
        sprints=tuple(replacement if sprint.id == replacement.id else sprint for sprint in ledger.sprints),
        backlog=ledger.backlog,
        draft_pool=ledger.draft_pool,
    )


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


def _strip_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_none(v) for v in value]
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
