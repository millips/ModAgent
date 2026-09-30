# Agent Core v2 修复实施记录

## 范围

2026-09-06 开始实施；依据为同目录 SYSTEM-AUDIT.md 和 probe-results.json。
保留原有未提交修改。不覆盖桌面版、不迁移真实数据、不调用付费模型。
本文件记录实际结果，**不是整个 v2 完成声明**。

## RED 基线（产品修复前）

tests/test_core_v2_audit_regressions.py 新增 19 个参数化检查。
临时 MODAGENT_DATA_DIR、临时 SQLite、模拟工具与模型流，无网络。
结果：17 failed, 2 passed in 2.51s。

| 编号 | 缺陷 | 修复前失败数 |
|---|---|---|
| A01 | 否定/引用/解释授权及误路由 | 8 |
| A02 | 失败加文字/无文本证据变成完成 | 2 |
| A03 | 人工登录/等待确认/失败进入完成账本 | 4 |
| A04 | 断流后 finally 假完成 | 1 |
| A05 | shadow 账本影响真实执行 | 1 |
| A06 | 取消后的晚到回写 | 1 |

正向保留：部分成功和普通解释完成；一个英文输入原本没有错误授权。

## 首次 GREEN

新回归和 test_agent_core_v2、test_terminal_download_guard、test_turn_cancellation、
test_exact_selection_state_machine 组合：47 passed in 2.37s。
首次组合测试发现合法下载被新规则误拦截，收窄解释判定后复测通过。

## 修改

- ToolOutcome 分类，不把人工处理和未知状态当成成功。
- 自然语言路由不再授予写权限，分类回调也不能授予权限。
- 解释/更新故障先于操作关键词；共享 Agent 入口保护提问和未确认更新。
- runtime 的终态不因文字掩盖失败；断流显式进入失败/部分成功。
- shadow 不读复用检查点/账本，不写执行检查点和副作用账本。
- 同一 runtime 内工具回写与结束加锁；已结束任务忽略晚到回写。
- 旧任务恢复接口要求重新核验计划，不带残缺状态继续执行。

## 未完成边界

- 服务端 PlanRevision/ExecutionGrant、所有 API 和快捷操作统一门禁。
- run_id、原子占位、跨进程写锁、事务取消、崩溃后对账。
- 文件/组件身份和完整恢复。本次阻止不安全恢复，不声称恢复已可用。
- 独立 120 条业务场景、500/1000 故障扩展及真实模型验收。
- 搜索、多组件变体、统一前端事件、结构化计划、提示词收缩。
- 网络客户端统一、Free/P 候选包及桌面验收。

ToolOutcome 是兼容收据适配，不是实际文件验证器。
运行内晚到回写保护不等于已停止正在运行的文件事务。

## 本批最终验收（2026-09-06）

### 已执行

- 审计安全回归扩展到 39 项：通过。
- HTTP 接口回归 4 项：通过。覆盖 off/shadow/on 的异常回复与历史保留、旧恢复接口拒绝且不改写原任务。
- `scripts/run-python-regressions.py` 最后全量运行：**All 104 regression files passed**。
  这是按文件独立进程执行的现有回归，不是 104 条真实模型场景，也不代表发布门槛已通过。
- 前端纯逻辑：test-task-outcome.mjs、test-chat-quick-replies.mjs、test-recommendation-recovery.mjs 全部通过。
- Free 前端独立 Vite 构建：1496 modules，9.36s，通过。
- P 前端独立 Vite 构建：1559 modules，3.62s，通过。
- 两个临时构建的 edition.json 分别为 free/subscription、beta、1.6.0-beta.1。
- 本批涉及的既有跟踪文件 diff --check 通过。统计中的原有大段未提交修改不算本批工作量。

### 后续补充修复

- TaskSpec 深层冻结，输入对象及反序列化副本不能改写任务目标/权限。
- 旧效果键加入完整参数和游戏身份，修正同 Mod 不同 file_id、不同批次共用键的碰撞。
  这还不是有验证器、占位和崩溃对账的完整 operation_id 机制。
- shadow 存储异常不会阻止真实工具运行，shadow 事件不再驱动正式界面。
- 到达循环上限不再登记为已完成；模型声称安装成功但无安装工具收据时不能完成。
- 接口异常输出用户可读总结，并保留该轮用户问题；错误事件不暴露原始异常敏感文本。
- 界面不再单凭 SSE 结束就生成安装确认/完成卡；确认执行缺少安装完成收据时不显示成功。
- 界面按收据显示等待/未完成，不把人工登录写成步骤完成；HTTP 拒绝及旧任务恢复原因可直接显示。

### 仍需明确的限制

