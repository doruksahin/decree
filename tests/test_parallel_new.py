"""Regression coverage for parallel document creation."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from decree.commands import index_db_cli, lint
from decree.config import get_project_root, load_doc_types
from decree.parser import load

SPEC_ONLY_CONFIG = """\
[types.spec]
dir = "decree/spec"
prefix = "SPEC"
initial_status = "draft"
statuses = ["draft", "review", "approved", "implemented"]
required_sections = ["Overview", "Technical Design", "Testing Strategy"]

[types.spec.transitions]
draft = ["review"]
review = ["approved", "draft"]
approved = ["implemented"]
implemented = []

[types.spec.actions]
submit = "review"
approve = "approved"
implement = "implemented"
"""


def test_parallel_new_creates_unique_canonical_documents(tmp_path: Path, monkeypatch):
    (tmp_path / "decree.toml").write_text(SPEC_ONLY_CONFIG)
    command = [
        sys.executable,
        "-c",
        "from decree.cli import main; raise SystemExit(main())",
        "new",
        "spec",
    ]
    env = _subprocess_env()

    procs = [
        subprocess.Popen(
            [*command, f"Parallel Smoke {i}"],
            cwd=tmp_path,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for i in range(12)
    ]
    results = [(*proc.communicate(timeout=10), proc.returncode) for proc in procs]

    failures = [
        f"returncode={returncode}\nstdout={stdout}\nstderr={stderr}"
        for stdout, stderr, returncode in results
        if returncode != 0
    ]
    assert not failures

    monkeypatch.chdir(tmp_path)
    get_project_root.cache_clear()
    load_doc_types.cache_clear()
    doc_type = load_doc_types()[0]
    files = sorted((tmp_path / "decree" / "spec").glob("*.md"))
    docs = [load(path, doc_type=doc_type) for path in files]
    ids = [doc.doc_id for doc in docs]

    assert len(files) == 12
    assert len(set(ids)) == 12
    assert all(path.name.startswith(doc.doc_id.lower()) for path, doc in zip(files, docs, strict=True))
    assert lint.run(None) == 0
    assert index_db_cli.rebuild_run(argparse.Namespace(project=str(tmp_path))) == 0
    assert index_db_cli.verify_run(argparse.Namespace(project=str(tmp_path), json=False)) == 0


def _subprocess_env() -> dict[str, str]:
    repo_root = Path(__file__).resolve().parents[1]
    src_path = str(repo_root / "src")
    env = os.environ.copy()
    env["PYTHONPATH"] = src_path + os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else src_path
    return env
