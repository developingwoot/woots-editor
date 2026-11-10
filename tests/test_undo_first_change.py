"""The first change made through the app to a plan file must be undoable: the version before it is recorded first."""
import json

import projectstore


def test_first_write_records_the_file_as_it_was(tmp_path):
    p = tmp_path / "x.beatmap.json"
    p.write_text(json.dumps({"a": 1}), encoding="utf-8")
    projectstore.write_json(p, {"a": 2})
    es = projectstore.history(tmp_path, "x.beatmap.json")
    assert len(es) == 2 and es[1]["who"] == "before history"
    projectstore.restore(tmp_path, es[1]["id"])
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}


def test_a_new_file_has_only_its_first_version(tmp_path):
    p = tmp_path / "y.notes.json"
    projectstore.write_json(p, {"n": []})
    assert len(projectstore.history(tmp_path, "y.notes.json")) == 1
