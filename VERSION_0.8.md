# ModAgent v0.8 — 后端核心稳定版

> 提交: `836637a3` (tag: v0.8) + 清理提交 `c1442dd9`
> 日期: 2026-07-10
> 定位: **后端核心链路稳定版**。前端一致性与创意工坊为已知待办区。

---

## 一、这个版本是什么

以"修好《剑星》N 键换装菜单"为线索的真实排障,暴露并修复了一批系统性缺陷后的第一个稳定锚点。
核心承诺:**装得上、卸得掉、回得去、不骗人。**

- 实战验收:剑星 CNS N 键菜单已在真实游戏中弹出(Chrisr0 RE-UE4SS 3.1.0-6 + CNS v2.2,F 盘)
- 备份:代码入 git(tag v0.8);数据目录手动备份为 `.modagent_备份_v0.8`

## 二、包含的关键修复(均已验证)

| 修复 | 位置 | 验证方式 |
|---|---|---|
| mod 互删保护(共享文件引用计数) | installer.uninstall_mod + db.get_shared_files + tools | 端到端模拟:卸 UE4SS,CNS 共享的 settings.ini 幸存 |
| 游戏检测以 acf 为权威源(卸载残骸不再出现) | games.detect_steam_games | /games/detect:E 盘残骸消失,几十游戏无误判 |
| 活体守卫(拒绝装进空壳/残骸) | tools.mod_install + games.verify_game_alive | 沙箱:指向 E 盘残骸时 8ms 拒绝 |
| 游戏体检 + 手动导入端点 | api /games/health /games/import | /games/health 返回 alive:true |
| conflict_check 透视 zip(archive_contents)+ 智能剥壳 | installer.conflict_check | 沙箱:38 文件全列,stripped_top_dir 正确 |
| GitHub Releases 自动解析(选正式版、跳过 dev) | tools._resolve_github_release_url | 对话:releases 页面链接 → 自动下载 UE4SS_v3.1.0-6.zip |
| 空安装守卫(全 skipped 不落库不报成功) | tools.mod_install | 带壳包安装失败时正确报错(六月式"装了个寂寞"绝迹) |
| 智能剥壳(单一顶层目录自动剥离) | installer.install_mod | 带 UE4SS_v3.1.0-6/ 壳的包 30 文件正确落位 |
| cow_backup 回归清除 | installer | 安装不再抛 "no attribute cow_backup" |
| 工具看门狗(90s 超时,SSE 不再卡死) | agent._exec | scan_existing_mods 卡死场景 |
| game_file_check 只读诊断(查文件/读log,防越界) | tools | 查 UE4SS.log 判断注入成败的主力工具 |
| list_downloads 列下载缓存 | tools | (v0.8 后补,待沙箱验证) |
| prompt v0.5 | .modagent/prompt.md | 甩锅红线/依赖版本核对/诊断四补丁/忠实转述三禁令/含糊需求先澄清 |
| 状态断言三闸门校验器 + 防纠偏泄漏 | report_validator | 11 用例全过;"ue4ss是什么版本"强制先查工具 |

## 三、已知待办(v0.8 明确不含)

- 前端:顶栏与游戏下拉框不一致(下拉框曾挂 E 盘毒路径);重新生成不回退 history;提前收尾卡输入框;Mod/快照界面缺"刷新/对账"按钮
- installed_mods 对账端点(/mods/reconcile:账本 vs 磁盘实物)
- conflict_check 只认绝对路径(裸文件名不自动补下载目录)
- GitHub 按版本名模糊匹配("下 Build 5")
- Steam 创意工坊链路未系统测试
- 34 个服装 mod 迁移(账本旧记录指向 E 盘,待批量重装到 F)
- 长上下文下回合铁律偶发失效(宣告后空转)

## 四、I 盘文件校验清单(防版本飘忧)

每次替换文件/怀疑版本不对时,跑以下检查确认真身完整。

### 4.1 代码标记检查(命令行,项目目录下)

```
findstr /c:"get_shared_files" modagent\db.py && echo db互删OK
findstr /c:"shared_files" modagent\installer.py && echo installer互删OK
findstr /c:"_strip_dir" modagent\installer.py && echo 剥壳OK
findstr /c:"archive_contents" modagent\installer.py && echo 透视OK
findstr /c:"verify_game_alive" modagent\games.py && echo 活体OK
findstr /c:"steam_acf" modagent\games.py && echo acf检测OK
findstr /c:"_resolve_github_release_url" modagent\tools.py && echo GitHub解析OK
findstr /c:"game_file_check" modagent\tools.py && echo 诊断工具OK
findstr /c:"list_downloads" modagent\tools.py && echo 缓存列表OK
findstr /c:"games/health" modagent\api.py && echo 体检端点OK
findstr /c:"TOOL_TIMEOUT" modagent\agent.py && echo 看门狗OK
```

### 4.2 运行时沙箱检查(后端启动后,PowerShell)

```powershell
# 工具活性(任一返回"未知工具"即说明版本不对)
Invoke-RestMethod -Uri "http://127.0.0.1:18890/debug/exec" -Method Post -ContentType "application/json" -Body '{"name":"game_file_check","args":{"path":"SB/Binaries/Win64/dwmapi.dll"}}'
Invoke-RestMethod -Uri "http://127.0.0.1:18890/debug/exec" -Method Post -ContentType "application/json" -Body '{"name":"list_downloads","args":{}}'
# 游戏检测(E盘残骸不应出现;F盘 real:true)
# 浏览器: http://127.0.0.1:18890/games/detect
# 体检(configured.alive 应为 true)
# 浏览器: http://127.0.0.1:18890/games/health
```

### 4.3 铁律(血泪版)

1. 改代码前,先从 I 盘拷当前真身作基底;改完替换回 I 盘;**重启后端才生效**。
2. 每次替换后立刻跑 4.2 验证关键工具还在——"game_file_check 凭空消失"事件不允许重演。
3. 每轮修复验证通过后 `git add . && git commit`;大节点打 tag。
4. C 盘 `.modagent\` 是数据目录,不进 git,重大节点手动备份。
5. 验证 agent 的说法用 `/debug/exec` 沙箱直接问文件系统,不信转述。

---

*本文件随 git 管理。下一个稳定锚点目标:v0.9(前端一致性 + 创意工坊验证 + 34 mod 迁移完成)。*
