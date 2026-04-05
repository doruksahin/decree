"""
Decree configuration — loaded from decree.toml at project root.

Config schema:
    [types.<name>]
    dir = "decree/adr"
    prefix = "ADR"
    ...

decree.toml is the only supported config format. No pyproject.toml fallback.
"""

import functools
import re
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib

MADR_SPEC_VERSION = "4.0.0"

# ── Project root discovery ────────────────────────────────


@functools.lru_cache(maxsize=1)
def get_project_root() -> Path:
    """Walk up from cwd to find the directory containing decree.toml."""
    for parent in (Path.cwd(), *Path.cwd().parents):
        if (parent / "decree.toml").exists():
            return parent
    raise FileNotFoundError(
        "decree.toml not found. Run 'decree init' or create one."
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

# ── Status lifecycle (core) ──────────────────────────────
STATUSES = ("proposed", "accepted", "rejected", "deprecated", "superseded")

VALID_TRANSITIONS = {
    "proposed": ("accepted", "rejected"),
    "accepted": ("deprecated", "superseded"),
    "rejected": (),
    "deprecated": (),
    "superseded": (),
}

STATUS_FIELD_REQUIREMENTS = {
    "proposed": (),
    "accepted": (),
    "rejected": (),
    "deprecated": (),
    "superseded": ("superseded-by",),
}

# Cross-file invariants (enforced by lint command):
#   - If ADR-X has superseded-by: ADR-Y, then ADR-Y must have supersedes: ADR-X
#   - If ADR-X has supersedes: ADR-Y, then ADR-Y must have status: superseded
#   - If supersedes is present, the referenced ADR file must exist
#   - If superseded-by is present, the referenced ADR file must exist

# ── Sections (core) ──────────────────────────────────────
MADR_REQUIRED_SECTIONS = (
    "Context and Problem Statement",
    "Considered Options",
    "Decision Outcome",
)

OPTIONAL_SECTIONS = (
    "Decision Drivers",
    "Pros and Cons of the Options",
    "More Information",
)

# ── Section descriptions (core) ──────────────────────────
MADR_SECTION_DESCRIPTIONS = {
    "Context and Problem Statement": "What is the issue or force motivating this decision?",
    "Considered Options": (
        "Bullet list of candidate options. Detailed pros/cons go in "
        "'Pros and Cons of the Options'."
    ),
    "Decision Outcome": (
        "State the chosen option and why. Use: "
        "'Chosen option: \"[option]\", because [justification]'."
    ),
    "Decision Drivers": "Bullet list of forces or concerns influencing the decision.",
    "Pros and Cons of the Options": "Detailed per-option pros/cons as H3 subsections.",
    "More Information": "Links to related ADRs, external references, meeting notes.",
}

# ── File naming ───────────────────────────────────────────
FILENAME_RE = re.compile(r"^(\d{4})-.+\.md$")  # e.g. 0001-use-pulp-solver.md
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SLUG_MAX_LENGTH = 60

# ── Link format ───────────────────────────────────────────
ADR_REF_RE = re.compile(r"^ADR-\d{4}$")

# ── Defensive assertions (core only) ─────────────────────
assert set(STATUS_FIELD_REQUIREMENTS) == set(STATUSES)
assert set(VALID_TRANSITIONS) == set(STATUSES)


# ── Multi-type DocType loading ────────────────────────────

@functools.lru_cache(maxsize=1)
def load_doc_types():
    """Load document types from [types.*] in decree.toml."""
    decree_toml = get_project_root() / "decree.toml"
    with open(decree_toml, "rb") as f:
        data = tomllib.load(f)

    types_config = data.get("types", {})
    if not types_config:
        raise ValueError(
            "decree.toml has no [types.*] sections. "
            "Define at least one document type."
        )

    return tuple(_build_doc_type(name, cfg) for name, cfg in types_config.items())


def find_doc_type(doc_id: str):
    """Look up the DocType for a given document ID (e.g., 'ADR-0001' → adr type)."""
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
                raise ValueError(
                    f"Type '{name}': transition target '{t}' not in statuses {statuses}"
                )

    # Fill missing terminal statuses
    for s in statuses:
        if s not in transitions:
            transitions[s] = ()

    return DocType(
        name=name,
        prefix=cfg["prefix"],
        digits=cfg.get("digits", 4),
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
    )


def _parse_c4_config(cfg: dict):
    """Parse [types.*.c4] section into a C4Config, or None if absent."""
    c4_raw = cfg.get("c4")
    if not c4_raw or not c4_raw.get("enabled"):
        return None
    from .c4 import C4Config
    return C4Config(
        enabled=True,
        id_field=c4_raw.get("id_field", "id"),
        levels=tuple(c4_raw.get("levels", ("system", "container", "component"))),
    )


def _parse_field_requirements(cfg: dict) -> dict[str, tuple[str, ...]]:
    """Parse status_field_requirements from config, defaulting to empty."""
    raw = cfg.get("status_field_requirements", {})
    return {k: tuple(v) for k, v in raw.items()}
