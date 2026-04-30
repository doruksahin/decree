"""End-to-end: the killer combination.

PRD-001 references ADR-0003.
SPEC-001 references PRD-001.
ADR-0003 gets superseded by ADR-0004.
Lint catches the stale reference chain.
"""

import argparse

from decree.commands import lint, new, status

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


def test_killer_combination(monkeypatch, tmp_path):
    # 1. Set up multi-type project
    (tmp_path / "decree.toml").write_text(MULTI_TYPE_CONFIG)
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "docs" / "prd").mkdir(parents=True)
    (tmp_path / "docs" / "spec").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    # 2. Create ADR-0001, ADR-0002, ADR-0003
    for title in ["Use Redis", "Use PostgreSQL", "Auth via JWT"]:
        new.run(argparse.Namespace(title=title, doc_type="adr"))

    # 3. Accept ADR-0003
    status.run(argparse.Namespace(action="accept", doc_id="ADR-0003", target_id=None))

    # 4. Create PRD-001 referencing ADR-0003
    new.run(argparse.Namespace(title="User Authentication", doc_type="prd"))
    prd_path = tmp_path / "docs" / "prd" / "001-user-authentication.md"
    _add_references(prd_path, ["ADR-0003"])

    # 5. Create SPEC-001 referencing PRD-001
    new.run(argparse.Namespace(title="Auth API Design", doc_type="spec"))
    spec_path = tmp_path / "docs" / "spec" / "001-auth-api-design.md"
    _add_references(spec_path, ["PRD-001"])

    # 6. Lint should pass — all references valid
    assert lint.run(None) == 0

    # 7. Create ADR-0004 and supersede ADR-0003
    new.run(argparse.Namespace(title="Auth via OAuth2", doc_type="adr"))
    status.run(argparse.Namespace(action="accept", doc_id="ADR-0004", target_id=None))
    status.run(argparse.Namespace(action="supersede", doc_id="ADR-0003", target_id="ADR-0004"))

    # 8. Lint should FAIL — PRD-001 references ADR-0003 (superseded)
    assert lint.run(None) == 1
