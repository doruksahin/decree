"""Validate all ADRs: frontmatter, sections, cross-file integrity."""
import argparse
import sys

from pydantic import ValidationError

from madr_tools.config import FILENAME_RE, get_adr_dir
from madr_tools.parser import ADRDocument, load
from madr_tools.validators import validate_sections, validate_cross_file_integrity

import frontmatter as fm


def run(args: argparse.Namespace | None = None) -> int:
    adr_dir = get_adr_dir()
    if not adr_dir.exists():
        return 0

    errors: list[str] = []
    docs: list[ADRDocument] = []
    paths = sorted(p for p in adr_dir.glob("[0-9]*.md") if FILENAME_RE.match(p.name))

    for path in paths:
        rel = path.relative_to(adr_dir.parent.parent)
        try:
            doc = load(path)
        except ValidationError as e:
            for err in e.errors():
                errors.append(f"{rel}: {err['msg']}")
            continue
        except Exception as e:
            errors.append(f"{rel}: {e}")
            continue

        docs.append(doc)

        for msg in validate_sections(doc):
            errors.append(f"{rel}: {msg}")

    for msg in validate_cross_file_integrity(docs):
        errors.append(msg)

    if errors:
        for e in errors:
            print(e)
        return 1
    return 0
