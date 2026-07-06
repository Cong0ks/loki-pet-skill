---
name: loki-pet
description: Loki 幽灵桌面 AI 宠物:启动/关闭透明置顶桌宠(聊天默认调用宿主 agent CLI,无需配置 API key)、把角色视频转换成透明背景动态表情、管理表情/语音朗读。当用户想要桌面宠物、桌宠、启动/关闭 Loki、视频转透明动态表情/表情包、给桌宠换表情或换语音时使用。
---

# Loki 幽灵桌面宠物

透明置顶的桌面 AI 宠物:漂浮动画、拖拽、点击聊天、语音朗读、动态表情。
本 skill 目录即完整程序,所有命令的工作目录都应为本 skill 目录(下称 `$SKILL_DIR`)。

## 首次使用 / 环境检查

1. 确认依赖(缺失则安装):
   ```
   python -c "import PySide6, requests, edge_tts, cv2, numpy"
   pip install -r "$SKILL_DIR/requirements.txt"
   ```
2. 聊天后端默认 `"backend": "cli"`(见 `config.json`),通过 `cli_command`
   (默认 `claude -p`)调用宿主 agent 的命令行,消耗其登录账号额度,无需 API key。
   - 宿主不是 Claude Code 时,把 `cli_command` 改成对应 agent 的无头命令
     (如 `codex exec`、`gemini -p`),要求:提示词从 stdin 读入、回复输出到 stdout。
   - 也可改 `"backend": "api"` 走 OpenAI 兼容 HTTP 接口(需在 config 里填 api_key)。

## 启动宠物

必须以后台/分离方式启动,不要阻塞会话:

- Windows (PowerShell): `Start-Process pythonw -ArgumentList "pet.py" -WorkingDirectory "$SKILL_DIR"`
  (必须用 pythonw 而非 python + `-WindowStyle Hidden`:后者的隐藏标志会被 Windows
  应用到宠物后续弹出的对话框上,导致表情工坊/输入框"看不见")
- macOS / Linux: `cd "$SKILL_DIR" && nohup python pet.py >/dev/null 2>&1 &`

启动后屏幕右下角出现漂浮幽灵。操作方式(告知用户):左键拖拽移动、左键单击开关聊天框、右键菜单(表情工坊 / 语音开关 / 退出)。

## 关闭宠物

优先让用户右键 → 退出;需要强制关闭时按命令行匹配 kill 进程(进程名为 python,命令行含 pet.py)。

## 视频 → 透明动态表情(表情工坊)

把纯色背景的角色视频逐帧抠成透明 PNG 帧序列(原分辨率无损),宠物循环播放:

```
cd "$SKILL_DIR" && python emote_studio.py <视频路径> [表情名]
```

- 转换完成后,把 `config.json` 的 `"emote"` 设为该表情名即可生效(宠物运行中需重启,或让用户在右键菜单 → 表情工坊里点"使用")
- 要求:视频为纯色背景、角色轮廓闭合(有描边);背景色自动取画面边缘颜色
- 恢复静态图片:`"emote"` 设为空串
- 表情存放于 `$SKILL_DIR/assets/emotes/<表情名>/`

## 常用配置(config.json)

| 键 | 说明 |
|---|---|
| `backend` | `cli`(默认,用宿主 agent 额度) / `api`(OpenAI 兼容 HTTP) |
| `cli_command` | cli 后端的命令,默认 `claude -p` |
| `cli_model` | cli 聊天模型:`haiku`/`sonnet`(默认)/`opus`,空串跟随宿主;右键菜单可切换 |
| `api_base`/`api_key`/`model` | 自定义 API 后端(与宿主流量分开);聊天框 `/api key [地址] [模型]` 配置,右键菜单切换后端 |
| `system_prompt` | 宠物人设 |
| `emote` | 当前动态表情名,空串为静态图片 |
| `emote_shuffle` / `emote_shuffle_minutes` | 表情随机轮播开关与间隔(分钟),多表情时定时随机换装 |
| `tts_enabled` / `tts_voice` | 语音朗读开关 / 音色(edge-tts,免费无需 key) |
| `pet_width` | 显示宽度(像素) |
| `stop_sound` | Claude 任务完成时播放的音效路径(空串关闭) |
| `notify_email` | 离开模式通知邮箱;首次开启离开模式弹框填写并记住,聊天框 `/email 新地址` 可改 |
| `risk_notes` | 授权风险注解开关(默认开):便宜模型生成一句"命令作用+风险等级",宠物与离席邮件中显示 |
| `task_cli` | 计划任务续跑命令(默认 `claude --continue -p`);聊天框 `/task 15:00 指令` 登记,到点在最近会话目录续跑,`提醒`开头则仅通知 |
| `stop_notify_min_seconds` | 任务完成通知阈值(秒,默认120),低于该时长的轮次不通知 |

修改 config.json 后需重启宠物生效(表情/语音可在运行中通过右键菜单改)。

## Claude Code 授权联动(帮按 Yes)

`hook_bridge.py` 把 Claude Code 的权限请求/通知经 `~/.loki-pet/` 文件队列转发给宠物:
弹授权提示时宠物出现 允许 / Yes 15分钟 / 拒绝 / 忽略 按钮,临时授权期间所有命令自动放行,
也可在宠物右键菜单开关"自动帮按 Yes"。hooks 需配置在 `~/.claude/settings.json`
(PreToolUse / PermissionRequest / Notification / Stop 四个事件调用
`python hook_bridge.py --event <事件名小写>`),细节见 hook_bridge.py 文件头注释。
宠物未运行时 hooks 静默跳过,不会造成干扰。

## 故障排查

- 聊天报"CLI 调用失败": 检查 `cli_command` 对应命令在 PATH 中且已登录
- 语音无声: 需联网(edge-tts 在线接口);回复只含标点时会自动跳过朗读
- 转换表情报错: 确认视频可读、背景为纯色
