"""
Decree configuration — loaded from decree.toml at project root.

Config schema:
    [types.<name>]
    dir = "decree/adr"
    prefix = "ADR"
    ...

decree.toml is the only supported config format. No pyproject.toml fallback.
"""

import dataclasses
import functools
import re
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib

# ── Project root discovery ────────────────────────────────


@functools.lru_cache(maxsize=1)
def get_project_root() -> Path:
    """Walk up from cwd to find the directory containing decree.toml."""
    for parent in (Path.cwd(), *Path.cwd().parents):
        if (parent / "decree.toml").exists():
            return parent
    raise FileNotFoundError(
        "decree.toml not found. Create one in your project root.\n"
        "See https://github.com/doruksahin/decree#configuration"
    )


# ── Frontmatter (core) ───────────────────────────────────
REQUIRED_FRONTMATTER = ("status", "date")
OPTIONAL_FRONTMATTER = (
    "supersedes",
    "superseded-by",
    "deciders",
    "consulted",
    "informed",
)
DATE_FORMAT = "%Y-%m-%d"

# ── File naming ───────────────────────────────────────────
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SLUG_MAX_LENGTH = 60


# ── Multi-type DocType loading ────────────────────────────


@functools.lru_cache(maxsize=1)
def load_doc_types():
    """Load document types from [types.*] in decree.toml."""
    decree_toml = get_project_root() / "decree.toml"
    with open(decree_toml, "rb") as f:
        data = tomllib.load(f)

    types_config = data.get("types", {})
    if not types_config:
        raise ValueError("decree.toml has no [types.*] sections. Define at least one document type.")

    return tuple(_build_doc_type(name, cfg) for name, cfg in types_config.items())


def find_doc_type(doc_id: str):
    """Look up the DocType for a given document ID (e.g., 'ADR-01KT22NMRV7GMAXKWSBEEN68KE' → adr type)."""
    for dt in load_doc_types():
        if dt.ref_re.match(doc_id):
            return dt
    raise ValueError(f"No document type matches ID '{doc_id}'")


def _build_doc_type(name: str, cfg: dict):
    """Build a DocType from a [types.*] config section."""
    from .doctypes import DocType

    statuses = tuple(cfg["statuses"])
    transitions = {k: tuple(v) for k, v in cfg.get("transitions", {}).items()}

    # Validate transitions reference valid statuses
    for src, targets in transitions.items():
        if src not in statuses:
            raise ValueError(f"Type '{name}': transition source '{src}' not in statuses")
        for t in targets:
            if t not in statuses:
                raise ValueError(f"Type '{name}': transition target '{t}' not in statuses {statuses}")

    # Fill missing terminal statuses
    for s in statuses:
        if s not in transitions:
            transitions[s] = ()

    return DocType(
        name=name,
        prefix=cfg["prefix"],
        dir=cfg.get("dir", f"docs/{name}"),
        initial_status=cfg.get("initial_status", statuses[0]),
        statuses=statuses,
        transitions=transitions,
        actions=cfg.get("actions", {}),
        warn_on_reference=tuple(cfg.get("warn_on_reference", ())),
        required_sections=tuple(cfg.get("required_sections", ())),
        status_field_requirements=_parse_field_requirements(cfg),
        section_descriptions=cfg.get("section_descriptions", {}),
        template=cfg.get("template"),
        c4=_parse_c4_config(cfg),
        coherence=_parse_coherence_config(name, cfg),
        legacy_digits=cfg.get("digits", 4),
    )


def _parse_c4_config(cfg: dict):
    """Parse [types.*.c4] section into a C4Config, or None if absent."""
    c4_raw = cfg.get("c4")
    if not c4_raw or not c4_raw.get("enabled"):
        return None
    from .c4 import C4Config

    return C4Config(
        enabled=True,
        id_field=c4_raw.get("id_field", "c4_id"),
        levels=tuple(c4_raw.get("levels", ("system", "container", "component"))),
    )


def _parse_field_requirements(cfg: dict) -> dict[str, tuple[str, ...]]:
    """Parse status_field_requirements from config, defaulting to empty."""
    raw = cfg.get("status_field_requirements", {})
    return {k: tuple(v) for k, v in raw.items()}


# ── SPEC-01KT22NMRYNFYM7EN80WS2HD6F coherence config ─────────────────────────────


@dataclasses.dataclass(frozen=True)
class CoherenceConfig:
    """Per-type opt-in coherence gates (SPEC-01KT22NMRYNFYM7EN80WS2HD6F).

    All gates default to False. Set in decree.toml under
    `[types.<name>.coherence]`. Unknown keys are rejected at load time.
    """

    terminal_status_progress: bool = False
    deferred_sections_separated: bool = False
    unreferenced_active: bool = False
    unreferenced_after_days: int = 30
    deferred_sections: tuple[str, ...] = ()
    expected_referrer_types: tuple[str, ...] = ()
    active_statuses: tuple[str, ...] = ()


