"""Direct installation requests remain single-target discovery tasks."""

from modagent.agent import explicit_install_target


assert explicit_install_target("帮我安装 ModsUp 1.0.5") == {
    "name": "ModsUp",
    "version": "1.0.5",
}
assert explicit_install_target("请帮我装上“ModsUp 1.0.5”") == {
    "name": "ModsUp",
    "version": "1.0.5",
}
assert explicit_install_target(
    "更好的物品扫描器\ncustom_ts_reepchik_BetterItemScanner_1.0.0 帮我安装这个"
) == {
    "name": "reepchik_BetterItemScanner",
    "version": "1.0.0",
}
assert explicit_install_target("安装一个 mod") == {}
assert explicit_install_target("推荐十个地图 mod") == {}

print("ALL PASS")
