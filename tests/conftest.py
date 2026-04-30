"""Shared fixtures for decree tests."""

import pytest


@pytest.fixture
def project_dir(tmp_path):
    """A minimal project with decree.toml and empty ADR dir."""
    decree_toml = tmp_path / "decree.toml"
    decree_toml.write_text(
        "[types.adr]\n"
        'dir = "docs/adr"\n'
        'prefix = "ADR"\n'
        "digits = 4\n"
        'initial_status = "proposed"\n'
        'statuses = ["proposed", "accepted", "rejected", "deprecated", "superseded"]\n'
        'warn_on_reference = ["rejected", "deprecated", "superseded"]\n'
        "required_sections = ["
        '"Context and Problem Statement", "Considered Options", '
        '"Decision Outcome", "Consequences", "Affected Files", "Validation Needed"]\n'
        "\n"
        "[types.adr.transitions]\n"
        'proposed = ["accepted", "rejected"]\n'
        'accepted = ["deprecated", "superseded"]\n'
        "rejected = []\n"
        "deprecated = []\n"
        "superseded = []\n"
        "\n"
        "[types.adr.actions]\n"
        'accept = "accepted"\n'
        'reject = "rejected"\n'
        'deprecate = "deprecated"\n'
        'supersede = "superseded"\n'
        "\n"
        "[types.adr.status_field_requirements]\n"
        'superseded = ["superseded-by"]\n'
    )
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    return tmp_path


@pytest.fixture(autouse=True)
def reset_caches():
    """Clear lru_cache between tests."""
    from decree.config import get_project_root, load_doc_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()
    yield
    get_project_root.cache_clear()
    load_doc_types.cache_clear()
