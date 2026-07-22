"""Old custom prompts cannot suppress current execution invariants."""

from modagent import config, db, prompts


old_load_prompt = config.load_prompt
old_get_installed = db.get_installed_mods
try:
    config.load_prompt = lambda: (
        "# ModAgent System Prompt v0.5\n"
        "自定义语气仍应保留。\n"
        "CURRENT STATE: {game_info}\n{installed_mods}"
    )
    db.get_installed_mods = lambda _slug="": []
    cfg = config.Config(
        game_name="Final Fantasy VII Rebirth",
        game_slug="local_final_fantasy_vii_rebirth",
        game_root=r"C:\Games\FF7R",
    )
    result = prompts.build_prompt(cfg)
    assert "自定义语气仍应保留" in result
    assert "空缓存不等于下载失败" in result
    assert "API 403 是路径切换" in result
    assert "每个文件独立推进" in result
finally:
    config.load_prompt = old_load_prompt
    db.get_installed_mods = old_get_installed

print("ALL PASS")
