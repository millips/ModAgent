import sys
import os

from .config import Config, load as load_config, save as save_config, load_prompt, save_prompt, CONFIG_FILE, PROMPT_FILE
from . import db
from .agent import Agent
from . import tools

_CFG: Config = None
_AGENT: Agent = None

MODELS = [
    ("deepseek-chat", "DeepSeek V3 (快速)"),
    ("deepseek-v4-pro", "DeepSeek V4 Pro (推荐)"),
    ("deepseek-reasoner", "DeepSeek R1 (推理)"),
]

GAMES = {
    "1": ("Skyrim Special Edition", "skyrimspecialedition", 1704),
    "2": ("Cyberpunk 2077", "cyberpunk2077", 3333),
    "3": ("Fallout 4", "fallout4", 1151),
}


def main():
    global _CFG, _AGENT
    db.init_db()
    _CFG = load_config()

    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd in ("--help", "-h", "help"):
            _help()
            return
        if cmd == "prompt":
            _edit_prompt()
            return
        if cmd == "config":
            _print_config()
            return

    if not _CFG.nexus_api_key or not _CFG.llm_api_key:
        _first_setup()

    _CFG = load_config()
    _AGENT = Agent(_CFG)
    _chat()


def _first_setup():
    print("\n  ModAgent 首次配置\n")

    cfg = load_config()
    try:
        cfg.nexus_api_key = _input("Nexus Mods API Key")
        cfg.llm_api_key = _input("LLM API Key")

        print("\n选择模型:")
        for i, (mid, desc) in enumerate(MODELS, 1):
            print(f"  {i}. {mid}  ({desc})")
        choice = _input("模型 (1/2/3)", "2")
        idx = int(choice) - 1 if choice.isdigit() else 1
        cfg.llm_model = MODELS[idx][0] if 0 <= idx < len(MODELS) else "deepseek-v4-pro"

        cfg.llm_endpoint = _input("LLM 接口", "https://api.deepseek.com/v1")
    except KeyboardInterrupt:
        print("\n已取消。重新运行 modagent 再次配置。")
        sys.exit(0)

    save_config(cfg)
    print(f"\n  [OK] 配置完成。输入 /game 选游戏，或直接开始对话。\n")


def _chat():
    global _CFG
    print(f"ModAgent | {_CFG.llm_model}")
    if _CFG.game_name:
        print(f"游戏: {_CFG.game_name}")
    print()

    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            break

        if not raw:
            continue

        if raw == "/exit":
            print("再见。")
            break
        if raw == "/help":
            _print_chat_help()
            continue
        if raw == "/reset":
            _AGENT.reset()
            print("[OK] 已重置对话。")
            continue
        if raw == "/game":
            _pick_game()
            continue
        if raw == "/config":
            _print_config()
            continue
        if raw == "/model":
            _pick_model()
            continue
        if raw == "/mods":
            print(tools.execute("list_installed_mods", {}, _CFG))
            continue
        if raw == "/snaps":
            print(tools.execute("list_snapshots", {}, _CFG))
            continue
        if raw == "/log":
            print(tools.execute("get_operation_log", {}, _CFG))
            continue

        try:
            reply = _AGENT.chat(raw)
        except Exception as e:
            reply = f"[ERR] {e}"

        print(f"\n{reply}\n")


def _pick_game():
    global _CFG
    print("选择游戏:")
    for k, (name, slug, gid) in GAMES.items():
        print(f"  {k}. {name}")
    choice = _input("游戏", "1")
    if choice in GAMES:
        _CFG.game_name, _CFG.game_slug, _CFG.game_id = GAMES[choice]
    else:
        print("[ERR] 无效选择。")
        return

    path = _input("游戏目录 (回车跳过)")
    if path:
        _CFG.game_root = path
    save_config(_CFG)
    _AGENT.reset()
    print(f"[OK] 当前游戏: {_CFG.game_name}")


def _pick_model():
    global _CFG
    print("选择模型:")
    for i, (mid, desc) in enumerate(MODELS, 1):
        print(f"  {i}. {mid}  ({desc})")
    choice = _input("模型 (1/2/3)", "2")
    idx = int(choice) - 1 if choice.isdigit() else 1
    if 0 <= idx < len(MODELS):
        _CFG.llm_model = MODELS[idx][0]
        save_config(_CFG)
        _AGENT.reset()
        print(f"[OK] 模型: {_CFG.llm_model}")
    else:
        print("[ERR] 无效选择。")


def _edit_prompt():
    print("粘贴提示词（输入 END 结束）:")
    lines = []
    while True:
        try:
            line = input()
            if line.strip() == "END":
                break
            lines.append(line)
        except (EOFError, KeyboardInterrupt):
            break
    if lines:
        save_prompt("\n".join(lines))
        print(f"[OK] 已保存到 {PROMPT_FILE}")


def _print_config():
    print(f"Nexus Key: {'已设置' if _CFG.nexus_api_key else '未设置'}")
    print(f"LLM Key:   {'已设置' if _CFG.llm_api_key else '未设置'}")
    print(f"模型:      {_CFG.llm_model}")
    print(f"接口:      {_CFG.llm_endpoint}")
    print(f"游戏:      {_CFG.game_name or '未选择'}")
    print(f"目录:      {_CFG.game_root or '未设置'}")
    print(f"提示词:    {'自定义' if load_prompt() else '内置默认'}")


def _print_chat_help():
    print("""
  /game    选择游戏
  /model   切换模型
  /config  查看配置
  /mods    已安装 Mod
  /snaps   快照列表
  /log     操作记录
  /reset   重置对话
  /exit    退出
""")


def _help():
    print("""
ModAgent — AI 游戏 Mod 管理器

  modagent          启动对话
  modagent config   查看配置
  modagent prompt   编辑提示词

首次运行自动进入配置引导。
""")


def _input(prompt: str, default: str = "") -> str:
    if default:
        v = input(f"  {prompt} [{default}]: ").strip()
    else:
        v = input(f"  {prompt}: ").strip()
    return v if v else default


if __name__ == "__main__":
    main()
