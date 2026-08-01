import json

from modagent import agent as agent_module
from modagent.agent import Agent
from modagent.config import Config


def _selected_rows():
    return [
        {
            "source": "nexus",
            "mod_id": "2415",
            "file_id": "7327",
            "variant_id": "2415:7327",
            "variant_name": "Oily skin Mai",
            "file_name": "Mai Simple C1 edits.zip",
        },
        {
            "source": "nexus",
            "mod_id": "1725",
            "file_id": "6001",
            "variant_id": "1725:6001",
            "variant_name": "标准款",
            "file_name": "Cammy C2 PAWG.rar",
        },
    ]


def _strict_agent():
    instance = Agent(Config())
    instance._selection_action = "confirm"
    instance._selection_confirm_rows = instance._normalize_selection_rows(
        _selected_rows()
    )
    instance._selection_strict_nexus = True
    instance._selection_allowed_nexus_ids = {"2415", "1725"}
    return instance


def test_partial_exact_download_never_starts_install_and_is_not_repeated(
    monkeypatch,
):
    calls = []

    def fake_execute(name, args, _cfg):
        calls.append((name, dict(args)))
        return json.dumps({
            "status": "partial_manual_action_required",
            "success": [{
                "mod_id": "2415",
                "file_id": "7327",
                "local_path": "C:/tmp/2415.zip",
            }],
            "failed": [],
            "pending_verification": [{
                "mod_id": "1725",
                "file_id": "6001",
            }],
        }, ensure_ascii=False)

    monkeypatch.setattr(agent_module, "execute", fake_execute)
    instance = _strict_agent()

    first = json.loads(instance._exec("batch_download", {
        "mods": [{"mod_id": "9999"}],
    }))
    second = json.loads(instance._exec("batch_download", {
        "mods": [{"mod_id": "9999"}],
    }))
    install = json.loads(instance._exec("mod_install_batch", {
        "items": [{"local_path": "C:/tmp/2415.zip"}],
    }))

    assert first["status"] == "partial_manual_action_required"
    assert second["reused_result"] is True
    assert install["status"] == "download_incomplete"
    assert install["install_blocked"] is True
    assert len(calls) == 1
    assert calls[0][0] == "batch_download"
    assert [row["mod_id"] for row in calls[0][1]["mods"]] == [
        "2415", "1725",
    ]


def test_exact_download_forces_exact_install_and_truthful_completion(
    monkeypatch,
):
    calls = []

    def fake_execute(name, args, _cfg):
        calls.append((name, json.loads(json.dumps(args))))
        if name == "batch_download":
            return json.dumps({
                "status": "completed",
                "success": [
                    {
                        "mod_id": "2415",
                        "file_id": "7327",
                        "local_path": "C:/tmp/2415.zip",
                    },
                    {
                        "mod_id": "1725",
                        "file_id": "6001",
                        "local_path": "C:/tmp/1725.rar",
                    },
                ],
                "failed": [],
                "pending_verification": [],
            }, ensure_ascii=False)
        return json.dumps({
            "status": "completed",
            "total": 2,
            "succeeded": 2,
            "failed": 0,
            "all_selected_installed": True,
            "results": [],
        }, ensure_ascii=False)

    monkeypatch.setattr(agent_module, "execute", fake_execute)
    instance = _strict_agent()

    downloaded = json.loads(instance._exec("batch_download", {"mods": []}))
    installed = json.loads(instance._exec("mod_install_batch", {
        "items": [{"local_path": "C:/tmp/wrong.zip"}],
    }))

    assert downloaded["status"] == "completed"
    assert installed["all_selected_installed"] is True
    assert instance._install_completed_this_turn is True
    assert [call[0] for call in calls] == [
        "batch_download", "mod_install_batch",
    ]
    install_items = calls[1][1]["items"]
    assert {item["local_path"] for item in install_items} == {
        "C:/tmp/2415.zip", "C:/tmp/1725.rar",
    }
    assert {item["variant_id"] for item in install_items} == {
        "2415:7327", "1725:6001",
    }


def test_partial_install_cannot_be_reported_as_completed(monkeypatch):
    def fake_execute(name, args, _cfg):
        if name == "batch_download":
            return json.dumps({
                "status": "completed",
                "success": [
                    {
                        "mod_id": row["mod_id"],
                        "file_id": row["file_id"],
                        "local_path": f"C:/tmp/{row['mod_id']}.zip",
                    }
                    for row in _selected_rows()
                ],
                "failed": [],
                "pending_verification": [],
            }, ensure_ascii=False)
        return json.dumps({
            "status": "partial_failure",
            "total": 2,
            "succeeded": 1,
            "failed": 1,
            "all_selected_installed": False,
            "results": [],
        }, ensure_ascii=False)

    monkeypatch.setattr(agent_module, "execute", fake_execute)
    instance = _strict_agent()

    instance._exec("batch_download", {"mods": []})
    result = json.loads(instance._exec("mod_install_batch", {"items": []}))

    assert result["status"] == "partial_failure"
    assert result["all_selected_installed"] is False
    assert instance._install_completed_this_turn is False


def test_direct_single_file_tools_are_blocked_in_exact_confirmation():
    instance = _strict_agent()

    for name, args in (
        ("mod_download", {"mod_id": "2415", "file_id": "7327"}),
        ("download_from_url", {"url": "https://example.com/mod.zip"}),
        ("mod_install", {"mod_id": "2415"}),
        ("mod_install_custom", {"path": "C:/tmp/mod.zip"}),
    ):
        result = json.loads(instance._exec(name, args))
        assert result["status"] == "exact_batch_required"
        assert result["install_blocked"] is True
