"""Create a new ADR from the MADR v4 template."""
import argparse
from datetime import date
from slugify import slugify
from madr_tools.config import DATE_FORMAT, SLUG_MAX_LENGTH, get_adr_dir, get_template_path
from madr_tools.parser import next_adr_number
from madr_tools.template import render_template
from madr_tools.commands import index


def run(args: argparse.Namespace) -> int:
    title = args.title
    number = next_adr_number()
    slug = slugify(title, max_length=SLUG_MAX_LENGTH, word_boundary=True)
    today = date.today().strftime(DATE_FORMAT)

    raw = get_template_path().read_text()
    content = render_template(raw, number, title, slug, today)

    adr_dir = get_adr_dir()
    adr_dir.mkdir(parents=True, exist_ok=True)
    filepath = adr_dir / f"{number:04d}-{slug}.md"
    filepath.write_text(content)

    index.run(None)
    print(filepath)
    return 0
