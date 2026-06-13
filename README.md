<div align="center">

# Kimi WebBridge Pro

**面向本地 AI Agent 的真实浏览器控制 skill，强调隐私最小化和标签页安全**

[![Agent Skill](https://img.shields.io/badge/Agent-Skill-black.svg)](skill/SKILL.md)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-blue.svg)](#快速开始)
[![Privacy](https://img.shields.io/badge/Privacy-Minimized-green.svg)](#隐私与安全)

</div>

---

## 简介

Kimi WebBridge Pro 是一个独立的 Agent skill，通过本机 Kimi WebBridge daemon
控制用户真实、已登录的浏览器。

只要 Agent 能读取 Agent Skill 指令，并能执行本地 shell 或 HTTP 请求，就可以使用
核心工作流。仓库额外提供 OpenAI/Codex 元数据，但核心协议和操作说明不依赖某个
特定 Agent 产品。

它适合需要使用现有标签页、Cookie 会话或浏览器扩展状态的任务，例如：

- 阅读用户已经登录的网站
- 在现有标签页中搜索、点击和填写内容
- 保存页面截图或 PDF
- 排查点击后页面没有变化、后台标签页或弹窗拦截

本项目不是搜索引擎，也不包含浏览器驱动。它依赖 Kimi WebBridge daemon 和浏览器
扩展，并在官方 skill 的基础上补充跨 Agent 工作流约束。

> 本项目是社区维护的非官方项目，与 Moonshot AI、Kimi 或 OpenAI 无隶属或背书关系。

## 主要增强

| 能力 | 说明 |
|---|---|
| Windows 原生 helper | 使用 PowerShell 对象构造 UTF-8 JSON，避免命令行转义问题 |
| Bash 调用 helper | 无 `jq` 依赖，支持从 UTF-8 JSON 文件读取中文和复杂参数 |
| Snapshot 控制 | 可输出精简 UI 摘要，或把完整快照写入临时文件 |
| 跨平台截图 | Python helper 兼容 daemon 路径响应和旧版 base64 响应 |
| 智能等待 | 按 URL、标题或可访问性文本轮询，不重复原始点击 |
| 标签页所有权 | 区分用户原有标签页和任务新建标签页，避免误关页面 |
| 弹窗诊断 | 页面无变化时依次检查 SPA、后台标签页和浏览器弹窗拦截 |
| 隐私最小化 | 限制 Cookie、认证头、浏览器存储和无关私人内容的读取 |
| 分层文档 | Agent 操作说明、协议参考、故障恢复和人类原理文档彼此分离 |

## 快速开始

### 1. 安装 Kimi WebBridge

使用本 skill 前需要同时安装本地 daemon 和浏览器扩展：

- [Kimi WebBridge 中文官方说明与 daemon 安装](https://www.kimi.com/zh-cn/features/webbridge)
- [Chrome Web Store：Kimi WebBridge 扩展](https://chromewebstore.google.com/detail/kimi-webbridge/fldmhceldgbpfpkbgopacenieobmligc?pli=1)

Windows 官方安装命令：

```powershell
irm https://cdn.kimi.com/webbridge/install.ps1 | iex
```

POSIX 官方安装命令：

```bash
curl -fsSL https://cdn.kimi.com/webbridge/install.sh | bash
```

执行远程安装脚本前，请确认域名和脚本来源符合你的安全要求。

### 2. 安装 skill

将仓库中的 `skill/` 目录复制到你的 Agent 所使用的 skills 目录，并保持目录名为
`kimi-webbridge-pro`。不同 Agent 的 skills 路径和重载方式不同，请以对应 Agent
文档为准。

通用结构：

```text
<agent-skills-directory>/
└── kimi-webbridge-pro/
    ├── SKILL.md
    ├── agents/
    ├── references/
    └── scripts/
```

#### Codex 安装示例

Windows：

```powershell
git clone https://github.com/yang12535/kimi-webbridge-pro.git
$target = "$env:USERPROFILE\.codex\skills\kimi-webbridge-pro"
New-Item -ItemType Directory -Path $target -Force | Out-Null
Copy-Item ".\kimi-webbridge-pro\skill\*" -Destination $target -Recurse -Force
```

Linux / macOS：

```bash
git clone https://github.com/yang12535/kimi-webbridge-pro.git
mkdir -p ~/.codex/skills/kimi-webbridge-pro
cp -R kimi-webbridge-pro/skill/. ~/.codex/skills/kimi-webbridge-pro/
```

重新启动 Agent 或打开新会话，使 skill 列表重新加载。

### 3. 调用

```text
使用 $kimi-webbridge-pro 查看我当前登录的网页。
```

```text
使用 $kimi-webbridge-pro 在我打开的知乎页面搜索 OpenAI。
```

```text
使用 $kimi-webbridge-pro 截取当前页面，并在完成后删除临时文件。
```

## 隐私与安全

这个 skill 能访问真实登录态，因此应按高权限工具对待。

### 数据流

```text
Local AI agent
    |
    | HTTP JSON
    v
127.0.0.1:10086 daemon
    |
    v
浏览器扩展和真实标签页
```

仓库中的 helper：

- 只向配置的 daemon 地址发送命令，默认是 `127.0.0.1:10086`
- 不保存 Cookie、密码、认证令牌或浏览器存储
- 不包含遥测或第三方分析代码
- 截图默认使用临时目录或 daemon 返回的本地路径

但是，本地 daemon 不等于数据永远只停留在本机。页面 snapshot、截图内容、PDF 或网络
结果一旦返回给 agent，就会进入当前 AI 会话的处理范围。

### 默认隐私规则

- 只读取完成任务所需的最少页面内容
- 不读取或返回 Cookie、Authorization、session token、密码字段或浏览器存储
- `network` 仅用于用户确实需要的请求级诊断
- 不采集 `Cookie`、`Set-Cookie`、`Authorization` 或带令牌的请求体
- 临时截图和 PDF 在任务完成后删除，除非用户明确要求保留
- 上传、发送、发布、购买、删除和权限变更前需要确认
- 不绕过验证码、付费墙、年龄限制、浏览器警告或网站安全机制

Kimi WebBridge daemon 和浏览器扩展是外部依赖，其自身的数据处理行为不由本仓库控制。
安装和使用前应自行审阅对应产品的隐私政策与实现。

## 项目结构

```text
kimi-webbridge-pro/
├── README.md
├── .gitignore
├── .gitattributes
├── skill/
    ├── SKILL.md
    ├── agents/
    │   └── openai.yaml       # 可选的 OpenAI/Codex UI 元数据
    ├── references/
    │   ├── protocol.md
    │   ├── operations.md
    │   └── how-it-works.md
    └── scripts/
        ├── invoke.ps1
        ├── invoke.sh
        ├── screenshot.py
        ├── snapshot.py
        ├── wait_for.py
        ├── webbridge_client.py
        └── screenshot.ps1
└── tests/
    └── test_snapshot.py
```

- `SKILL.md`：Agent 正常执行时读取的操作手册
- `protocol.md`：动作参数、响应和隐私约束
- `operations.md`：安装、状态检查和 daemon 故障恢复
- `how-it-works.md`：面向人类维护者的原理说明，内容较长，不推荐 Agent 日常加载

## 验证

通用检查包括 frontmatter、相对链接和脚本语法。若本机安装了 Codex 的
`skill-creator`，还可以使用其校验器：

```powershell
py -3 "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py" .\skill
```

PowerShell 语法检查：

```powershell
Get-ChildItem .\skill\scripts -Filter *.ps1 | ForEach-Object {
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        $_.FullName,
        [ref]$null,
        [ref]$errors
    ) | Out-Null
    if ($errors.Count) { throw $errors }
}
```

无副作用的 daemon 冒烟测试：

```powershell
& .\skill\scripts\invoke.ps1 `
    -Session "kimi-webbridge-pro-smoke" `
    -Action "list_tabs"
```

Bash 调用：

```bash
./skill/scripts/invoke.sh \
  --session kimi-webbridge-pro-smoke \
  --action list_tabs
```

大型页面快照：

Windows：

```powershell
# 精简输出，适合定位输入框、按钮和链接
py -3 .\skill\scripts\snapshot.py --session demo --mode compact

# 完整快照保存到临时文件，仅返回文件路径
py -3 .\skill\scripts\snapshot.py --session demo --mode file
```

Linux / macOS：

```bash
# 精简输出，适合定位输入框、按钮和链接
python3 ./skill/scripts/snapshot.py --session demo --mode compact

# 完整快照保存到临时文件，仅返回文件路径
python3 ./skill/scripts/snapshot.py --session demo --mode file
```

Windows 应使用 `py -3` 或 `py` 启动 Python，不要假定存在 `python3` 命令。

跨平台截图与等待：

```powershell
py -3 .\skill\scripts\screenshot.py --session demo
py -3 .\skill\scripts\wait_for.py --session demo `
  --url-contains "example.com" --timeout 10
```

回归测试：

```powershell
py -3 -m unittest discover -s tests -v
```

### Agent 实测

- [Kimi K2.7 Code：知乎搜索、文章阅读、截图与修复后二次验收](https://github.com/yang12535/kimi-webbridge-pro/issues/1)

该评价来自 Kimi K2.7 Code 对真实浏览器工作流的端到端测试，不代表 Moonshot AI 的
官方背书。

## 已知限制

- PowerShell helper 目前以 Windows 为主；协议本身可在其他平台通过 HTTP 调用
- `snapshot.py` 需要 Python 3，Bash helper 需要 Bash 和 curl
- 合成点击和输入无法满足要求 `event.isTrusted` 的网站
- 顶层页面操作不能直接访问跨域 iframe 内容
- 浏览器可能拦截站点尝试打开的弹窗或新标签页
- daemon 和扩展升级后，响应协议可能发生变化，需要重新实测

## 贡献

提交修改前请保持以下分层：

1. 脚本只保留帮助理解意图的最小注释
2. `SKILL.md` 只写 Agent 必须执行的步骤和常见问题
3. 协议细节进入 `protocol.md`
4. 生命周期与恢复流程进入 `operations.md`
5. 原理和设计原因进入 `how-it-works.md`

涉及 daemon 协议的改动应通过真实请求验证，不能只依据旧文档推断。
