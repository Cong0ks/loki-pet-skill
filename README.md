# Loki 幽灵桌面宠物

跨平台(Windows / macOS)桌面 AI 宠物:漂浮、拖拽、点击对话、语音朗读。

## 功能

- 幽灵透明置顶,正弦上下漂浮
- 左键拖拽移动,单击打开聊天框
- AI 对话(OpenAI 兼容接口,DeepSeek / Kimi / Qwen / 中转站均可)
- 回复自动语音朗读(edge-tts 免费微软神经网络语音,无需 API key)
- 动态表情:视频一键转透明背景帧动画,内置"表情工坊"面板管理
- 可打包为 Agent Skill:聊天直接调用宿主 agent 的 CLI(如 `claude -p`),无需配置 API key
- Claude Code 授权联动:权限请求转发到宠物,点按钮帮你按 Yes,支持 15 分钟临时授权
- 任务完成通知:弹泡泡 + 播放自定义音效(BGM)
- 离开模式:授权请求转发邮件,回复 yes/no/15min 远程审批(腾讯 Agent Mail,可选)

## 文档导航

- **[USAGE.md](USAGE.md)** — 新手教程:每个功能"什么时候用+怎么操作",强烈建议先读
- **[INSTALL.md](INSTALL.md)** — 安装:环境要求、依赖、hooks 配置、常见问题
- **[CHANGELOG.md](CHANGELOG.md)** — 版本记录

## 安装

完整安装步骤(含环境要求与常见问题)见 [INSTALL.md](INSTALL.md),快速安装:

```bash
pip install -r requirements.txt
```

## 配置

首次运行会生成 `config.json`,填入你的 API 信息:

```json
{
  "api_base": "https://api.deepseek.com/v1",
  "api_key": "sk-xxxx",
  "model": "deepseek-chat",
  "system_prompt": "你是 Loki,一只坏笑的小幽灵……",
  "pet_width": 180,
  "max_history": 20,
  "tts_enabled": true,
  "tts_voice": "zh-CN-YunxiNeural"
}
```

| 配置项 | 说明 |
|---|---|
| `backend` | 对话后端: `cli`(skill 版默认,走宿主 agent 额度) / `api`(自备便宜接口如 DeepSeek,与宿主流量完全分开);右键菜单"对话后端"可随时切换,即时生效 |
| `cli_command` | cli 后端使用的命令,默认 `claude -p`(可换 `codex exec` 等) |
| `cli_model` | cli 后端聊天模型:`haiku`/`sonnet`(默认)/`opus`,空串跟随宿主;闲聊用便宜模型省额度,右键菜单可切换 |
| `api_base` / `api_key` / `model` | OpenAI 兼容接口信息(api 后端必填) |
| `system_prompt` | Loki 的人设提示词 |
| `pet_width` | 宠物显示宽度(像素) |
| `max_history` | 对话保留的历史条数 |
| `tts_enabled` | 是否开启语音朗读(也可通过右键菜单切换) |
| `tts_voice` | 朗读音色,完整列表: `python -m edge_tts --list-voices` |
| `emote` | 当前使用的动态表情名,空串为静态图片(通过表情工坊设置) |
| `emote_shuffle` / `emote_shuffle_minutes` | 表情随机轮播开关与间隔分钟数(在表情工坊面板设置),多表情时定时随机换装 |
| `stop_sound` | Claude 任务完成时播放的音效路径(默认自带捷报 BGM,空串关闭;换音乐见 [assets/sounds/README.md](assets/sounds/README.md)) |
| `notify_email` | 离开模式通知邮箱(首次开启弹框填写,聊天框 `/email 新地址` 可改) |
| `risk_notes` | 授权风险注解开关(默认开) |
| `chat_width` / `chat_height` | 聊天框尺寸,拖拽右下角手柄调整后自动记住 |
| `stop_notify_min_seconds` | 任务完成通知阈值(秒,默认 120):本轮耗时低于该值不通知 |
| `memory_enabled` | 轻量记忆开关(默认开):每 10 轮对话提炼一次"关于主人的事实+近况",注入人设;`/memory` 管理 |

常用中文音色: `zh-CN-YunxiNeural`(少年音,默认)、`zh-CN-XiaoxiaoNeural`(温柔女声)、`zh-CN-XiaoyiNeural`(活泼女声)。

## 运行

```bash
python pet.py
```

## 操作

