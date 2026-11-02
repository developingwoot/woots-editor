import workflow


def test_a_new_workspace_without_a_work_folder_lists_no_videos(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "WORK", tmp_path / "_editor" / "work")
    assert workflow.list_videos() == []
