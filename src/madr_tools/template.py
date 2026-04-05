"""Pure template rendering — no I/O."""

from .config import get_project_sections, get_section_descriptions


def render_template(
    template_content: str,
    number: int,
    title: str,
    slug: str,
    today: str,
    doc_type=None,
) -> str:
    """Fill template placeholders and append project sections."""
    digits = doc_type.digits if doc_type is not None else 4
    prefix = doc_type.prefix if doc_type is not None else "ADR"
    initial_status = doc_type.initial_status if doc_type is not None else "proposed"

    content = template_content
    content = content.replace("__NUMBER__", f"{number:0{digits}d}")
    content = content.replace("__TITLE__", title)
    content = content.replace("__SLUG__", slug)
    content = content.replace("__DATE__", today)
    content = content.replace("__PREFIX__", prefix)
    content = content.replace("__INITIAL_STATUS__", initial_status)

    # Append project sections (legacy [tool.adr] mechanism).
    # In the new [tool.doc.types.*] config, templates already contain all sections.
    project_sections = get_project_sections()
    if project_sections:
        descs = get_section_descriptions()
        for section in project_sections:
            desc = descs.get(section, "TODO")
            content += f"\n## {section}\n\n{desc}\n"

    return content