| 操作 | 效果 |
|---|---|
| 左键拖拽 | 移动宠物(松手后在新位置继续漂浮) |
| 左键单击 | 打开/关闭聊天框 |
| 拖聊天框右下角 | 自由调整聊天框大小(自动记住) |
| 右键 | 菜单 → 表情工坊 / 自动帮按 Yes / 离开模式 / 语音朗读开关 / 退出 |
| 聊天框 `/email` | 查看/修改离开模式通知邮箱(本地命令,不发给 AI) |
| 聊天框 `/api` | 查看/配置自定义 API:`/api 你的key [接口地址] [模型名]`,只给 key 默认 DeepSeek |
| 聊天框 `/task` | 计划任务:到点提醒或让宿主续跑(见"计划任务"章节) |
| 聊天框 `/face` | 打开表情工坊 |
| 聊天框 `/memory` | 查看记忆 / `forget 关键词` 删除 / `clear` 清空 |
| 聊天框 `/resume` | 断点档案列表 / `1` 轻量续接 / `clear` 清空档案 |

## 表情工坊(视频转动态表情)

右键菜单 → **表情工坊…**,或命令行 `python emote_studio.py <视频> [表情名]`。

- 选择一段角色视频(mp4/mov/avi/webm/mkv),起个名字,点"转换并导入"
- 自动逐帧去除纯色背景,生成透明 PNG 帧序列(原分辨率,清晰度无损),完成后立即生效
- 面板中可预览(棋盘格显示透明区域)、切换表情、恢复静态图片、删除表情
- 聊天框输入 `/face` 也可打开工坊;面板左下角"随机轮播"勾选后,每隔 N 分钟(可调)从已导入表情随机换装
- 帧文件存放在 `assets/emotes/<表情名>/`,含 `meta.json`(帧率信息)

抠图原理:以画面边界颜色为背景色,只去除与边界连通的背景区域——角色内部
与背景同色的部分(如白发白衣)有描边隔开,会完整保留。因此**视频需要纯色
背景且角色有闭合轮廓**(AI 生成的角色视频通常都满足)。

## 语音朗读说明

