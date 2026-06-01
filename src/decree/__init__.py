"""decree — software decision lifecycle toolkit (MADR v4.0.0 ADR management for CLI and LLMs)."""

from decree.version import get_version

__all__ = ["__version__", "get_version"]


def __getattr__(name: str) -> str:
    if name == "__version__":
        return get_version()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
