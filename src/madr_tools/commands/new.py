"""Create a new document from a template (ADR, PRD, SPEC, etc.)."""
import argparse
from datetime import date
from pathlib import Path

from slugify import slugify

from madr_tools.config import DATE_FORMAT, SLUG_MAX_LENGTH, get_project_sections, load_doc_types
from madr_tools.doctypes import ADR_DEFAULT
from madr_tools.log import info, error, success
from madr_tools.parser import next_number, next_adr_number
from madr_tools.template import render_template
from madr_tools.commands import index

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
    from madr_tools.config import get_project_root, get_template_path
    # Custom template from type config
    if doc_type.template:
        custom = get_project_root() / doc_type.template
        if custom.exists():
            return custom
    # Built-in template for known types
    if doc_type.name in _TYPE_TEMPLATES:
        return _TYPE_TEMPLATES[doc_type.name]
    # Fallback to ADR default template (for adr type or unknown)
    return get_template_path()


def run(args: argparse.Namespace) -> int:
    prefix = "new"
    title = args.title
    doc_type_name = getattr(args, "doc_type", None) or "adr"

    # Resolve DocType
    doc_type = _resolve_doc_type(doc_type_name)
    if doc_type is None:
        error(prefix, f"Unknown document type: '{doc_type_name}'")
        return 1

    number = next_number(doc_type)
    slug = slugify(title, max_length=SLUG_MAX_LENGTH, word_boundary=True)
    today = date.today().strftime(DATE_FORMAT)

    info(prefix, f"type: {doc_type.name}, next number: {doc_type.format_id(number)}")
    info(prefix, f"slug: {slug}")

    template_path = _get_template_path(doc_type)
    info(prefix, f"template: {template_path}")

    raw = template_path.read_text()
    content = render_template(raw, number, title, slug, today, doc_type=doc_type)

    from madr_tools.config import get_project_root
    type_dir = get_project_root() / doc_type.dir
    type_dir.mkdir(parents=True, exist_ok=True)

    digits = doc_type.digits
    filepath = type_dir / f"{number:0{digits}d}-{slug}.md"
    filepath.write_text(content)
    info(prefix, f"wrote {filepath}")

    index.run(None)

    print(filepath)  # stdout: machine-readable path
    success(f"created {doc_type.format_id(number)}")
    return 0
