"""Shared fixtures for madr-tools tests."""

import pytest
from pathlib import Path


@pytest.fixture
def project_dir(tmp_path):
    """A minimal project with pyproject.toml and empty ADR dir."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "test-project"\n\n'
        '[tool.adr]\n'
        'adr_dir = "docs/adr"\n'
        'project_sections = ["Consequences", "Affected Files", "Validation Needed"]\n'
    )
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    return tmp_path


@pytest.fixture(autouse=True)
def reset_caches():
    """Clear lru_cache between tests."""
    from madr_tools.config import get_project_root, _load_project_config
    get_project_root.cache_clear()
    _load_project_config.cache_clear()
    yield
    get_project_root.cache_clear()
    _load_project_config.cache_clear()
