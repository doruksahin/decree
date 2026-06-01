"""Package version helpers."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as metadata_version

DISTRIBUTION_NAME = "decree"


def get_version() -> str:
    """Return the installed decree package version from package metadata."""
    try:
        return metadata_version(DISTRIBUTION_NAME)
    except PackageNotFoundError as exc:
        raise RuntimeError(
            "decree package metadata is not installed; run `uv sync` or install the package before reading the "
            "decree version."
        ) from exc
