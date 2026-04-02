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
FILENAME_RE = re.compile(r"^ADR-(\d{4})-.+\.md$")
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SLUG_MAX_LENGTH = 60

# ── Link format ───────────────────────────────────────────
ADR_REF_RE = re.compile(r"^ADR-\d{4}$")

# ── Defensive assertions (core only) ─────────────────────
assert set(STATUS_FIELD_REQUIREMENTS) == set(STATUSES)
assert set(VALID_TRANSITIONS) == set(STATUSES)
