"""User-approved, capped live-model test with synthetic read-only tool receipts."""
import json
import os
import time
from pathlib import Path

from openai import OpenAI
from modagent import agent as module, db
from modagent.agent import Agent
from modagent.config import Config
from modagent.orchestration.models import TaskSpec
from modagent.orchestration.router import route_message
from modagent.orchestration import store
from modagent.orchestration.runtime import AgentCoreRuntime

output = Path(__file__).resolve().parents[1] / "build/conversation-flow-20260906-r4/live-model-result-v2.json"
cfg = Config(agent_core_v2="on", game_name="Phasmophobia", game_slug="phasmophobia",
             llm_api_key=os.environ["MODAGENT_LLM_API_KEY"],
             llm_endpoint=os.environ["MODAGENT_LLM_ENDPOINT"], llm_model=os.environ["MODAGENT_LLM_MODEL"])
client = OpenAI(api_key=cfg.llm_api_key, base_url=cfg.llm_endpoint, timeout=40, max_retries=0)
db.init_db()
db.create_session("r4-live", "isolated live-model test", cfg.game_slug)
calls, tool_calls, results, request_sizes = [], [], [], []
module.refresh_local_inventory = lambda *a: None
module.MAX_ROUNDS = 3

def fixture_execute(name, args, _cfg):
    tool_calls.append({"tool": name, "args": args})
    search = {"mod_recommend", "nexus_search", "github_search", "thunderstore_search", "workshop_search", "gamebanana_search"}
    if name in search:
        row = {"mod_id": 424242, "name": "Training UI TEST FIXTURE", "summary": "Phasmophobia training assistance and clearer UI. Synthetic evaluation fixture, not a real downloadable Mod.",
               "url": "https://www.nexusmods.com/phasmophobia/mods/424242", "version": "test"}
        return json.dumps({"query": args.get("query", ""), "results": [row], "recommendations": [row], "sources_consulted": ["nexus"], "sources_failed": {}}, ensure_ascii=False)
    if name in {"get_installed", "list_local_mods"}:
        return '[]'
    if name == "nexus_get_detail":
        return json.dumps({"error": "fixture_has_no_download", "message": "This synthetic search fixture has no downloadable files."})
    # No actual tool implementation is reachable, even if the model asks.
    return json.dumps({"error": "live_eval_tool_not_allowed", "install_blocked": True})

module.execute = fixture_execute

class LiveAgent(Agent):
    def _stream(self, messages, tools):
        if len(calls) >= 8:
            raise RuntimeError("live_eval_call_budget_exhausted")
        receipt = {"number": len(calls) + 1, "time": time.time(), "finish_reasons": []}
        calls.append(receipt)
        self._record_prompt_metrics(messages, tools)
        request_sizes.append(self._last_prompt_metrics)
        response = client.chat.completions.create(model=cfg.llm_model, messages=messages,
            tools=tools or None, temperature=0.3, max_tokens=900, stream=True)
        try:
            for chunk in response:
                for choice in chunk.choices:
                    if choice.finish_reason:
                        receipt["finish_reasons"].append(choice.finish_reason)
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    receipt["usage"] = usage.model_dump()
                yield chunk
        finally:
            response.close()
    def _once(self, messages, tools):
        raise RuntimeError("extra_live_generation_disabled")
    def _localize_recommendation_set(self, payload):
        return payload  # Separate localization calls are outside this 8-call trial.

agent = LiveAgent(cfg)
agent.session_id = "r4-live"
messages = ["mod是什么", "我害怕 不敢玩 新手什么都不懂 难度太大了 有没有帮我快速适应的方法",
            "帮我搜搜看 最适合我的mod 如何", "辅助学习的 界面优化的", "你刚才做了什么？", "不用搜了，今天先到这里"]
try:
    for message in messages:
        if len(calls) >= 8:
            break
        route = route_message(message, history=agent.history)
        spec = TaskSpec.create(session_id="r4-live", game_id=cfg.game_slug, intent=route.intent,
            user_goal=message, constraints={"read_only": True, "search_goal": route.search_goal},
            confidence=route.confidence, route_reason=route.reason)
        start = time.monotonic()
        before = len(tool_calls)
        before_calls = len(calls)
        task_events = []
        runtime = AgentCoreRuntime(spec, feature_mode="on", event_sink=task_events.append)
        runtime.start()
        events = [json.loads(item) for item in agent.chat_stream(
            message, task_spec=spec, core_runtime=runtime, core_mode="on")]
        task = store.get_task(spec.task_id)
        results.append({"input": message, "intent": route.intent.value, "seconds": round(time.monotonic() - start, 2),
            "state": task.get("state") if task else "missing", "tools": tool_calls[before:],
            "answer": "".join(item.get("chunk", "") for item in events),
            "recommendation_cards": sum(bool(item.get("recommendations", {}).get("items")) for item in events),
            "task_events": task_events,
            "model_requests": calls[before_calls:],
            "errors": [item["error"] for item in events if "error" in item]})
        print(json.dumps({"case": len(results), "intent": route.intent.value, "state": results[-1]["state"], "calls": len(calls), "seconds": results[-1]["seconds"]}), flush=True)
finally:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"model": cfg.llm_model, "provider_host": "api.deepseek.com", "call_limit": 8,
        "calls_used": len(calls), "max_output_tokens_per_call": 900, "temperature": .3,
        "real_model": True, "real_sources": False, "real_game_writes": False, "localization_tested": False,
        "harness_revision": "r4-runtime-and-finish-reason-2",
        "fixture_contract": "Explicitly invalid synthetic candidate; must not become an actionable recommendation.",
        "results": results, "request_sizes": request_sizes}, ensure_ascii=False, indent=2), encoding="utf-8")
    client.close()
print("LIVE MODEL REPORT SAVED; no real source or game operations were executed", flush=True)
