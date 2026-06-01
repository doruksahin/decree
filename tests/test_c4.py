"""Tests for C4 architecture validation and diagram generation."""

import frontmatter

from decree.c4 import C4Config, generate_c4_container, validate_c4
from decree.doctypes import DocType
from decree.parser import DocDocument, DocFrontmatter


def _doc_id(number: int) -> str:
    return f"SPEC-{number:026d}"


def _spec_type(c4_enabled=True):
    return DocType(
        name="spec",
        prefix="SPEC",
        legacy_digits=3,
        dir="decree/spec",
        initial_status="draft",
        statuses=("draft", "approved", "implemented", "superseded"),
        transitions={
            "draft": ("approved",),
            "approved": ("implemented",),
            "implemented": (),
            "superseded": (),
        },
        actions={"approve": "approved"},
        warn_on_reference=("superseded",),
        c4=C4Config(
            enabled=c4_enabled,
            id_field="c4_id",
            levels=("system", "container", "component"),
        )
        if c4_enabled
        else None,
    )


def _make_spec(
    tmp_path,
    number,
    title,
    status="approved",
    c4_id=None,
    c4_type="container",
    c4_name=None,
    parent="",
    depends_on=None,
    doc_type=None,
):
    """Create a spec file with C4 metadata and return a DocDocument."""
    dt = doc_type or _spec_type()
    doc_id = _doc_id(number)
    slug = title.lower().replace(" ", "-")
    path = tmp_path / f"{doc_id.lower()}-{slug}.md"

    fm = {"id": doc_id, "status": status, "date": "2026-04-05"}
    if c4_id is not None:
        fm["c4_id"] = c4_id
    if c4_type is not None:
        fm["c4_type"] = c4_type
    if c4_name is not None:
        fm["c4_name"] = c4_name
    elif c4_id is not None:
        fm["c4_name"] = title
    if parent:
        fm["parent"] = parent
    if depends_on:
        fm["depends-on"] = depends_on

    body = (
        f"# {doc_id} {title}\n\n## Overview\n\nOverview.\n\n"
        "## Technical Design\n\nDesign.\n\n## Testing Strategy\n\nTests.\n"
    )
    post = frontmatter.Post(body, **fm)
    path.write_text(frontmatter.dumps(post).rstrip() + "\n")

    meta = DocFrontmatter.model_validate(
        {"id": doc_id, "status": status, "date": "2026-04-05"},
        context={"doc_type": dt},
    )
    return DocDocument(path=path, meta=meta, body=body, doc_type=dt, raw_metadata=fm)


# ── validate_c4 tests ───────────────────────────────────────


