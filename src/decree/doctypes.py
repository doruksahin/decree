"""Document type definitions — the core abstraction for multi-type support."""

import re
from dataclasses import dataclass, field

from decree.identity import ULID_PATTERN


@dataclass(frozen=True)
class DocType:
    """A document type with its own ID scheme, lifecycle, and structure."""

    name: str
    prefix: str
    dir: str  # relative to project root
    initial_status: str
    statuses: tuple[str, ...]
    transitions: dict[str, tuple[str, ...]]
    actions: dict[str, str]  # verb → target status
    required_sections: tuple[str, ...] = ()
    warn_on_reference: tuple[str, ...] = ()  # "dead" statuses — referencing these is flagged
    status_field_requirements: dict[str, tuple[str, ...]] = field(default_factory=dict)
    section_descriptions: dict[str, str] = field(default_factory=dict)
    template: str | None = None  # relative path to custom template, or None for built-in
    c4: object | None = None  # C4Config instance when C4 is enabled, None otherwise
    coherence: object | None = None  # CoherenceConfig instance when configured, None otherwise
    legacy_digits: int = 4  # used only by `decree migrate ids` for old numeric corpora

    @property
    def ref_re(self) -> re.Pattern:
        return re.compile(rf"^{re.escape(self.prefix)}-{ULID_PATTERN}$")

    @property
    def filename_re(self) -> re.Pattern:
        return re.compile(rf"^{re.escape(self.prefix.lower())}-{ULID_PATTERN.lower()}-.+\.md$")

    @property
    def terminal_statuses(self) -> frozenset[str]:
        return frozenset(s for s, t in self.transitions.items() if not t)

    # NOTE: warn_on_reference is DIFFERENT from terminal_statuses.
    # "implemented" is terminal (no transitions) but healthy to reference.
    # "rejected", "superseded", "deprecated" are terminal AND dead.


ADR_DEFAULT = DocType(
    name="adr",
    prefix="ADR",
    dir="docs/adr",
    initial_status="proposed",
    statuses=("proposed", "accepted", "rejected", "deprecated", "superseded"),
    transitions={
        "proposed": ("accepted", "rejected"),
        "accepted": ("deprecated", "superseded"),
        "rejected": (),
        "deprecated": (),
        "superseded": (),
    },
    actions={
        "accept": "accepted",
        "reject": "rejected",
        "deprecate": "deprecated",
        "supersede": "superseded",
    },
    warn_on_reference=("rejected", "deprecated", "superseded"),
    status_field_requirements={
        "proposed": (),
        "accepted": (),
        "rejected": (),
        "deprecated": (),
        "superseded": ("superseded-by",),
    },
    required_sections=(
        "Context and Problem Statement",
        "Considered Options",
        "Decision Outcome",
    ),
    section_descriptions={
        "Context and Problem Statement": "What is the issue or force motivating this decision?",
        "Considered Options": (
            "Bullet list of candidate options. Detailed pros/cons go in 'Pros and Cons of the Options'."
        ),
        "Decision Outcome": (
            "State the chosen option and why. Use: 'Chosen option: \"[option]\", because [justification]'."
        ),
        "Decision Drivers": "Bullet list of forces or concerns influencing the decision.",
        "Pros and Cons of the Options": "Detailed per-option pros/cons as H3 subsections.",
        "More Information": "Links to related ADRs, external references, meeting notes.",
    },
    legacy_digits=4,
)
