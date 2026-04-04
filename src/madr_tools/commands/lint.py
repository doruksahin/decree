"""Validate all ADRs: frontmatter, sections, cross-file integrity."""
import argparse

from pydantic import ValidationError

from madr_tools.config import FILENAME_RE, get_adr_dir, get_required_sections
from madr_tools.log import info, error, success, fail
from madr_tools.parser import ADRDocument, load
from madr_tools.validators import validate_sections, validate_cross_file_integrity


def run(args: argparse.Namespace | None = None) -> int:
    prefix = "lint"
    adr_dir = get_adr_dir()

    if not adr_dir.exists():
        info(prefix, f"ADR directory {adr_dir} does not exist — nothing to lint")
        success("0 ADRs validated. 0 errors.")
        return 0

    info(prefix, f"scanning {adr_dir} for ADR files matching [0-9]*.md")
    paths = sorted(p for p in adr_dir.glob("[0-9]*.md") if FILENAME_RE.match(p.name))
    info(prefix, f"found {len(paths)} ADR files")

    if not paths:
        success("0 ADRs validated. 0 errors.")
        return 0

    errors: list[str] = []
    docs: list[ADRDocument] = []
    required = get_required_sections()

    for path in paths:
        rel = path.relative_to(adr_dir.parent.parent)
        try:
            doc = load(path)
        except ValidationError as e:
            for err in e.errors():
                msg = f"{rel}: {err['msg']}"
                errors.append(msg)
            error(prefix, f"validating {path.name} — frontmatter INVALID")
            continue
        except Exception as e:
            msg = f"{rel}: {e}"
            errors.append(msg)
            error(prefix, f"validating {path.name} — parse error: {e}")
            continue

        docs.append(doc)
        section_errors = validate_sections(doc)
        section_count = len(required) - len(section_errors)

        if section_errors:
            for msg in section_errors:
                errors.append(f"{rel}: {msg}")
            info(prefix, f"validating {path.name} — frontmatter OK, {section_count}/{len(required)} sections")
        else:
            info(prefix, f"validating {path.name} — frontmatter OK, {section_count}/{len(required)} sections")

    info(prefix, f"cross-file: checking supersede symmetry across {len(docs)} ADRs")
    cross_errors = validate_cross_file_integrity(docs)
    for msg in cross_errors:
        errors.append(msg)
    info(prefix, f"cross-file: {len(cross_errors)} issues")

    if errors:
        print()  # blank line before errors on stdout
        for e in errors:
            print(e)
        fail(f"{len(paths)} ADRs checked. {len(errors)} errors.")
        return 1

    success(f"{len(paths)} ADRs validated. 0 errors.")
    return 0
