"""
MADR v4.0.0 format rules — core defaults + project overrides.

Core rules (statuses, transitions, MADR sections) are hardcoded.
Project-specific extensions (extra sections, adr_dir) are loaded
from pyproject.toml [tool.adr] at runtime.
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
    """Walk up from cwd to find the directory containing pyproject.toml."""
    for parent in (Path.cwd(), *Path.cwd().parents):
        if (parent / "pyproject.toml").exists():
            return parent
    raise FileNotFoundError("Could not find pyproject.toml in any parent directory")


@functools.lru_cache(maxsize=1)
def _load_project_config() -> dict:
    """Load [tool.adr] from the consuming project's pyproject.toml."""
    pyproject = get_project_root() / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    return data.get("tool", {}).get("adr", {})


# ── Paths (project-configurable) ─────────────────────────


def get_adr_dir() -> Path:
    cfg = _load_project_config()
    rel = cfg.get("adr_dir", "docs/adr")
    return get_project_root() / rel


def get_adr_index_file() -> Path:
    return get_adr_dir() / "index.md"


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
DEFAULT_TEMPLATE = "madr-v4.md"


def get_template_path() -> Path:
    """Return project-override template or default."""
    cfg = _load_project_config()
    custom = cfg.get("template")
    if custom:
        p = get_project_root() / custom
        if p.exists():
            return p
    return TEMPLATE_DIR / DEFAULT_TEMPLATE


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

# ── Sections (core + project-configurable) ────────────────
MADR_REQUIRED_SECTIONS = (
    "Context and Problem Statement",
    "Considered Options",
    "Decision Outcome",
)


def get_project_sections() -> tuple[str, ...]:
    cfg = _load_project_config()
    return tuple(cfg.get("project_sections", ()))


def get_required_sections() -> tuple[str, ...]:
    return (*MADR_REQUIRED_SECTIONS, *get_project_sections())


OPTIONAL_SECTIONS = (
    "Decision Drivers",
    "Pros and Cons of the Options",
    "More Information",
)

# ── Section descriptions (core + project-configurable) ────
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


def get_section_descriptions() -> dict[str, str]:
    cfg = _load_project_config()
    project_descs = cfg.get("project_section_descriptions", {})
    return {**MADR_SECTION_DESCRIPTIONS, **project_descs}


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
    """Load document types from [tool.doc.types.*] or fall back to [tool.adr]."""
    from .doctypes import DocType, ADR_DEFAULT
    pyproject = get_project_root() / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)

    tool = data.get("tool", {})
    doc_config = tool.get("doc", {}).get("types", {})

    if doc_config:
        return tuple(_build_doc_type(name, cfg) for name, cfg in doc_config.items())

    # Fallback: build ADR type from [tool.adr]
    adr_cfg = tool.get("adr", {})
    if adr_cfg:
        return (_adr_from_legacy_config(adr_cfg),)

    return (ADR_DEFAULT,)


def find_doc_type(doc_id: str):
    """Look up the DocType for a given document ID (e.g., 'ADR-0001' → adr type)."""
    for dt in load_doc_types():
        if dt.ref_re.match(doc_id):
            return dt
    raise ValueError(f"No document type matches ID '{doc_id}'")


def _build_doc_type(name: str, cfg: dict):
    """Build a DocType from a [tool.doc.types.*] config section."""
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
    )


def _adr_from_legacy_config(cfg: dict):
    """Build ADR DocType from legacy [tool.adr] config."""
    from .doctypes import ADR_DEFAULT
    extra_sections = tuple(cfg.get("project_sections", ()))
    from .doctypes import DocType
    return DocType(
        name=ADR_DEFAULT.name,
        prefix=ADR_DEFAULT.prefix,
        digits=ADR_DEFAULT.digits,
        dir=cfg.get("adr_dir", ADR_DEFAULT.dir),
        initial_status=ADR_DEFAULT.initial_status,
        statuses=ADR_DEFAULT.statuses,
        transitions=ADR_DEFAULT.transitions,
        actions=ADR_DEFAULT.actions,
        required_sections=(*ADR_DEFAULT.required_sections, *extra_sections),
        warn_on_reference=ADR_DEFAULT.warn_on_reference,
        status_field_requirements=ADR_DEFAULT.status_field_requirements,
        section_descriptions={
            **ADR_DEFAULT.section_descriptions,
            **cfg.get("project_section_descriptions", {}),
        },
        template=cfg.get("template"),
    )


def _parse_field_requirements(cfg: dict) -> dict[str, tuple[str, ...]]:
    """Parse status_field_requirements from config, defaulting to empty."""
    raw = cfg.get("status_field_requirements", {})
    return {k: tuple(v) for k, v in raw.items()}
