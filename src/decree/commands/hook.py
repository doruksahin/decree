"""`decree hook install/uninstall` — Claude Code stop hook management.

Modifies .claude/settings.json to register a Stop hook that runs `decree ddd`
at session end. The hook writes a markdown snapshot the next session can read.

Per-project only in v1 (modifies project's .claude/settings.json, not the
user's global ~/.claude/settings.json).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from decree.log import error, info, success

# The shipped hook script, relative to the decree package.
HOOK_SCRIPT_RELATIVE = "scripts/hooks/decree-ddd-stop.sh"

# Marker in settings.json to identify the entry we wrote (so uninstall can
# remove only it, not user-authored entries).
HOOK_MARKER = "decree-ddd-stop"


def _settings_path(project_root: Path) -> Path:
    return project_root / ".claude" / "settings.json"


def _hook_script_path() -> Path:
    """Locate the shipped hook script next to the decree package."""
    # When installed via pip/uv, the package lives at site-packages/decree/.
    # The script ships at <repo>/scripts/hooks/... — we resolve it via the
    # package's __file__ pointer.
    import decree

    pkg_root = Path(decree.__file__).parent.parent.parent  # src/decree/__init__.py → repo root
    script = pkg_root / HOOK_SCRIPT_RELATIVE
    if script.exists():
        return script
    # Fallback for editable installs / src layout: look in the parent dir
    alt = Path(decree.__file__).resolve().parent.parent / HOOK_SCRIPT_RELATIVE
    return alt


def _load_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Existing {path} is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"Existing {path} must be a JSON object at the top level.")
    return data


def _save_settings(path: Path, data: dict) -> None:
    """Atomic write: write to .tmp then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    tmp.replace(path)


def _hook_entry(script_path: Path) -> dict:
    """Build the Claude Code Stop hook entry pointing at our script."""
    return {
        "matcher": "",
        "hooks": [
            {
                "type": "command",
                "command": str(script_path),
                # marker so uninstall can find this entry
                "_decree_marker": HOOK_MARKER,
            }
        ],
    }


def _find_decree_entries(settings: dict) -> list[tuple[str, int]]:
    """Find (event_name, index) pairs for entries we previously installed."""
    hooks_root = settings.get("hooks", {})
    if not isinstance(hooks_root, dict):
        return []
    found: list[tuple[str, int]] = []
    for event_name, entries in hooks_root.items():
        if not isinstance(entries, list):
            continue
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            sub_hooks = entry.get("hooks", [])
            if not isinstance(sub_hooks, list):
                continue
            for sh in sub_hooks:
                if isinstance(sh, dict) and sh.get("_decree_marker") == HOOK_MARKER:
                    found.append((event_name, i))
                    break
    return found


def install_claude_hook(project_root: Path) -> None:
    """Add the stop hook to .claude/settings.json. Idempotent."""
    settings_path = _settings_path(project_root)
    settings = _load_settings(settings_path)

    # Validate the existing structure before we touch anything.
    hooks_root = settings.get("hooks", {})
    if not isinstance(hooks_root, dict):
        raise ValueError(f"{settings_path}: 'hooks' must be an object, got {type(hooks_root).__name__}")

    # Idempotency: if we already have a Stop entry with our marker, do nothing.
    existing = _find_decree_entries(settings)
    if existing:
        return

    script_path = _hook_script_path()
    entry = _hook_entry(script_path)

    stop_entries = hooks_root.get("Stop", [])
    if not isinstance(stop_entries, list):
        raise ValueError(f"{settings_path}: 'hooks.Stop' must be a list, got {type(stop_entries).__name__}")

    stop_entries.append(entry)
    hooks_root["Stop"] = stop_entries
    settings["hooks"] = hooks_root
    _save_settings(settings_path, settings)


def uninstall_claude_hook(project_root: Path) -> int:
    """Remove all decree-installed hook entries. Returns the count removed."""
    settings_path = _settings_path(project_root)
    if not settings_path.exists():
        return 0
    settings = _load_settings(settings_path)

    entries = _find_decree_entries(settings)
    if not entries:
        return 0

    # Remove entries in reverse order so indices remain valid
    hooks_root = settings.get("hooks", {})
    by_event: dict[str, list[int]] = {}
    for event_name, idx in entries:
        by_event.setdefault(event_name, []).append(idx)
    for event_name, indices in by_event.items():
        for idx in sorted(indices, reverse=True):
            del hooks_root[event_name][idx]
        # Drop the event key entirely if no entries remain
        if not hooks_root[event_name]:
            del hooks_root[event_name]

    if hooks_root:
        settings["hooks"] = hooks_root
    elif "hooks" in settings:
        del settings["hooks"]

    _save_settings(settings_path, settings)
    return len(entries)


def hook_status(project_root: Path) -> tuple[bool, Path]:
    """Return (installed?, settings_path)."""
    settings_path = _settings_path(project_root)
    if not settings_path.exists():
        return False, settings_path
    settings = _load_settings(settings_path)
    return bool(_find_decree_entries(settings)), settings_path


def run(args: argparse.Namespace) -> int:
    from decree.config import get_project_root

    try:
        root = get_project_root()
    except FileNotFoundError:
        error("hook", "decree.toml not found. Run `decree` from a decree-enabled project.")
        return 1

    if args.action == "install":
        try:
            install_claude_hook(root)
        except ValueError as e:
            error("hook", str(e))
            return 1
        success(f"Claude Code stop hook installed at {_settings_path(root)}")
        return 0
    elif args.action == "uninstall":
        try:
            removed = uninstall_claude_hook(root)
        except ValueError as e:
            error("hook", str(e))
            return 1
        if removed:
            success(f"removed {removed} decree hook entries from {_settings_path(root)}")
        else:
            info("hook", "no decree hook entries found to remove")
        return 0
    elif args.action == "status":
        installed, path = hook_status(root)
        if installed:
            print(f"installed at {path}")
            return 0
        else:
            print(f"not installed (settings would be at {path})")
            return 1
    return 1
