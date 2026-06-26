"""Tests for decree.commands.list_docs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from decree.commands import list_docs

ADR_1 = "ADR-00000000000000000000000001"
ADR_2 = "ADR-00000000000000000000000002"


def _write_doc(root: Path, doc_id: str, bucket: str, status: str = "proposed") -> Path:
    type_dir = root / "docs" / "adr"
    path = type_dir / bucket / f"{doc_id.lower()}-test.md" if bucket else type_dir / f"{doc_id.lower()}-test.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nid: {doc_id}\nstatus: {status}\ndate: 2026-04-02\n---\n"
        f"\n# {doc_id} Test\n\n## Acceptance Criteria\n\n- [x] Done\n- [ ] Todo\n"
    )
    return path


def _args(**overrides):
    data = {
        "doc_type": None,
        "tree": False,
        "bucket": None,
        "status": None,
        "with_progress": False,
        "json": False,
    }
    data.update(overrides)
    return argparse.Namespace(**data)


def test_list_tree_groups_by_bucket(project_dir, monkeypatch, capsys) -> None:
    monkeypatch.chdir(project_dir)
    _write_doc(project_dir, ADR_1, "")
    _write_doc(project_dir, ADR_2, "platform/auth")

    assert list_docs.run(_args(tree=True, with_progress=True)) == 0

    out = capsys.readouterr().out
    assert "./" in out
    assert "platform/auth/" in out
    assert "ADR:" in out
    assert "1/2 primary" in out


def test_list_bucket_json_contract(project_dir, monkeypatch, capsys) -> None:
    monkeypatch.chdir(project_dir)
    _write_doc(project_dir, ADR_1, "")
    nested = _write_doc(project_dir, ADR_2, "platform/auth", status="accepted")

    assert list_docs.run(_args(bucket="platform/auth", json=True)) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "decree.list.v1"
    assert payload["filters"]["bucket"] == "platform/auth"
    assert [doc["id"] for doc in payload["documents"]] == [ADR_2]
    doc = payload["documents"][0]
    assert doc["bucket"] == "platform/auth"
    assert doc["type"] == "adr"
    assert doc["status"] == "accepted"
    assert doc["path"] == nested.relative_to(project_dir).as_posix()
    assert doc["references"] == []
    assert doc["progress"]["primary"] == {"done": 1, "total": 2, "percent": 50}
