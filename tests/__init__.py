"""Test package marker.

Some integration tests reuse fixture builders from sibling test modules.
Keeping tests importable as a package makes `uv run pytest` work without
requiring callers to set PYTHONPATH manually.
"""
