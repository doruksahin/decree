"""Pure template rendering — no I/O."""

from .config import get_project_sections, get_section_descriptions


def render_template(
    template_content: str,
    number: int,
    title: str,
    slug: str,
    today: str,
) -> str:
    """Fill template placeholders and append project sections."""
    content = template_content
    content = content.replace("__NUMBER__", f"{number:04d}")
    content = content.replace("__TITLE__", title)
    content = content.replace("__SLUG__", slug)
    content = content.replace("__DATE__", today)

    project_sections = get_project_sections()
    if project_sections:
        descs = get_section_descriptions()
        for section in project_sections:
            desc = descs.get(section, "TODO")
            content += f"\n## {section}\n\n{desc}\n"

    return content
