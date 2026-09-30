"""The final installation report must include Workshop and archive targets together."""
from modagent.agent import Agent


report = Agent._format_install_completion_report([
    {
        "results": [
            {
                "mod_id": "ws_1", "name": "Workshop One", "ok": True,
                "status": "installed", "version": "1.0", "files_installed": ["a"],
                "dependencies": [], "warnings": [],
            }
        ]
    },
    {
        "results": [
            {
                "mod_id": "ws_2", "name": "Workshop Two", "ok": False,
                "status": "steam_download_pending", "version": "", "files_installed": [],
                "dependencies": [], "warnings": ["pending"],
                "error": "Steam download has not finished",
            }
        ]
    },
    {
        "results": [
            {
                "mod_id": "nexus_3", "name": "Archive Three", "ok": True,
                "status": "installed", "version": "2.0", "files_installed": ["b", "c"],
                "dependencies": [], "warnings": [],
            }
        ]
    },
])

assert "2/3" in report, report
assert "Workshop One" in report, report
assert "Workshop Two" in report, report
assert "Archive Three" in report, report
assert "等待 Steam" in report, report
print("ALL PASS")