class TestValidateC4:
    def test_valid_docs_no_errors(self, tmp_path):
        c4 = C4Config(enabled=True, id_field="c4_id", levels=("system", "container"))
        docs = [
            _make_spec(tmp_path, 1, "System", c4_id="poc", c4_type="system"),
            _make_spec(
                tmp_path,
                2,
                "Data Prep",
                c4_id="data_prep",
                c4_type="container",
                parent="poc",
            ),
            _make_spec(
                tmp_path,
                3,
                "Demand",
                c4_id="demand",
                c4_type="container",
                parent="poc",
                depends_on=["data_prep"],
            ),
        ]
        assert validate_c4(docs, c4) == []

    def test_missing_c4_id_field(self, tmp_path):
        c4 = C4Config(enabled=True, id_field="c4_id", levels=("container",))
        docs = [_make_spec(tmp_path, 1, "No ID", c4_id=None, c4_type="container", c4_name="No ID")]
        errors = validate_c4(docs, c4)
        assert len(errors) == 1
        assert "missing required field(s)" in errors[0]
        assert "id" in errors[0]

    def test_missing_c4_type(self, tmp_path):
        c4 = C4Config(enabled=True, id_field="c4_id", levels=("container",))
        docs = [_make_spec(tmp_path, 1, "No Type", c4_id="foo", c4_type=None, c4_name="Foo")]
        errors = validate_c4(docs, c4)
        assert len(errors) == 1
        assert "c4_type" in errors[0]

    def test_missing_c4_name(self, tmp_path):
        c4 = C4Config(enabled=True, levels=("container",))
        [_make_spec(tmp_path, 1, "No Name", c4_id="foo", c4_type="container", c4_name=None)]
        # c4_name defaults to title in _make_spec when c4_id is set, so force it None
        # by writing the file manually
        doc_id = _doc_id(2)
        path = tmp_path / f"{doc_id.lower()}-manual.md"
        path.write_text(
            f"---\nid: {doc_id}\nstatus: approved\ndate: 2026-04-05\nc4_id: bar\nc4_type: container\n---\n"
            f"# {doc_id}\n\n## Overview\n\n## Technical Design\n\n## Testing Strategy\n"
        )
        dt = _spec_type()
        meta = DocFrontmatter.model_validate(
            {"id": doc_id, "status": "approved", "date": "2026-04-05"},
            context={"doc_type": dt},
        )
        raw = {
            "id": doc_id,
            "status": "approved",
            "date": "2026-04-05",
            "c4_id": "bar",
            "c4_type": "container",
        }
        doc = DocDocument(path=path, meta=meta, body="", doc_type=dt, raw_metadata=raw)
        errors = validate_c4([doc], c4)
        assert len(errors) == 1
        assert "c4_name" in errors[0]

    def test_invalid_c4_type(self, tmp_path):
        c4 = C4Config(enabled=True, id_field="c4_id", levels=("system", "container"))
        docs = [_make_spec(tmp_path, 1, "Bad Type", c4_id="foo", c4_type="microservice")]
        errors = validate_c4(docs, c4)
        assert len(errors) == 1
        assert "invalid c4_type" in errors[0]
        assert "microservice" in errors[0]

    def test_duplicate_c4_ids(self, tmp_path):
        c4 = C4Config(enabled=True, id_field="c4_id", levels=("container",))
        docs = [
            _make_spec(tmp_path, 1, "First", c4_id="same_id"),
            _make_spec(tmp_path, 2, "Second", c4_id="same_id"),
        ]
        errors = validate_c4(docs, c4)
        assert len(errors) == 1
        assert "duplicate" in errors[0].lower()
        assert "same_id" in errors[0]

    def test_parent_resolves(self, tmp_path):
        c4 = C4Config(enabled=True, id_field="c4_id", levels=("system", "container"))
        docs = [
            _make_spec(tmp_path, 1, "System", c4_id="poc", c4_type="system"),
            _make_spec(tmp_path, 2, "Child", c4_id="child", parent="poc"),
        ]
        assert validate_c4(docs, c4) == []

    def test_parent_not_found(self, tmp_path):
        c4 = C4Config(enabled=True, id_field="c4_id", levels=("container",))
        docs = [_make_spec(tmp_path, 1, "Orphan", c4_id="orphan", parent="nonexistent")]
        errors = validate_c4(docs, c4)
        assert len(errors) == 1
        assert "parent 'nonexistent' not found" in errors[0]

    def test_depends_on_resolves(self, tmp_path):
        c4 = C4Config(enabled=True, id_field="c4_id", levels=("container",))
        docs = [
            _make_spec(tmp_path, 1, "A", c4_id="a"),
            _make_spec(tmp_path, 2, "B", c4_id="b", depends_on=["a"]),
        ]
        assert validate_c4(docs, c4) == []

    def test_depends_on_not_found(self, tmp_path):
        c4 = C4Config(enabled=True, id_field="c4_id", levels=("container",))
        docs = [_make_spec(tmp_path, 1, "Lonely", c4_id="lonely", depends_on=["ghost"])]
        errors = validate_c4(docs, c4)
        assert len(errors) == 1
        assert "depends-on 'ghost' not found" in errors[0]

    def test_dead_docs_filtered(self, tmp_path):
        c4 = C4Config(enabled=True, id_field="c4_id", levels=("container",))
        # Superseded doc with missing c4_name — should NOT produce an error because it's filtered
        docs = [_make_spec(tmp_path, 1, "Dead", c4_id="dead", status="superseded")]
        errors = validate_c4(docs, c4)
        assert errors == []

    def test_disabled_c4_is_noop(self, tmp_path):
        c4 = C4Config(enabled=False)
        docs = [
            _make_spec(
                tmp_path,
                1,
                "Whatever",
                c4_id=None,
                doc_type=_spec_type(c4_enabled=False),
            )
        ]
        assert validate_c4(docs, c4) == []


