def build_prompt(cfg):
    from .config import load_prompt
    custom = load_prompt()
    if custom:
        template = custom
    else:
        # 默认 prompt 从仓库 default_prompt.md 读(权威 v0.5,受版控);
        # 用户 ~/.modagent/prompt.md 存在时优先(上面 custom 分支)。
        import os
        _p = os.path.join(os.path.dirname(__file__), "default_prompt.md")
        try:
            with open(_p, encoding="utf-8") as f:
                template = f.read()
        except OSError:
            template = ("你是 ModAgent，面向中文玩家的游戏 Mod 管理助手。\n"
                        "当前游戏：{game_info}\n已安装 Mod：\n{installed_mods}\n")

    from .db import get_installed_mods

    if not cfg.game_root:
        game_info = "（用户尚未选择游戏，请先让其在右上角选择游戏）"
    elif (cfg.game_slug or "").startswith("local_"):
        game_info = (f"《{cfg.game_name}》（目录: {cfg.game_root}）"
                     f"——该游戏尚未建立静态 Nexus 映射，将根据游戏名动态探测 Nexus 等来源；"
                     f"探测失败或搜索为空都不代表平台未收录。仍可处理本地已有 mod、快照等操作。")
    else:
        game_info = f"《{cfg.game_name}》（Nexus slug: {cfg.game_slug}, 目录: {cfg.game_root}）"

    # 可用来源先验(#1):让 agent 知道该游戏在哪些平台有 mod,搜索/推荐按此挑源,
    # 不再默认只搜 Nexus。探测带缓存+限时,失败降级为不注入,绝不阻塞对话。
    if cfg.game_root:
        try:
            from .sources import available_sources
            src = available_sources(
                cfg.game_name or "", cfg.game_slug or "", cfg.game_root,
                getattr(cfg, "tavily_api_key", ""))
            status = src.get("source_status", {})
            parts = [
                "Nexus✓" if src["nexus"] else "Nexus✗",
                f"创意工坊✓(appid {src['workshop']})" if src["workshop"] else "创意工坊✗",
                f"Thunderstore✓({src['thunderstore']})" if src["thunderstore"] else "Thunderstore✗",
                "GameBanana✓" if src["gamebanana"] else "GameBanana✗",
                "GitHub✓",
            ]
            game_info += ("\n可用 mod 来源:" + " / ".join(parts)
                          + "(✗=当前未确认可用,不是平台不存在;搜索/推荐优先从 ✓ 的源里挑 2-3 个综合)")
            import json
            game_info += (
                "\n来源探测状态:" + json.dumps(status, ensure_ascii=False)
                + "\nnot_detected/candidate/search_failed/credentials_missing 均不代表平台不存在;"
                  "空结果只能表述为“本次未搜到”。")
        except Exception:
            pass

    mods = get_installed_mods(cfg.game_slug)
    if mods:
        mod_lines = [f"- [{m.name}] v{m.version} (顺序: {m.load_order})" for m in mods]
        mod_info = "\n".join(mod_lines)
    else:
        mod_info = "(无)"

    body = template.format(game_info=game_info, installed_mods=mod_info)

    # 把"当前游戏"做成对话的强制前提，放在最顶部
    if not cfg.game_root:
        banner = "【当前游戏：用户尚未选择，请先引导其在右上角选择游戏】"
    else:
        banner = (f"【当前游戏：{cfg.game_name}】\n"
                  f"这是本次对话的固定前提。无论用户问什么，都默认围绕《{cfg.game_name}》展开，"
                  f"回答要专业且自然地体现你已知道当前游戏；不要反问'你玩什么游戏'，"
                  f"也不要在用户没要求时就去扫描整个游戏库或长篇跑题。")
    return banner + "\n\n" + body
