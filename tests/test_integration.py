"""End-to-end: the killer combination.

PRD-00000000000000000000000001 references ADR-00000000000000000000000003.
SPEC-00000000000000000000000001 references PRD-00000000000000000000000001.
ADR-00000000000000000000000003 gets superseded by ADR-00000000000000000000000004.
Lint catches the stale reference chain.
"""

import argparse

from decree.commands import lint, new, status
from decree.config import load_doc_types
from decree.parser import load

MULTI_TYPE_CONFIG = """\
[types.adr]
dir = "docs/adr"
prefix = "ADR"
digits = 4
initial_status = "proposed"
statuses = ["proposed", "accepted", "rejected", "deprecated", "superseded"]
required_sections = ["Context and Problem Statement", "Considered Options", "Decision Outcome"]
warn_on_reference = ["rejected", "deprecated", "superseded"]

[types.adr.transitions]
proposed = ["accepted", "rejected"]
accepted = ["deprecated", "superseded"]
rejected = []
deprecated = []
superseded = []

[types.adr.actions]
accept = "accepted"
reject = "rejected"
deprecate = "deprecated"
supersede = "superseded"

[types.adr.status_field_requirements]
superseded = ["superseded-by"]

[types.prd]
dir = "docs/prd"
prefix = "PRD"
digits = 3
initial_status = "draft"
statuses = ["draft", "review", "approved", "implemented"]
required_sections = ["Problem Statement", "Requirements", "Success Criteria"]

[types.prd.transitions]
draft = ["review"]
review = ["approved", "draft"]
approved = ["implemented"]
implemented = []

[types.prd.actions]
submit = "review"
approve = "approved"
implement = "implemented"

[types.spec]
dir = "docs/spec"
prefix = "SPEC"
digits = 3
initial_status = "draft"
statuses = ["draft", "approved", "implemented"]
required_sections = ["Overview", "Technical Design", "Testing Strategy"]

[types.spec.transitions]
draft = ["approved"]
approved = ["implemented"]
implemented = []

[types.spec.actions]
approve = "approved"
implement = "implemented"
"""


def _add_references(path, refs):
    """Inject references into a document's frontmatter."""
    import frontmatter

    post = frontmatter.load(str(path))
    post["references"] = refs
    path.write_text(frontmatter.dumps(post).rstrip() + "\n")


def _new_doc(tmp_path, doc_type, title):
    type_dir = tmp_path / "docs" / doc_type
    before = set(type_dir.glob("*.md"))
    assert new.run(argparse.Namespace(title=title, doc_type=doc_type)) == 0
    created = sorted(set(type_dir.glob("*.md")) - before)
    assert len(created) == 1
    dt = next(t for t in load_doc_types() if t.name == doc_type)
    doc = load(created[0], doc_type=dt)
    return created[0], doc.doc_id


def test_killer_combination(monkeypatch, tmp_path):
    # 1. Set up multi-type project
    (tmp_path / "decree.toml").write_text(MULTI_TYPE_CONFIG)
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "docs" / "prd").mkdir(parents=True)
    (tmp_path / "docs" / "spec").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    # 2. Create three ADRs
    adr_ids = []
    for title in ["Use Redis", "Use PostgreSQL", "Auth via JWT"]:
        _, doc_id = _new_doc(tmp_path, "adr", title)
        adr_ids.append(doc_id)
    auth_jwt_id = adr_ids[2]

    # 3. Accept the JWT ADR
    assert status.run(argparse.Namespace(action="accept", doc_id=auth_jwt_id, target_id=None)) == 0

    # 4. Create PRD referencing the JWT ADR
    prd_path, prd_id = _new_doc(tmp_path, "prd", "User Authentication")
    _add_references(prd_path, [auth_jwt_id])

    # 5. Create SPEC referencing the PRD
    spec_path, _ = _new_doc(tmp_path, "spec", "Auth API Design")
    _add_references(spec_path, [prd_id])

    # 6. Lint should pass — all references valid
    assert lint.run(None) == 0

    # 7. Create OAuth2 ADR and supersede the JWT ADR
    _, oauth_id = _new_doc(tmp_path, "adr", "Auth via OAuth2")
    assert status.run(argparse.Namespace(action="accept", doc_id=oauth_id, target_id=None)) == 0
    assert status.run(argparse.Namespace(action="supersede", doc_id=auth_jwt_id, target_id=oauth_id)) == 0

    # 8. Lint should FAIL — PRD references the superseded ADR
    assert lint.run(None) == 1
