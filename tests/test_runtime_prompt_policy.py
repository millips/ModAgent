"""Old custom prompts cannot suppress current execution invariants."""

from modagent import config, db, prompts


old_load_prompt = config.load_prompt
old_get_installed = db.get_installed_mods
try:
    config.load_prompt = lambda: (
        "# ModAgent System Prompt v0.5\n"
        "语气友好\n"
        "捕获到文件就继续安装。\n"
        "CURRENT STATE: {game_info}\n{installed_mods}"
    )
    db.get_installed_mods = lambda _slug="": []
    cfg = config.Config(
        game_name="Final Fantasy VII Rebirth",
        game_slug="local_final_fantasy_vii_rebirth",
        game_root=r"C:\Games\FF7R",
    )
    result = prompts.build_prompt(cfg)
    assert "语气友好" in result
    assert "捕获到文件就继续安装" not in result
    assert "下载完成不等于获准安装" in result
    assert "不构成继续执行的许可" in result
    assert len(result) < 4000
finally:
    config.load_prompt = old_load_prompt
    db.get_installed_mods = old_get_installed

print("ALL PASS")