- 阶段 0 只完成了第一批审计失败基线，尚非全部 120 条独立业务场景。
- 阶段 1 已落地并验证上述修复，但不能据此宣称所有授权/假完成路径都已消除。
- 旧自然语言安装/人工验证继续路径仍有兼容职责；不是完整的服务端计划授权系统。
- 结构化 confirm 仍需阶段 2 的服务端计划修订/授权凭据接管；不把客户端选择字段视为最终设计。
- 全部来源状态 schema、真实写入验证、文件事务取消、跨运行结果隔离尚未完成。
- 未执行真实模型请求、外网下载、真实游戏安装或桌面点击验收。
- 未构建后端 exe/NSIS/测试 zip，未发包、未上传 GitHub、未改版本/默认开关。
- Vite CJS API 和 postcss 模块类型有原有构建警告，不影响本次构建；未在此批额外改包配置。

### 源码凭据 SHA-256（不是安装包哈希）

| 文件 | SHA-256 |
|---|---|
| modagent/orchestration/outcomes.py | DB83A266E29020F5AAF06865928ABCD58C80E31D276D57451E724BFB94F165F0 |
| modagent/orchestration/runtime.py | E4AAAF50A14083C874C6FE5BDDB53C908E95518F09B9C70DD878F8C5C0A4D1BD |
| modagent/orchestration/router.py | 7B483F47ED8FF03A94010AD179E1476B06B922971F125C1BD2D4EA1730EBA412 |
| modagent/orchestration/models.py | 00A0B65AEA3E2C174D4E2190F41DF64455F9B94659AC12DEB2BE565013A28EBC |
| tests/test_core_v2_audit_regressions.py | 41BBCFFB5D26A90EC55E9E7179BE8F5C5577ADAB787E404F14D5E991277AB2BB |
| tests/test_core_v2_api_safety.py | 07EB359C7FFCA24BB4AEFEE8132B35FE32B0787EE82F0834A1748CA40617C0B6 |

下一批承接：先将界面确认绑定到服务端 PlanRevision/ExecutionGrant，再迁移执行账本与恢复。
不先删提示词，不把这批静态/离线通过数当作实际 Agent 质量验收。

## 独立候选包交付（2026-09-06，core-safety-20260906-r1）

本节更新上方历史时点的“未打包”状态；完整 v2 仍未完成。

- 基础版本 1.6.0-beta.1；新编译后端、Free/P 前端并组装独立 Electron 免安装目录及 ZIP，不覆盖旧桌面版。
- 测试包独立 appId、用户数据、后端数据与浏览器端口；不继承正式数据目录，禁用应用自动更新；仅测试包固定 agent_core_v2=on。
- 后端全量再次运行：All 105 regression files passed。pytest 缓存写入有权限警告但无失败；不是 105 条真实模型场景。
- 隔离及安全接口组合测试 47 passed；前端身份、隔离、更新禁用与任务结果检查通过。
- Free/P 均在构建和桌面交付路径通过临时数据目录下的程序化启动检查：后端健康、页面加载、无顶层渲染异常、正常退出。不是完整人工 UI 验收。
- app.asar 中主进程模块与源码逐字节一致；版别、beta 和 candidate 标识正确。
- 两包内后端 exe 与新编译输出哈希相同：E3DC0AE8862DEECEEB561D4A3FAE086F464BE334986C9995F1305E43BCA7F112。
- Free 291、P 294 个程序文件复制后逐文件哈希一致；各另附 TESTING.txt。ZIP 内全部 292/295 个文件亦逐个通过哈希检查。
- 桌面目录：C:/Users/Administrator/Desktop/ModAgent Core Safety 测试包 20260906-r1。
- 指南：docs/testing/CORE-SAFETY-20260906-r1.md，桌面同内容文件为“先读我-测试说明.txt”。
- PACKAGE-MANIFEST.json 记录逐文件及 ZIP 大小/哈希；源码含未提交改动，不能仅凭 HEAD 复现。

| ZIP | 字节 | SHA-256 |
|---|---:|---|
| ModAgent-Free-core-safety-20260906-r1.zip | 173942282 | 3ded57feef1b2091a93be600c0201e5680797e3d1906a81d8b8b2139126fd6b0 |
| ModAgent-P-core-safety-20260906-r1.zip | 216735316 | b7c219a214ef5e02f258fdbc332bbfcc6832d2c1d687a3da7c4e424a892f5547 |

未测试：真实模型、真实游戏写入、外网下载与完整人工按钮链路。完整恢复、统一服务端授权、搜索/变体重构、流式体验未验收。没有上传 GitHub。PyInstaller tzdata 缺失与既有 Vite/PostCSS 构建警告仍保留。
