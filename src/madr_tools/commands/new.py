"""Create a new ADR from the MADR v4 template."""
import argparse
from datetime import date

from slugify import slugify

from madr_tools.config import DATE_FORMAT, SLUG_MAX_LENGTH, get_adr_dir, get_template_path, get_project_sections
from madr_tools.log import info, success
from madr_tools.parser import next_adr_number
from madr_tools.template import render_template
from madr_tools.commands import index


def run(args: argparse.Namespace) -> int:
    prefix = "new"
    title = args.title
    number = next_adr_number()
    slug = slugify(title, max_length=SLUG_MAX_LENGTH, word_boundary=True)
    today = date.today().strftime(DATE_FORMAT)

    info(prefix, f"next number: {number:04d}")
    info(prefix, f"slug: {slug}")

    template_path = get_template_path()
    info(prefix, f"template: {template_path}")

    raw = template_path.read_text()
    content = render_template(raw, number, title, slug, today)

    project_sections = get_project_sections()
    if project_sections:
        info(prefix, f"appending {len(project_sections)} project sections: {', '.join(project_sections)}")

    adr_dir = get_adr_dir()
    adr_dir.mkdir(parents=True, exist_ok=True)
    filepath = adr_dir / f"{number:04d}-{slug}.md"
    filepath.write_text(content)
    info(prefix, f"wrote {filepath}")

    index.run(None)

    print(filepath)  # stdout: machine-readable path
    success(f"created ADR-{number:04d}")
    return 0
