"""Create a new document from a template (ADR, PRD, SPEC, etc.)."""

import argparse
from datetime import date
from pathlib import Path

from slugify import slugify

from decree.config import DATE_FORMAT, SLUG_MAX_LENGTH, load_doc_types
from decree.identity import filename_for_doc_id, generate_doc_id
from decree.log import error, info, success
from decree.template import render_template

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
DEFAULT_ADR_TEMPLATE = TEMPLATE_DIR / "madr-v4.md"

_TYPE_TEMPLATES = {
    "prd": TEMPLATE_DIR / "prd.md",
    "spec": TEMPLATE_DIR / "spec.md",
}


def _resolve_doc_type(name: str):
    """Look up a DocType by name from the project config."""
    types = {dt.name: dt for dt in load_doc_types()}
    if name in types:
        return types[name]
    return None


def _get_template_path(doc_type):
    """Return the template path for a given DocType."""
    from decree.config import get_project_root

    # Custom template from type config
    if doc_type.template:
        custom = get_project_root() / doc_type.template
        if custom.exists():
            return custom
    # Built-in template for known types
    if doc_type.name in _TYPE_TEMPLATES:
        return _TYPE_TEMPLATES[doc_type.name]
    # Fallback to ADR default template (for adr type or unknown)
    return DEFAULT_ADR_TEMPLATE


def run(args: argparse.Namespace) -> int:
    prefix = "new"
    title = args.title
    doc_type_name = args.doc_type

    # Resolve DocType
    doc_type = _resolve_doc_type(doc_type_name)
    if doc_type is None:
        error(prefix, f"Unknown document type: '{doc_type_name}'")
        return 1

    doc_id = generate_doc_id(doc_type.prefix)
    slug = slugify(title, max_length=SLUG_MAX_LENGTH, word_boundary=True)
    today = date.today().strftime(DATE_FORMAT)

    info(prefix, f"type: {doc_type.name}, id: {doc_id}")
    info(prefix, f"slug: {slug}")

    template_path = _get_template_path(doc_type)
    info(prefix, f"template: {template_path}")

    raw = template_path.read_text()
    content = render_template(raw, doc_id, title, slug, today, doc_type=doc_type)

    from decree.config import get_project_root

    type_dir = get_project_root() / doc_type.dir
    type_dir.mkdir(parents=True, exist_ok=True)

    filepath = type_dir / filename_for_doc_id(doc_id, slug)
    try:
        with filepath.open("x") as f:
            f.write(content)
    except FileExistsError:
        error(prefix, f"refusing to overwrite existing document: {filepath}")
        return 1
    info(prefix, f"wrote {filepath}")

    print(filepath)  # stdout: machine-readable path
    success(f"created {doc_id}")
    return 0