# ── generate_c4_container tests ──────────────────────────────


class TestGenerateC4Container:
    def test_generates_diagram(self, tmp_path):
        c4 = C4Config(enabled=True, id_field="c4_id", levels=("system", "container"))
        docs = [
            _make_spec(tmp_path, 1, "PoC", c4_id="poc", c4_type="system"),
            _make_spec(tmp_path, 2, "Data Prep", c4_id="data_prep", parent="poc"),
            _make_spec(
                tmp_path,
                3,
                "Demand",
                c4_id="demand",
                parent="poc",
                depends_on=["data_prep"],
            ),
        ]
        result = generate_c4_container(docs, c4)
        assert result is not None
        assert "C4Container" in result
        assert "System_Boundary" in result
        assert "data_prep" in result
        assert "demand" in result
        assert "depends on" in result

    def test_disabled_returns_none(self, tmp_path):
        c4 = C4Config(enabled=False)
        assert generate_c4_container([], c4) is None

    def test_no_c4_docs_returns_none(self, tmp_path):
        c4 = C4Config(enabled=True, levels=("container",))
        dt = _spec_type()
        doc_id = _doc_id(1)
        path = tmp_path / f"{doc_id.lower()}-no-c4.md"
        path.write_text(f"---\nid: {doc_id}\nstatus: approved\ndate: 2026-04-05\n---\n# {doc_id}\n")
        meta = DocFrontmatter.model_validate(
            {"id": doc_id, "status": "approved", "date": "2026-04-05"},
            context={"doc_type": dt},
        )
        raw = {"id": doc_id, "status": "approved", "date": "2026-04-05"}
        doc = DocDocument(path=path, meta=meta, body="", doc_type=dt, raw_metadata=raw)
        assert generate_c4_container([doc], c4) is None

    def test_dead_docs_excluded_from_diagram(self, tmp_path):
        c4 = C4Config(enabled=True, id_field="c4_id", levels=("container",))
        docs = [
            _make_spec(tmp_path, 1, "Alive", c4_id="alive"),
            _make_spec(tmp_path, 2, "Dead", c4_id="dead", status="superseded"),
        ]
        result = generate_c4_container(docs, c4)
        assert result is not None
        assert "alive" in result
        assert "dead" not in result.lower().split("container")[1]  # dead not in container nodes


# ── Integration: config loading ──────────────────────────────


class TestC4Config:
    def test_c4_config_loaded_from_decree_toml(self, tmp_path, monkeypatch):
        decree_toml = tmp_path / "decree.toml"
        decree_toml.write_text("""\
[types.spec]
dir = "decree/spec"
prefix = "SPEC"
digits = 3
initial_status = "draft"
statuses = ["draft", "approved"]
required_sections = []

[types.spec.transitions]
draft = ["approved"]
approved = []

[types.spec.actions]
approve = "approved"

[types.spec.c4]
enabled = true
id_field = "c4_id"
levels = ["system", "container", "component"]
""")
        monkeypatch.chdir(tmp_path)
        from decree.config import load_doc_types

        types = load_doc_types()
        spec_type = next(t for t in types if t.name == "spec")
        assert spec_type.c4 is not None
        assert spec_type.c4.enabled is True
        assert spec_type.c4.id_field == "c4_id"
        assert spec_type.c4.levels == ("system", "container", "component")

    def test_no_c4_section_means_none(self, tmp_path, monkeypatch):
        decree_toml = tmp_path / "decree.toml"
        decree_toml.write_text("""\
[types.adr]
dir = "decree/adr"
prefix = "ADR"
digits = 4
initial_status = "proposed"
statuses = ["proposed", "accepted"]
required_sections = []

[types.adr.transitions]
proposed = ["accepted"]
accepted = []

[types.adr.actions]
accept = "accepted"
""")
        monkeypatch.chdir(tmp_path)
        from decree.config import load_doc_types

        types = load_doc_types()
        adr_type = next(t for t in types if t.name == "adr")
        assert adr_type.c4 is None