_COHERENCE_KEYS = frozenset(
    {
        "terminal_status_progress",
        "deferred_sections_separated",
        "unreferenced_active",
        "unreferenced_after_days",
        "deferred_sections",
        "expected_referrer_types",
        "active_statuses",
    }
)


def _parse_coherence_config(type_name: str, cfg: dict) -> CoherenceConfig | None:
    """Parse `[types.<name>.coherence]` into a CoherenceConfig, or None if absent.

    Unknown keys raise ValueError so typos surface at load time.
    """
    raw = cfg.get("coherence")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"Type '{type_name}': [types.{type_name}.coherence] must be a table, got {type(raw).__name__}")
    unknown = set(raw.keys()) - _COHERENCE_KEYS
    if unknown:
        raise ValueError(
            f"Type '{type_name}': unknown keys in [types.{type_name}.coherence]: "
            f"{sorted(unknown)}. Allowed: {sorted(_COHERENCE_KEYS)}"
        )
    return CoherenceConfig(
        terminal_status_progress=bool(raw.get("terminal_status_progress", False)),
        deferred_sections_separated=bool(raw.get("deferred_sections_separated", False)),
        unreferenced_active=bool(raw.get("unreferenced_active", False)),
        unreferenced_after_days=int(raw.get("unreferenced_after_days", 30)),
        deferred_sections=tuple(raw.get("deferred_sections", ())),
        expected_referrer_types=tuple(raw.get("expected_referrer_types", ())),
        active_statuses=tuple(raw.get("active_statuses", ())),
    )


def _parse_coherence_exceptions(type_name: str, cfg: dict) -> dict[str, frozenset[str]]:
    """Parse `[types.<name>.coherence_exceptions]` into a {gate: frozenset(doc_id)} map.

    SPEC-01KT22NMRZ4W0CFDSJVHVQ8JBR: each gate-name key maps to a list of doc IDs to skip when that
    gate runs. Used both by the live gate (skip listed docs) and by the audit
    (still report, but flag as "deferred via exception").

    Returns an empty dict if the block is absent. Unknown gate names are *not*
    rejected (forward-compat): the audit/gate code simply won't consult them.
    """
    raw = cfg.get("coherence_exceptions")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"Type '{type_name}': [types.{type_name}.coherence_exceptions] must be a table, got {type(raw).__name__}"
        )
    out: dict[str, frozenset[str]] = {}
    for gate_name, ids in raw.items():
        if not isinstance(ids, list):
            raise ValueError(
                f"Type '{type_name}': [types.{type_name}.coherence_exceptions.{gate_name}] "
                f"must be a list of doc IDs, got {type(ids).__name__}"
            )
        out[gate_name] = frozenset(str(i) for i in ids)
    return out


def load_coherence_exceptions() -> dict[str, dict[str, frozenset[str]]]:
    """Load coherence exceptions for every configured type.

    Returns: {type_name: {gate_name: frozenset(doc_id)}}.
    Cached at the call site via load_doc_types' lifecycle (caller should
    invalidate alongside load_doc_types.cache_clear()).
    """
    decree_toml = get_project_root() / "decree.toml"
    with open(decree_toml, "rb") as f:
        data = tomllib.load(f)
    types_config = data.get("types", {})
    return {name: _parse_coherence_exceptions(name, cfg) for name, cfg in types_config.items()}


# ── SPEC-01KT22NMRYNFYM7EN80WS2HD6F health config (global [health] block) ────────


@dataclasses.dataclass(frozen=True)
class HealthConfig:
    """Global `decree health` defaults from `[health]` in decree.toml.

    CLI flags `--threshold-commits` and `--threshold-days` override these.
    """

    threshold_commits: int = 10
    threshold_days: int = 30


_HEALTH_KEYS = frozenset({"threshold_commits", "threshold_days"})


def load_health_config() -> HealthConfig:
    """Load the optional `[health]` block from decree.toml.

    Returns defaults (10 / 30) when the block is absent. Unknown keys raise
    ValueError so typos are caught at load time.
    """
    decree_toml = get_project_root() / "decree.toml"
    with open(decree_toml, "rb") as f:
        data = tomllib.load(f)
    raw = data.get("health", {})
    if not isinstance(raw, dict):
        raise ValueError(f"[health] must be a table, got {type(raw).__name__}")
    unknown = set(raw.keys()) - _HEALTH_KEYS
    if unknown:
        raise ValueError(f"Unknown keys in [health]: {sorted(unknown)}. Allowed: {sorted(_HEALTH_KEYS)}")
    return HealthConfig(
        threshold_commits=int(raw.get("threshold_commits", 10)),
        threshold_days=int(raw.get("threshold_days", 30)),
    )
