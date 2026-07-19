# ModAgent

ModAgent 是一个面向 PC 游戏的开源 AI Mod 管理器，帮助用户搜索、识别、安装、管理和回滚游戏 Mod。

本仓库仅包含 **ModAgent 普通版**。订阅版的专属主题、音效、动效、壁纸与商业素材不包含在本仓库中，也不属于 GPL 开源范围。

## 主要功能

- 通过对话描述 Mod 需求
- 聚合 Nexus Mods、GitHub、Steam Workshop、Thunderstore、GameBanana 等来源
- 下载并安装受支持的 Mod
- 扫描现有 Mod
- 创建、预览与恢复快照
- 启用、禁用及卸载 Mod
- 检查前置依赖与陈旧风险
- 本地保存配置、对话和 Mod 管理记录

实际支持能力取决于游戏、Mod 类型、来源网站与当前版本。安装前请阅读应用内的风险提示，并为重要存档保留备份。

## 系统要求

- Windows 10/11 x64
- 当前 v1.0 仅提供中文界面与中文交互
- Python 3.10 或更高版本（仅源码运行需要）
- Node.js 18 或更高版本（仅前端开发与打包需要）
- 使用在线搜索、Mod 来源和 AI 模型时需要网络连接

## 必需的 API Key

ModAgent 普通版不内置共享密钥。用户需要在“设置”中填写自己的 API Key：

| API Key | 用途 | 缺少时的影响 |
|---|---|---|
| Nexus Mods API Key | 查询 Nexus Mods、读取文件和版本信息、执行 Nexus 下载流程 | 无法完整使用 Nexus Mods 来源 |
| Tavily Search API Key | 搜索 GitHub、Steam Workshop、GameBanana 及其他网页来源，补充跨站推荐信息 | 跨网站搜索与综合推荐能力明显受限 |
| DeepSeek API Key | 驱动中文对话、需求理解、计划生成和工具调用 | 无法使用 AI 对话与自动规划 |

API Key 分别由对应服务提供，相关额度、费用、地区可用性和服务条款由服务提供方决定。

### 当前模型与语言支持

- 当前官方验证并支持的模型服务：**DeepSeek**
- 当前产品语言：**简体中文**
- 设置页中可能出现兼容 OpenAI 接口格式的实验性模型选项，但 v1.0 不承诺其完整可用性
- 英文界面、其他模型服务和免配置托管能力属于后续规划

因此，当前版本更准确的定位是：**由用户提供 API Key 的中文 AI Mod 管理器**，并非无需配置即可使用的在线服务。

## 从源码运行

安装 Python 依赖：

```powershell
python -m pip install -r requirements.txt
```

安装前端依赖：

```powershell
cd electron
npm install
```
## 普通用户下载

普通用户请从 GitHub 仓库右侧的 **Releases** 下载 `ModAgent-Setup-*.exe` 安装程序。

GitHub 自动提供的 **Source code (zip)** 只包含约数 MB 的源代码，不能解压后直接运行 ModAgent。完整 Windows 安装程序包含 Electron、Python 后端和运行依赖，体积会明显更大。

暂未发布 Release 时，表示当前版本仍在封闭测试阶段。


开发模式运行：

```powershell
npm run dev:full
```

## 构建 Windows 安装包

```powershell
cd electron
npm run dist:win
```

构建过程会生成 Python 后端与 Electron 安装程序。生成结果不会提交到源码仓库。

## 隐私与安全

- API 密钥通过 Windows DPAPI 加密保存在本机。
- ModAgent 不包含项目方自建的遥测上传。
- 使用 AI 模型、搜索服务或 Mod 来源时，必要请求会发送到用户选择的第三方服务。
- 诊断文件仅在用户主动导出后由用户自行提供。

详见 [隐私说明](PRIVACY.md) 与 [第三方 Mod 和网站免责声明](THIRD-PARTY-MODS-DISCLAIMER.md)。

## 许可证

ModAgent 普通版以 **GNU GPL v3.0 only** 发布，详见 [LICENSE.md](LICENSE.md) 与 [LICENSE-GPL-3.0.txt](LICENSE-GPL-3.0.txt)。

第三方组件仍受各自许可证约束，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 联系

问题反馈、权利投诉与公开联系：`3387454098@qq.com`
我的支持频道:https://afdian.com/a/catgirl_creator
