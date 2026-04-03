"""Validate all ADRs: frontmatter, sections, cross-file integrity."""
import argparse
from pydantic import ValidationError
from madr_tools.config import FILENAME_RE, get_adr_dir, get_required_sections
from madr_tools.parser import ADRFrontmatter, ADRDocument
import frontmatter as fm

def run(args: argparse.Namespace | None = None) -> int:
    adr_dir = get_adr_dir()
    if not adr_dir.exists():
        return 0

    errors: list[str] = []
    docs: list[ADRDocument] = []
    required = get_required_sections()
    paths = sorted(p for p in adr_dir.glob("[0-9]*.md") if FILENAME_RE.match(p.name))

    for path in paths:
        rel = path.relative_to(adr_dir.parent.parent)
        try:
            post = fm.load(str(path))
            meta = ADRFrontmatter(**post.metadata)
        except ValidationError as e:
            for err in e.errors():
                errors.append(f"{rel}: {err['msg']}")
            continue
        except Exception as e:
            errors.append(f"{rel}: {e}")
            continue

        doc = ADRDocument(path=path, meta=meta, body=post.content)
        docs.append(doc)
        present = set(doc.sections)
        for section in required:
            if section not in present:
                errors.append(f"{rel}: missing section \"{section}\"")

    docs_by_id = {d.adr_id: d for d in docs}
    for doc in docs:
        rel = doc.path.relative_to(adr_dir.parent.parent)
        if doc.meta.superseded_by:
            tid = doc.meta.superseded_by
            if tid not in docs_by_id:
                errors.append(f"{rel}: superseded-by {tid} does not exist")
            elif docs_by_id[tid].meta.supersedes != doc.adr_id:
                errors.append(f"CROSS-FILE: {doc.adr_id} has superseded-by {tid}, but {tid} has no supersedes {doc.adr_id}")
        if doc.meta.supersedes:
            tid = doc.meta.supersedes
            if tid not in docs_by_id:
                errors.append(f"{rel}: supersedes {tid} does not exist")
            elif docs_by_id[tid].meta.status != "superseded":
                errors.append(f"CROSS-FILE: {doc.adr_id} supersedes {tid}, but {tid} has status '{docs_by_id[tid].meta.status}'")

    if errors:
        for e in errors:
            print(e)
        return 1
    return 0
