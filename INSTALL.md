# 安装指南

本文档说明从零开始运行 Loki 幽灵桌面宠物所需的全部组件、安装步骤与常见问题。

## 一、环境要求

| 组件 | 要求 | 说明 |
|---|---|---|
| 操作系统 | Windows 10+ / macOS 11+ | 均已支持透明置顶窗口 |
| Python | 3.10 及以上 | 开发验证环境为 Python 3.14 |
| pip | 随 Python 附带 | 建议先升级: `python -m pip install --upgrade pip` |
| 网络 | 对话与语音朗读需要联网 | 语音使用微软 edge-tts 在线接口 |

检查 Python 是否可用:

```bash
python --version
```

## 二、依赖组件

| 包 | 用途 | 验证版本 |
|---|---|---|
| `PySide6` | Qt 界面框架:窗口、动画、聊天面板,及 QtMultimedia 语音播放 | 6.11.1 |
| `requests` | 调用 OpenAI 兼容对话接口 | 2.32.5 |
| `edge-tts` | 微软神经网络语音合成(免费,无需 API key) | 7.2.8 |
| `opencv-python` | 表情工坊:读取视频帧、去背景抠图 | 5.0.0 |
| `numpy` | 表情工坊:图像矩阵运算 | 2.5.0 |

可选组件(按需):

| 组件 | 用途 | 安装 |
|---|---|---|
| Node.js 18+ | 离开模式邮件审批的前置 | https://nodejs.org |
| `@tencent-qqmail/agently-cli` | 离开模式:发授权邮件、读回复 | `npm install -g @tencent-qqmail/agently-cli`,然后 `agently-cli auth login` 完成 OAuth(免密钥) |
| Claude Code | 授权联动 / skill 化 / cli 聊天后端的宿主 | https://claude.com/claude-code |

一键安装:

```bash
pip install -r requirements.txt
```

或手动安装:

```bash
pip install PySide6 requests edge-tts
```

国内网络较慢时可用镜像源:

```bash
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

> 语音播放使用 PySide6 自带的 QtMultimedia 模块,无需额外安装播放器。

## 三、项目文件

```
loki-pet/
├── pet.py             # 主程序
├── emote_studio.py    # 表情工坊: 视频转透明动态表情 + 管理面板
├── config.json        # 配置文件(首次运行自动生成)
├── requirements.txt   # 依赖清单
├── install_skill.ps1  # 安装/同步为 Agent Skill
├── skill/             # skill 定义源文件(SKILL.md + skill 版默认配置)
├── assets/
│   ├── loki.png       # 静态角色图(必需,缺失时程序会退出并提示)
│   ├── *.mp4          # 表情源视频(可选)
│   └── emotes/        # 已导入的动态表情(每个表情一个目录,含帧序列 + meta.json)
├── README.md
├── INSTALL.md
└── CHANGELOG.md
```

## 四、配置

首次运行 `python pet.py` 会自动生成 `config.json`,然后填入你的 API 信息(OpenAI 兼容格式,DeepSeek / Kimi / Qwen / 中转站均可):

```json
{
  "api_base": "https://api.deepseek.com/v1",
  "api_key": "sk-xxxx",
  "model": "deepseek-chat"
}
```

各配置项含义见 [README.md](README.md#配置)。语音朗读默认开启,不需要任何 key。

## 五、启动与验证

```bash
cd loki-pet
python pet.py
```

逐项验证:

1. **界面**:屏幕右下角出现漂浮的幽灵,可拖拽
2. **对话**:单击幽灵打开聊天框,输入文字回车,Loki 回复(需 config.json 中 API 信息正确)
3. **语音**:Loki 回复的同时朗读出声(需联网;右键菜单可开关)
4. **动态表情**:config.json 中 `emote` 非空时角色为动画;右键 → 表情工坊可导入/切换

单独验证语音组件是否正常:

```bash
python -c "import asyncio, edge_tts; asyncio.run(edge_tts.Communicate('测试', 'zh-CN-YunxiNeural').save('test.mp3'))"
```

生成 `test.mp3` 即为正常。

## 六、常见问题

**Q: pip 安装时提示 "scripts ... are installed in '...' which is not on PATH"**
仅影响命令行直接调用 `pyside6-*`、`edge-tts` 等工具,不影响本项目运行,可忽略。

**Q: 聊天框显示"(请求失败: …)"**
检查 `config.json` 的 `api_base`、`api_key`、`model` 是否正确,以及网络是否可达。

**Q: 聊天框显示"(语音合成失败: …)"**
edge-tts 需要联网访问微软接口。程序已内置一次自动重试,若持续失败请检查网络或代理设置。回复只含标点/表情时会自动跳过朗读,不会报错。

**Q: 有声音文件但播放无声**
检查系统音量与默认输出设备;QtMultimedia 在 Windows 上使用系统解码器,Windows 10 及以上自带 mp3 解码,无需额外安装。

**Q: 启动提示"缺少角色图"**
确认 `assets/loki.png` 存在。

## 七、安装为 Agent Skill(可选)

```powershell
powershell -ExecutionPolicy Bypass -File install_skill.ps1 -WithEmotes
```

安装到 `~/.claude/skills/loki-pet/`,Claude Code 等支持 Agent Skills 的工具即可直接调度本宠物。skill 版聊天默认走宿主 agent CLI(宿主 agent 账号额度),无需 API key;要求宿主 CLI 已登录。安装在 `.codex/skills/` 下且仍是旧默认 `claude -p` 时,启动会自动迁移为 `codex exec` + `gpt5.4mini`。详见 README「作为 Agent Skill 使用」。

## 八、配置 Claude Code 授权联动 hooks(可选)

在 `~/.claude/settings.json` 的 `hooks` 中加入以下四项(把 `<SKILL_DIR>` 替换为
skill 安装路径,如 Windows 的 `C:\\Users\\你的用户名\\.claude\\skills\\loki-pet`):

```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Bash|PowerShell",
      "hooks": [{ "type": "command", "command": "python",
                  "args": ["<SKILL_DIR>\\hook_bridge.py", "--event", "pretooluse"],
                  "timeout": 10 }]
    }],
    "PermissionRequest": [{
      "hooks": [{ "type": "command", "command": "python",
                  "args": ["<SKILL_DIR>\\hook_bridge.py", "--event", "permissionrequest"],
                  "timeout": 920, "statusMessage": "等待 Loki 宠物端授权…" }]
    }],
    "Notification": [{
      "hooks": [{ "type": "command", "command": "python",
                  "args": ["<SKILL_DIR>\\hook_bridge.py", "--event", "notification"],
                  "timeout": 10, "async": true }]
    }],
    "Stop": [{
      "hooks": [{ "type": "command", "command": "python",
                  "args": ["<SKILL_DIR>\\hook_bridge.py", "--event", "stop"],
                  "timeout": 10, "async": true }]
    }],
    "UserPromptSubmit": [{
      "hooks": [{ "type": "command", "command": "python",
                  "args": ["<SKILL_DIR>\\hook_bridge.py", "--event", "promptsubmit"],
                  "timeout": 10, "async": true }]
    }],
    "PostCompact": [{
      "hooks": [{ "type": "command", "command": "python",
                  "args": ["<SKILL_DIR>\\hook_bridge.py", "--event", "postcompact"],
                  "timeout": 15, "async": true }]
    }],
    "SessionEnd": [{
      "hooks": [{ "type": "command", "command": "python",
                  "args": ["<SKILL_DIR>\\hook_bridge.py", "--event", "sessionend"],
                  "timeout": 15, "async": true }]
    }]
  }
}
```

PostCompact / SessionEnd 用于"会话断点档案":压缩或会话结束时自动存交接快照到
`~/.loki-pet/handoffs/`,配合宠物聊天框的 `/resume` 一键轻量续接。

UserPromptSubmit 用于记录每轮开始时间,让"任务完成"通知只在长任务(默认 ≥120 秒,
`stop_notify_min_seconds` 可调)时触发;不配置它则每轮结束都会通知。

说明:PermissionRequest 的 920 秒超时是为离开模式的邮件审批预留(最长等 15 分钟);
宠物未运行时所有 hook 会立即静默返回,不影响正常使用。

## 九、配置 Codex 授权联动 hooks(可选)

Codex 使用独立的 `~/.codex/hooks.json`,不会覆盖 Claude 的
`~/.claude/settings.json`。运行:

```powershell
python install_codex_hooks.py
```

脚本会把 PermissionRequest / UserPromptSubmit / PostCompact / Stop 四类 Codex
hooks 合并进 `~/.codex/hooks.json`,入口为 `codex_hook_bridge.py`,通信仍走
`~/.loki-pet/` 文件队列。已有 Codex hooks 会保留,不会被删除。

安装后在 Codex 里执行 `/hooks`,审核并 trust 新增的 Loki hooks。未 trust 前,
Codex 会跳过非托管 hook,宠物不会弹授权按钮。

Codex hooks 生效后:

- 授权等待时宠物会显示 Codex 来源并语音提示"你的 Codex 在找你"。
- Stop hook 只在整轮长任务完成后通知并播放音效,文案为"Codex 任务完成啦!"。
- 右键菜单"聊天模型(宿主后端)"会显示 `GPT-5.4 Mini(最省)` / `跟随宿主默认`。

## 十、打包成独立应用(可选)

```bash
pip install pyinstaller
pyinstaller --windowed --onefile --add-data "assets:assets" pet.py
```

- Windows 产出 `dist/pet.exe`,macOS 产出 `.app`
- `config.json` 需与可执行文件放在同一目录
- 打包不包含语音缓存,首次朗读仍需联网
