"""Structured logging for ADR commands."""

import sys


def info(prefix: str, msg: str) -> None:
    """Print a prefixed info line to stderr."""
    print(f"[{prefix}] {msg}", file=sys.stderr)


def error(prefix: str, msg: str) -> None:
    """Print a prefixed error line to stderr."""
    print(f"[{prefix}] ERROR: {msg}", file=sys.stderr)


def warn(prefix: str, msg: str) -> None:
    """Print a prefixed warning line to stderr."""
    print(f"[{prefix}] WARNING: {msg}", file=sys.stderr)


def success(msg: str) -> None:
    """Print a success summary line to stderr."""
    print(f"\u2713 {msg}", file=sys.stderr)


def fail(msg: str) -> None:
    """Print a failure summary line to stderr."""
    print(f"\u2717 {msg}", file=sys.stderr)
