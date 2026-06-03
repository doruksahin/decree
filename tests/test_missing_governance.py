"""SPEC-01KT6NCQC7DMJ3NG1MPWBGBVFQ — missing-governance (observed minus declared).

The headline is a **value-validation fixture** (`TestValueOnRealisticCorpus`): a
realistic multi-decision, multi-commit corpus — the shape decree's own
bulk-import history *lacks*, which is why the signal is mute there. Among a
deliberate tangle of declared / owned-elsewhere / structural / shared / single-
touch paths, the signal must surface **exactly one** candidate: the file a
decision genuinely repeat-developed (≥2 distinct commits) but never declared.

`TestRules` pins each gate individually; `TestDeterminism` guards the M5 review
finding (no working-tree dependence); `TestNeverFeedsWhy` guards the invariant.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from decree.commands.health import (
    _report_to_dict,
    health,
    health_run,
    missing_governance,
)
from decree.commands.queries import why
from decree.index_db import IndexDB, default_db_path

S1 = "SPEC-00000000000000000000000001"  # governs src/auth/    (directory)
S2 = "SPEC-00000000000000000000000002"  # governs src/cache.py (file)
S3 = "SPEC-00000000000000000000000003"  # governs src/api.py   (file)

_DECREE_TOML = """\
[types.spec]
dir = "decree/spec"
prefix = "SPEC"
digits = 3
initial_status = "draft"
statuses = ["draft", "approved", "implemented"]
required_sections = ["Overview"]
[types.spec.transitions]
draft = ["approved"]
approved = ["implemented"]
implemented = []
[types.spec.actions]
approve = "approved"
implement = "implemented"
"""


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "T"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "commit.gpgsign", "false"], check=True)


def _write_spec(repo: Path, sid: str, ulid: str, slug: str, governs: list[str]) -> None:
    path = repo / "decree" / "spec" / f"spec-{ulid}-{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    governs_yaml = "\n".join(f"  - {p}" for p in governs)
    path.write_text(
        f"---\nid: {sid}\nstatus: implemented\ndate: 2026-05-10\n"
        f"governs:\n{governs_yaml}\n---\n\n# {sid}\n\n## Overview\n\nProse.\n"
    )


def _commit(repo: Path, message: str, files: dict[str, str]) -> None:
    for rel, content in files.items():
        full = repo / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", message], check=True, capture_output=True)


def _impl(sid: str, body: str) -> str:
    return f"{body}\n\nImplements: {sid}"


def _build_corpus(repo: Path) -> None:
    """A realistic incremental corpus. Expected single surfaced candidate:
    S1 -> src/util/crypto.py (repeat-touched in 2 commits, undeclared, unowned).

    Every other touch is a deliberate negative:
      - src/auth/login.py    declared by S1 (directory governs)        -> excluded
      - src/cache.py         declared by S2                            -> excluded
      - src/api.py           declared by S3 (and S2 touches it)        -> excluded / owned-elsewhere
      - tests/test_cache.py  repeat-touched by S2 but structural       -> excluded
      - src/util/config.py   repeat-touched by S1+S2+S3 (DF=3)         -> shared-infra floor
      - src/util/crypto.py   single-touched by S3 (commit_count=1)     -> repeat-touch gate (for S3)
    """
    _git_init(repo)
    (repo / "decree.toml").write_text(_DECREE_TOML)
    _write_spec(repo, S1, "00000000000000000000000001", "auth", ["src/auth/"])
    _write_spec(repo, S2, "00000000000000000000000002", "cache", ["src/cache.py"])
    _write_spec(repo, S3, "00000000000000000000000003", "api", ["src/api.py"])
    # Root commit — no trailer, so none of these touches are attributed.
    _commit(
        repo,
        "chore: bootstrap",
        {
            "src/auth/login.py": "login v0\n",
            "src/util/crypto.py": "crypto v0\n",
            "src/util/config.py": "config v0\n",
            "src/cache.py": "cache v0\n",
            "src/api.py": "api v0\n",
            "tests/test_cache.py": "test v0\n",
        },
    )
    # S1: repeat-touch crypto.py (CANDIDATE) + login.py (declared) + config.py (shared).
    _commit(repo, _impl(S1, "feat: auth a"), {"src/auth/login.py": "login v1\n", "src/util/crypto.py": "crypto v1\n"})
    _commit(repo, _impl(S1, "feat: auth b"), {"src/auth/login.py": "login v2\n", "src/util/crypto.py": "crypto v2\n"})
    _commit(repo, _impl(S1, "feat: auth c"), {"src/util/config.py": "config s1a\n"})
    _commit(repo, _impl(S1, "feat: auth d"), {"src/util/config.py": "config s1b\n"})
    # S2: cache.py (declared) + test_cache.py (structural) + api.py (owned by S3) + config.py (shared).
    _commit(repo, _impl(S2, "feat: cache a"), {"src/cache.py": "cache v1\n", "tests/test_cache.py": "test v1\n"})
    _commit(repo, _impl(S2, "feat: cache b"), {"src/cache.py": "cache v2\n", "tests/test_cache.py": "test v2\n"})
    _commit(repo, _impl(S2, "feat: cache c"), {"src/api.py": "api s2a\n"})
    _commit(repo, _impl(S2, "feat: cache d"), {"src/api.py": "api s2b\n"})
    _commit(repo, _impl(S2, "feat: cache e"), {"src/util/config.py": "config s2a\n"})
    _commit(repo, _impl(S2, "feat: cache f"), {"src/util/config.py": "config s2b\n"})
    # S3: api.py (declared) + crypto.py (single touch only) + config.py (shared).
    _commit(repo, _impl(S3, "feat: api a"), {"src/api.py": "api v1\n"})
    _commit(repo, _impl(S3, "feat: api b"), {"src/api.py": "api v2\n", "src/util/crypto.py": "crypto s3\n"})
    _commit(repo, _impl(S3, "feat: api c"), {"src/util/config.py": "config s3a\n"})
    _commit(repo, _impl(S3, "feat: api d"), {"src/util/config.py": "config s3b\n"})


def _rebuild(repo: Path, monkeypatch) -> IndexDB:
    monkeypatch.chdir(repo)
    from decree.config import get_project_root, load_doc_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()
    db = IndexDB(default_db_path(repo))
    db.rebuild(repo)
    return db


def _by_decision(db: IndexDB) -> dict:
    return {f.decision_id: f for f in missing_governance(db)}


class TestValueOnRealisticCorpus:
    def test_surfaces_exactly_the_one_genuine_gap(self, tmp_path: Path, monkeypatch) -> None:
        _build_corpus(tmp_path)
        by_decision = _by_decision(_rebuild(tmp_path, monkeypatch))

        # Exactly one decision has a suggestion, and exactly one candidate.
        assert set(by_decision) == {S1}
        s1 = by_decision[S1]
        assert [c.path for c in s1.candidates] == ["src/util/crypto.py"]

        crypto = s1.candidates[0]
        assert crypto.commit_count == 2  # repeat-touched across 2 distinct commits
        assert crypto.distinct_decisions == 1  # only S1 repeat-touches it (S3's single touch doesn't count)

        # Honesty fields let a reader judge the suggestion's basis.
        assert s1.linked_commit_count == 4  # S1's distinct trailer-linked commits
        assert s1.observed_path_count == 3  # login.py, crypto.py, config.py

    def test_advisory_exit_zero_and_json_shape(self, tmp_path: Path, monkeypatch, capsys) -> None:
        _build_corpus(tmp_path)
        db = _rebuild(tmp_path, monkeypatch)
        report = health(db, tmp_path, 10, 30)

        # The suggestion is present but must NOT be treated as an exit-affecting finding.
        assert report.missing_governance
        assert not (report.stale_decisions or report.ungoverned_hotspots or report.dead_governance)

        args = argparse.Namespace(json=True, project=str(tmp_path), threshold_commits=10, threshold_days=30)
        assert health_run(args) == 0  # advisory: missing-governance alone exits clean

        payload = _report_to_dict(report)["missing_governance"]
        assert payload == [
            {
                "decision_id": S1,
                "linked_commit_count": 4,
                "observed_path_count": 3,
                "candidates": [
                    {"path": "src/util/crypto.py", "commit_count": 2, "distinct_decisions": 1},
                ],
            }
        ]


class TestRules:
    def test_declared_paths_excluded(self, tmp_path: Path, monkeypatch) -> None:
        # src/auth/ is declared (directory); login.py under it is repeat-touched but never surfaced.
        by_decision = _build_and_rebuild(tmp_path, monkeypatch)
        assert all("src/auth/login.py" not in [c.path for c in f.candidates] for f in by_decision.values())

    def test_owned_elsewhere_excluded(self, tmp_path: Path, monkeypatch) -> None:
        # S2 repeat-touches src/api.py, which S3 declares -> not a missing-governance gap for S2.
        by_decision = _build_and_rebuild(tmp_path, monkeypatch)
        assert S2 not in by_decision

    def test_structural_noise_excluded(self, tmp_path: Path, monkeypatch) -> None:
        # tests/test_cache.py is repeat-touched by S2 but is a structural path.
        by_decision = _build_and_rebuild(tmp_path, monkeypatch)
        assert all("tests/test_cache.py" not in [c.path for c in f.candidates] for f in by_decision.values())

    def test_shared_infra_floor_excludes_config(self, tmp_path: Path, monkeypatch) -> None:
        # src/util/config.py is repeat-touched by S1, S2, S3 (DF=3) -> dropped for everyone.
        by_decision = _build_and_rebuild(tmp_path, monkeypatch)
        assert all("src/util/config.py" not in [c.path for c in f.candidates] for f in by_decision.values())

    def test_single_touch_not_a_candidate(self, tmp_path: Path, monkeypatch) -> None:
        # S3 touches crypto.py once (commit_count=1) -> repeat-touch gate excludes it for S3.
        by_decision = _build_and_rebuild(tmp_path, monkeypatch)
        assert S3 not in by_decision


class TestDeterminism:
    def test_no_working_tree_dependence(self, tmp_path: Path, monkeypatch) -> None:
        # M5: the candidate set is a pure index read. Mutating the working tree
        # (delete the observed candidate file) must not change the result without
        # a rebuild — proving no read-time content sniffing.
        _build_corpus(tmp_path)
        db = _rebuild(tmp_path, monkeypatch)
        before = _by_decision(db)
        assert before[S1].candidates[0].path == "src/util/crypto.py"

        (tmp_path / "src" / "util" / "crypto.py").unlink()  # remove from working tree, no rebuild
        after = _by_decision(db)
        assert {k: [c.path for c in v.candidates] for k, v in before.items()} == {
            k: [c.path for c in v.candidates] for k, v in after.items()
        }


class TestNeverFeedsWhy:
    def test_suggested_path_is_not_a_governance_fact(self, tmp_path: Path, monkeypatch) -> None:
        # crypto.py is a missing-governance *suggestion*, not declared governance.
        # why() must report no governing decision for it (the suggestion never leaks).
        _build_corpus(tmp_path)
        db = _rebuild(tmp_path, monkeypatch)
        assert why(db, "src/util/crypto.py") == []  # the suggestion is not a governance fact
        assert why(db, "src/api.py")  # a genuinely declared path still resolves (non-empty)


def _build_and_rebuild(tmp_path: Path, monkeypatch) -> dict:
    _build_corpus(tmp_path)
    return _by_decision(_rebuild(tmp_path, monkeypatch))