- 使用 [edge-tts](https://pypi.org/project/edge-tts/)(微软 Edge "大声朗读"接口),免费、无需注册,但需要联网
- 朗读前会自动过滤 markdown 符号和括号内的动作描写(如"(坏笑)"不会被念出)
- 回复只含标点或表情时自动跳过朗读;合成失败会自动重试一次,仍失败才在聊天框提示
- 右键菜单的语音开关状态会保存到 `config.json`

## 验收清单

- [x] 幽灵透明置顶,上下正弦漂浮
- [x] 拖拽流畅,松手后位置保留
- [x] 单击弹出聊天框,回车发送,Loki 按人设回复
- [x] API 出错时聊天框内显示错误信息而非崩溃
- [x] 右键可退出
- [x] 回复自动语音朗读,可通过右键菜单开关
- [x] 视频一键转透明动态表情,循环播放且可随时切换

## 作为 Agent Skill 使用

把整个宠物打包成 [Agent Skills](https://code.claude.com/docs/en/skills) 标准格式,任何支持该标准的 agent(Claude Code 等)都能直接调度它:

```powershell
powershell -ExecutionPolicy Bypass -File install_skill.ps1            # 安装/同步代码
powershell -ExecutionPolicy Bypass -File install_skill.ps1 -WithEmotes  # 连同已转换的表情
```

安装到 `~/.claude/skills/loki-pet/` 后,在 agent 会话里说"启动桌宠""帮我把这个视频转成表情"即可。skill 版默认 `backend: cli`——聊天通过 `claude -p` 走宿主 agent 的登录账号额度,**不需要单独配置任何 API key**;宿主不是 Claude Code 时改 `cli_command` 为对应命令(如 `codex exec`)。skill 定义源文件在 `skill/` 目录。

## Claude Code 授权联动(帮按 Yes)

通过 hooks 把 Claude Code 的权限请求/通知转发给宠物(桥接脚本 `hook_bridge.py`,通信走 `~/.loki-pet/` 文件队列):

- **弹授权提示时**:宠物弹出请求详情 + 语音提醒,聊天框出现四个按钮——`允许` / `Yes 15分钟` / `拒绝` / `忽略`;**5 分钟**内没点则静默回落到终端授权,宠物端按钮悄悄收起(不弹打扰性提示),之后去终端处理即可
- **风险小注解** 🔎:每条授权请求会由便宜模型(宿主后端固定用 Haiku)自动生成一句人话说明——"这条命令会做什么 + [低/中/高风险]",看不懂命令也能放心决策;离席邮件里同样附带。`risk_notes: false` 可关闭
- **临时授权**:点 `Yes 15分钟` 或右键菜单"自动帮按 Yes",15 分钟内所有命令自动放行
- **任务完成 / 等待输入**:宠物弹泡泡通知(完成通知不朗读,避免打扰)。只有本轮耗时超过 `stop_notify_min_seconds`(默认 120 秒)的**长任务**才通知并显示耗时,快问快答不打扰;另有 45 秒冷却防多会话连环轰炸
- 宠物没运行时 hooks 静默跳过,零干扰

hooks 配置在 `~/.claude/settings.json`(PreToolUse 快速放行 + PermissionRequest 阻塞等待 + Notification / Stop 通知),配置示例见 `hook_bridge.py` 文件头注释。

> ⚠️ 临时授权 = 15 分钟内自动批准**所有**工具调用(含删文件等危险命令),请只在自己盯着任务时使用。

### 计划任务(额度重置后自动续跑)

典型场景:订阅额度跑满,Claude 提示"X 点重置"——让 Loki 到点自动叫本体继续:

| 命令 | 效果 |
|---|---|
| `/task 15:00 继续跑测试` | 15:00 时在最近会话的项目目录执行 `claude --continue -p "继续跑测试"`,恢复对话续跑 |
| `/task +2h` | 2 小时后续跑,默认指令"继续执行之前的任务" |
| `/task 09:00 提醒 开晨会` | 以"提醒"开头则只通知(泡泡+语音+音效),不动宿主 |
| `/task` / `/task del 1` | 查看队列 / 删除第 1 条 |

- 项目目录由 hooks 自动记录(最近一次活跃会话的 cwd),登记任务时会显示确认
- 续跑完成/失败都会通知(含输出结尾);离开模式下同步发邮件
- 续跑期间宿主如需授权,走上面的"帮按 Yes"体系(可配合临时授权/邮件审批)
- 任务存于 `~/.loki-pet/tasks.json`,宠物重启不丢;宿主命令可通过 `task_cli` 配置(默认 `claude --continue -p`)

### 会话断点档案与轻量续接(/resume)

**痛点**:长会话上下文压缩会丢细节;`claude --continue` 恢复超长会话要重载全部
上下文,又慢又贵。

- **自动存档**:上下文压缩时(PostCompact hook)白捡宿主生成的摘要存档,零成本;
  会话结束时(SessionEnd hook)用便宜模型从会话记录提炼一份交接快照
- **集中存本地**:档案统一存 `~/.loki-pet/handoffs/<项目名-哈希>/`,每项目滚动保留
  10 份,**不写入任何项目目录**(隐私友好,不怕误提交 git),手动清理才删
- **轻量续接**:`/resume` 列出各项目最新快照,`/resume 1` 以**全新会话 + 注入 2KB
  快照**的方式继续开发——秒级启动,成本比重载旧会话低两个数量级
- `/resume clear` 清空档案;续接命令可配(`resume_cli`,默认 `claude -p`)

与 `/task` 互补:额度断点用 `/task` 定时续跑原会话,上下文/关窗断点用 `/resume`
轻装转世。两者合起来,Loki 就是宿主的"断点续传管家"。

### 离开模式(邮件远程审批)

人不在电脑旁时,右键 Loki → **离开模式(邮件审批)**:

- **首次开启**会弹框让你填写常用邮箱,填一次就记住(存入 `notify_email`);之后在宠物聊天框输入 `/email 新地址` 可随时修改,输入 `/email` 查看当前地址
- 授权请求会经腾讯 Agent Mail 发到该邮箱,**回复邮件正文第一行写 `yes` / `no` / `15min`** 即远程完成授权;宠物每 60 秒查一次回复,授权等待自动延长到 15 分钟
- 任务完成同样发邮件通知
- 前置条件:`npm install -g @tencent-qqmail/agently-cli` 并 `agently-cli auth login` 完成 OAuth(无需任何密钥,配额 50 封/天)
- 安全:只解析主题带请求编号、发件人为本人的回复,且只认三个决定词;邮件里的其他内容一律不当作指令执行。注意发件人地址理论上可伪造,知道请求编号者可能冒充,个人使用风险可接受但不要用于高敏感环境

## 版本记录

见 [CHANGELOG.md](CHANGELOG.md)。

## 打包成独立应用(可选)

```bash
pip install pyinstaller
pyinstaller --windowed --onefile --add-data "assets:assets" pet.py
```

macOS 上产出 .app,Windows 上产出 .exe。注意 `config.json` 需与可执行文件放在同目录。

## License

[MIT](LICENSE)
