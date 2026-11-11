"""Offline prompt payload report; never contacts a model/source or loads a profile."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modagent import config, db, legacy_prompts, prompts
from modagent.agent import Agent
from modagent.orchestration import prompting, legacy_prompting
from modagent.orchestration.models import AgentMode, TaskSpec
from modagent.orchestration.router import route_message


def run():
    report = {"revision": prompting.PROMPT_REVISION, "units": "Unicode characters, not tokens",
              "real_model_calls": 0, "cases": [], "limitations": [
                  "Payload sizes and deterministic contracts do not prove model quality.",
                  "Tools, selection context and history are counted separately; moving data does not eliminate it.",
                  "Legacy off/shadow retains its tool set and history behavior."]}
    with patch.object(config, "load_prompt", return_value=""), patch.object(prompting, "load_prompt", return_value=""), patch.object(legacy_prompting, "load_prompt", return_value=""), patch.object(db, "get_installed_mods", return_value=[]):
        cfg = config.Config(tier="pro")
        task = TaskSpec.create(session_id="fixture", game_id="", intent=AgentMode.CHAT_EXPLAIN, user_goal="什么是 Mod?")
        report["empty_context_baseline"] = {
            "legacy_base_chars": len(legacy_prompts.build_legacy_prompt(cfg)),
            "previous_v2_chat_chars": len(legacy_prompting.build_legacy_v2_prompt(cfg, task)),
            "compact_shared_core_chars": len(prompts.build_prompt(cfg)),
            "compact_v2_chat_chars": len(prompting.build_v2_prompt(cfg, task)),
        }
        for feature in ("off", "shadow", "on"):
            for message, action in (("什么是 Mod?", ""), ("帮我找 Tifa 换皮", ""),
                                    ("为什么游戏打不开", ""), ("生成所选安装计划", "plan"),
                                    ("确认所选安装计划", "confirm")):
                rows = [{"source": "nexus", "mod_id": str(n), "source_id": str(n),
                         "file_id": 1000+n, "name": "Fixture-" + str(n),
                         "selected_variant_id": "variant-" + str(n),
                         "detail_verified": True, "installable": True} for n in range(20)] if action else []
                route = route_message(message, selection_action=action, has_selection=bool(rows))
                task = TaskSpec.create(session_id="fixture", game_id="", intent=route.intent,
                                       user_goal=message, authorization={"install": action == "confirm"})
                captured = {}
                def offline(messages, tools):
                    captured.update(prompting.measure_request(messages, tools))
                    raise TimeoutError("offline capture: no model called")
                agent = Agent(cfg)
                with patch.object(agent, "_stream", side_effect=offline):
                    list(agent.chat_stream(message, recommendation_selection=rows, selection_action=action,
                                           task_spec=task, core_mode=feature))
                report["cases"].append({"feature": feature, "mode": route.intent.value,
                                        "selected_rows": len(rows), **captured})
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run()
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(output)
    print(output)
