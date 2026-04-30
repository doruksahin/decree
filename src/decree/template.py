"""Pure template rendering — no I/O."""


def render_template(
    template_content: str,
    number: int,
    title: str,
    slug: str,
    today: str,
    doc_type=None,
) -> str:
    """Fill template placeholders and append any required sections not in the template."""
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

    # Append required sections that the template doesn't already contain.
    if doc_type is not None:
        existing_sections = {line.lstrip("# ").strip() for line in content.splitlines() if line.startswith("## ")}
        descs = doc_type.section_descriptions
        for section in doc_type.required_sections:
            if section not in existing_sections:
                desc = descs.get(section, "TODO")
                content += f"\n## {section}\n\n{desc}\n"

    return content
