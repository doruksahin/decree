"""Validate all documents: frontmatter, sections, cross-file integrity, cross-type references."""
import argparse

from pydantic import ValidationError

from madr_tools.log import info, success, fail
from madr_tools.validators import validate_sections, validate_cross_file_integrity, validate_cross_type_references


def run(args: argparse.Namespace | None = None) -> int:
    from madr_tools.config import load_doc_types, get_project_root
    from madr_tools.parser import load

    prefix = "lint"
    doc_types = load_doc_types()
    all_docs = []
    errors: list[str] = []
    total_files = 0

    for dt in doc_types:
        type_dir = get_project_root() / dt.dir
        if not type_dir.exists():
            continue
        paths = sorted(p for p in type_dir.glob("[0-9]*.md") if dt.filename_re.match(p.name))
        total_files += len(paths)
        type_docs = []

        for path in paths:
            rel = path.relative_to(get_project_root())
            try:
                doc = load(path, doc_type=dt)
            except ValidationError as e:
                for err in e.errors():
                    errors.append(f"{rel}: {err['msg']}")
                continue
            except Exception as e:
                errors.append(f"{rel}: {e}")
                continue

            type_docs.append(doc)
            all_docs.append(doc)
            section_errors = validate_sections(doc)
            for msg in section_errors:
                errors.append(f"{rel}: {msg}")

        cross_errors = validate_cross_file_integrity(type_docs)
        errors.extend(cross_errors)

    # Cross-type reference validation
    cross_type_errors = validate_cross_type_references(all_docs)
    errors.extend(cross_type_errors)

    if errors:
        print()
        for e in errors:
            print(e)
        fail(f"{total_files} documents checked. {len(errors)} errors.")
        return 1

    success(f"{total_files} documents validated. 0 errors.")
    return 0
