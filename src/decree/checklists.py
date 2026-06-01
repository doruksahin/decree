"""Markdown checklist parsing shared by progress, DDD, lint, and reports."""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_DEFERRED_SECTION_PATTERNS = (
    "What this does NOT do",
    "Deferred",
    "Future work",
    "v2 backlog",
    "Out of scope",
)

_HEADING_RE = re.compile(r"^(#+)\s+(.+?)\s*$", re.MULTILINE)
_CHECKBOX_RE = re.compile(r"^[\s]*[-*]\s+\[([ xX])\]\s+(.+)$")


@dataclass(frozen=True)
class CheckboxItem:
    text: str
    done: bool
    section: str
    section_level: int


@dataclass(frozen=True)
class SectionAcs:
    """All checkbox items in a section."""

    title: str
    level: int
    items: tuple[CheckboxItem, ...]

    @property
    def done(self) -> int:
        return sum(1 for item in self.items if item.done)

    @property
    def total(self) -> int:
        return len(self.items)


@dataclass(frozen=True)
class ParsedAcs:
    """Primary vs. deferred sections of a document."""

    primary: tuple[SectionAcs, ...]
    deferred: tuple[SectionAcs, ...]

    @property
    def primary_done(self) -> int:
        return sum(section.done for section in self.primary)

    @property
    def primary_total(self) -> int:
        return sum(section.total for section in self.primary)

    @property
    def deferred_done(self) -> int:
        return sum(section.done for section in self.deferred)

    @property
    def deferred_total(self) -> int:
        return sum(section.total for section in self.deferred)


def section_is_deferred(section_title: str, patterns: tuple[str, ...]) -> bool:
    """Return True when a section title matches a deferred/out-of-scope pattern."""
    title_lower = section_title.lower()
    return any(pattern.lower() in title_lower for pattern in patterns)


def parse_checkboxes_by_section(
    body: str,
    deferred_patterns: tuple[str, ...] = DEFAULT_DEFERRED_SECTION_PATTERNS,
) -> ParsedAcs:
    """Parse markdown checkboxes, ignoring fenced code blocks and splitting deferred sections."""
    current_section = "(preamble)"
    current_level = 0
    items_by_section: list[tuple[str, int, list[CheckboxItem]]] = [(current_section, current_level, [])]
    in_code_fence = False

    for line in body.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            hashes, title = heading_match.group(1), heading_match.group(2).strip()
            current_section = title
            current_level = len(hashes)
            items_by_section.append((current_section, current_level, []))
            continue
        checkbox_match = _CHECKBOX_RE.match(line)
        if checkbox_match:
            mark, text = checkbox_match.group(1), checkbox_match.group(2).strip()
            items_by_section[-1][2].append(
                CheckboxItem(
                    text=text,
                    done=mark in ("x", "X"),
                    section=current_section,
                    section_level=current_level,
                )
            )

    primary: list[SectionAcs] = []
    deferred: list[SectionAcs] = []
    deferred_ancestor_level: int | None = None
    for title, level, items in items_by_section:
        if deferred_ancestor_level is not None and level <= deferred_ancestor_level:
            deferred_ancestor_level = None
        is_deferred_by_self = section_is_deferred(title, deferred_patterns)
        is_deferred_by_ancestor = deferred_ancestor_level is not None
        if is_deferred_by_self and deferred_ancestor_level is None:
            deferred_ancestor_level = level
        if not items:
            continue
        section = SectionAcs(title=title, level=level, items=tuple(items))
        if is_deferred_by_self or is_deferred_by_ancestor:
            deferred.append(section)
        else:
            primary.append(section)

    return ParsedAcs(primary=tuple(primary), deferred=tuple(deferred))


def count_primary_checkboxes(
    body: str,
    deferred_patterns: tuple[str, ...] = DEFAULT_DEFERRED_SECTION_PATTERNS,
) -> tuple[int, int]:
    """Return completed/total primary acceptance criteria checkboxes."""
    parsed = parse_checkboxes_by_section(body, deferred_patterns)
    return parsed.primary_done, parsed.primary_total
