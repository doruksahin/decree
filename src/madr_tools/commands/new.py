"""Create a new ADR from the MADR v4 template."""
import argparse
from datetime import date
from slugify import slugify
from madr_tools.config import (
    DATE_FORMAT, SLUG_MAX_LENGTH,
    get_adr_dir, get_template_path, get_project_sections,
    get_section_descriptions,
)
from madr_tools.parser import next_adr_number
from madr_tools.commands import index

def run(args: argparse.Namespace) -> int:
    title = args.title
    number = next_adr_number()
    slug = slugify(title, max_length=SLUG_MAX_LENGTH, word_boundary=True)
    today = date.today().strftime(DATE_FORMAT)

    content = get_template_path().read_text()
    content = content.replace("__NUMBER__", f"{number:04d}")
    content = content.replace("__TITLE__", title)
    content = content.replace("__SLUG__", slug)
    content = content.replace("__DATE__", today)

    # Append project-specific sections
    project_sections = get_project_sections()
    if project_sections:
        descs = get_section_descriptions()
        for section in project_sections:
            desc = descs.get(section, "TODO")
            content += f"\n## {section}\n\n{desc}\n"

    adr_dir = get_adr_dir()
    adr_dir.mkdir(parents=True, exist_ok=True)
    filepath = adr_dir / f"ADR-{number:04d}-{slug}.md"
    filepath.write_text(content)

    index.run(None)
    print(filepath)
    return 0
