<div align="center">

# Kimi WebBridge Pro

**面向本地 AI Agent 的真实浏览器控制 skill，强调隐私最小化和标签页安全**

[![Agent Skill](https://img.shields.io/badge/Agent-Skill-black.svg)](skill/SKILL.md)
[![GitHub](https://img.shields.io/badge/GitHub-yang12535%2Fkimi--webbridge--pro-181717.svg)](https://github.com/yang12535/kimi-webbridge-pro)
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
>
> 项目源码与问题反馈：https://github.com/yang12535/kimi-webbridge-pro

## 主要增强

| 能力 | 说明 |
|---|---|
| Windows 原生 helper | 使用 PowerShell 对象构造 UTF-8 JSON，避免命令行转义问题 |
| UTF-8 复杂参数 | PowerShell 支持 JSON 文件；Bash 还可从 stdin 直接读取中文、emoji 和嵌套参数 |
| Bash 调用 helper | 无 `jq` 依赖，支持从 UTF-8 文件或 stdin 读取中文和复杂参数 |
| Snapshot 控制 | 支持自动策略、精简 UI 摘要，或把完整快照写入临时文件 |
| Doctor 自检 | 检查 daemon binary、status、端口、PID 文件和扩展连接，可短轮询等待连接，并输出 JSON reason |
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
curl -fsSL https://cdn.kimi.com/webbridge/install.sh | bash -s -- --no-skill
```

执行远程安装脚本前，请确认域名和脚本来源符合你的安全要求。
官方 POSIX installer 默认还会安装旧的 `kimi-webbridge` skill。准备单独安装本 Pro
skill 时使用 `--no-skill`，避免同一 skills 目录中两个 skill 并存后 Agent 选错。
这不会删除已经存在的官方 skill；是否保留应由用户明确决定。

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

### 3. 自检

在发送浏览器动作前，先确认 daemon 和扩展都已就绪：

Windows：

```powershell
py -3 .\kimi-webbridge-pro\skill\scripts\doctor.py --wait-connected 20
```

Linux / macOS：

```bash
python3 ./kimi-webbridge-pro/skill/scripts/doctor.py --wait-connected 20
```

`doctor.py` 默认不启动 daemon，也不发送浏览器动作。只有显式传入 `--start` 时才会尝试启动 daemon。
它也会报告同一 skills 根目录内的确定冲突；若两个 skill 位于不同的已知根目录，则给出
条件式提醒，由用户判断当前 Agent 是否同时加载这两个根目录。

Linux 用户可在安装当前 v2 daemon 后选择启用无 root 的登录自启动：

```bash
# 先只查看将要安装的 unit
./kimi-webbridge-pro/skill/scripts/install_linux_autostart.sh --print-unit

# 安装、启用并启动 systemd user service
./kimi-webbridge-pro/skill/scripts/install_linux_autostart.sh
```

该 helper 需要 `systemctl`、`flock` 和 Python 3，会拒绝不支持 `start --foreground` 的旧 daemon；
如果检测到直接启动的 daemon 仍在运行，它会保持现状并要求先显式停止，避免误杀复用 PID；
如果其他 systemd 搜索路径已加载同名 unit，它也会拒绝用用户配置静默遮蔽；
安装或卸载失败时会尝试恢复原 unit 以及先前的启用/运行状态，并在恢复不完整时警告；详见
[`operations.md`](skill/references/operations.md)。

### 4. 调用

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
    ├── examples/
    │   ├── login_and_fill_form.md
    │   ├── scroll_and_extract.md
    │   ├── handle_popup.md
    │   └── network_debug.md
    ├── references/
    │   ├── protocol.md
    │   ├── operations.md
    │   └── how-it-works.md
    └── scripts/
        ├── invoke.ps1
        ├── invoke.sh
        ├── install_linux_autostart.sh
        ├── doctor.py
        ├── screenshot.py
        ├── snapshot.py
        ├── wait_for.py
        ├── webbridge_client.py
        └── screenshot.ps1
└── tests/
    ├── test_doctor.py
    ├── test_snapshot.py
    └── test_wait_for.py
```

- `SKILL.md`：Agent 正常执行时读取的操作手册
- `examples/`：按需读取的端到端工作流样例
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
py -3 .\skill\scripts\snapshot.py --session demo --auto
py -3 .\skill\scripts\snapshot.py --session demo --mode compact

# 完整快照保存到指定文件；--path/--file 也是 --output 的别名
py -3 .\skill\scripts\snapshot.py --session demo --mode file --output .\snapshot.json
```

Linux / macOS：

```bash
# 精简输出，适合定位输入框、按钮和链接
python3 ./skill/scripts/snapshot.py --session demo --auto
python3 ./skill/scripts/snapshot.py --session demo --mode compact

# 完整快照保存到指定文件；--path/--file 也是 --output 的别名
python3 ./skill/scripts/snapshot.py --session demo --mode file --output ./snapshot.json
```

Windows 应使用 `py -3` 或 `py` 启动 Python，不要假定存在 `python3` 命令。

Doctor 自检：

```powershell
py -3 .\skill\scripts\doctor.py --wait-connected 20
```

跨平台截图与等待：

```powershell
py -3 .\skill\scripts\screenshot.py --session demo
py -3 .\skill\scripts\wait_for.py --session demo `
  --url-contains "example.com" --timeout 10
py -3 .\skill\scripts\wait_for.py --session demo `
  --visible-text "已保存" --timeout 10
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
- Python helpers 需要 Python 3；Bash helper 需要 Bash、curl 和 Python 3（用于 UTF-8/BOM 与 JSON object 预校验）
- 合成点击和输入无法满足要求 `event.isTrusted` 的网站
- 顶层页面操作不能直接访问跨域 iframe 内容
- 浏览器可能拦截站点尝试打开的弹窗或新标签页
- `find_tab` 选择的是 WebBridge session 内的目标，不保证切换浏览器可见焦点；独立标签页应使用独立 session
- `find_tab active:true` 不能配合 `https://*/*` 可靠发现未知的当前标签页；应提供已知 URL/域名并核对快照
- `fill` 对 `contenteditable` 仍是纯文本替换，不提供粗体、斜体或范围级富文本语义
- 已检查的扩展 1.11.6 仍可能因选择错误的原生 setter 而无法填写 framework-controlled textarea；根修复在上游，受限 fallback 见 `protocol.md`
- `navigate` 的 30 秒加载等待、超时后是否返回/登记 `tabId` 由上游 daemon/扩展决定；helpers 预留 45 秒仅用于完整接收其结果
- `upload` 的 CDP `-32000 Not allowed` 需要先对齐 daemon/扩展版本；同版本仍失败属于上游能力限制
- `mouse_click`、`key_type`、`send_keys` 和通用 `cdp` 取决于 daemon/扩展版本，其中 `cdp` 属于高权限高级能力
- daemon 和扩展升级后，响应协议可能发生变化，需要重新实测

## 贡献

提交修改前请保持以下分层：

1. 脚本只保留帮助理解意图的最小注释
2. `SKILL.md` 只写 Agent 必须执行的步骤和常见问题
3. 协议细节进入 `protocol.md`
4. 生命周期与恢复流程进入 `operations.md`
5. 原理和设计原因进入 `how-it-works.md`

涉及 daemon 协议的改动应通过真实请求验证，不能只依据旧文档推断。
