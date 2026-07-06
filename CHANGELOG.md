# Changelog

本项目版本迭代记录,格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [1.9.1] - 2026-07-06

### Added

- 聊天框支持自定义大小:拖拽右下角手柄自由拉伸(最小 260×200),停止拖拽后尺寸自动记住(`chat_width`/`chat_height`),下次启动保持

## [1.9.0] - 2026-07-06

### Added

- 授权风险小注解:收到 Claude Code 授权请求时,用便宜模型(宿主后端固定 Haiku,API 后端用所配模型)生成一句人话注解——命令作用 + [低/中/高风险]标注,显示在批准按钮上方;离席模式下注解写入审批邮件正文,手机上也能看懂再决定。`risk_notes` 配置可关(默认开),注解生成失败时静默降级不影响审批流程

## [1.8.1] - 2026-07-06

### Changed

- 随机轮播控件从右键菜单移入表情工坊面板(勾选框 + 间隔分钟数调节),右键菜单保持精简;仅调整间隔时不触发立即换装

## [1.8.0] - 2026-07-06

### Added

- 表情随机轮播:右键菜单"随机切换表情",开启后每隔 `emote_shuffle_minutes`(默认 5)分钟从已导入表情中随机换一个;开启瞬间立即切换一次给出反馈,不足 2 个表情时聊天框提示

## [1.7.2] - 2026-07-06

### Fixed

- 根治弹窗不可见问题:此前用 `Start-Process python -WindowStyle Hidden` 启动宠物,Windows 会把"隐藏"启动标志应用到进程随后弹出的第一个常规窗口(表情工坊/邮箱输入框),导致 `isVisible()` 为真但窗口实际被隐藏。启动方式改为 `pythonw`(无控制台,无需隐藏标志),SKILL.md 已更新并注明原因
- 聊天框新增 `/face` 命令:直接打开表情工坊,与右键菜单等效
- 表情工坊打开失败时错误显示在聊天框;未捕获异常写入 `~/.loki-pet/pet_error.log`;工坊窗口强制移到主屏中央

## [1.7.1] - 2026-07-06

### Fixed

- 修复表情工坊"弹不出来":窗口缺少置顶标志,被其他应用窗口遮挡(宠物进程在后台,Windows 前台锁定策略不允许其把普通窗口抢到前台)。现与邮箱弹框一致,置顶显示

## [1.7.0] - 2026-07-06

### Added

- 对话后端免配置切换:右键菜单新增"对话后端"——宿主 Agent(默认)/ 自定义 API(DeepSeek 等便宜接口,与宿主模型流量完全分开),切换即时生效无需重启
- 聊天框新增本地命令 `/api`:`/api` 查看当前后端与接口信息(key 打码),`/api 你的key [接口地址] [模型名]` 一句话配置并启用自定义 API(只给 key 时默认 DeepSeek)

## [1.6.2] - 2026-07-06

### Changed

- 音效随仓库分发:`assets/sounds/task_end.mp3` 入库,新增 `assets/sounds/README.md` DIY 指南(替换/新增/关闭音效的三种方式与格式说明);清理 `skill/` 下的重复音频文件

## [1.6.1] - 2026-07-06

### Fixed

- 安全默认:宠物每次启动时清除上次遗留的"临时授权"与"离开模式"状态,右键菜单两项默认均不勾选;临时授权 15 分钟到期后菜单自动恢复未勾选(勾选状态实时按到期时间计算)

## [1.6.0] - 2026-07-06

### Added

- 聊天模型可选(`cli_model`):cli 后端聊天默认用 `sonnet` 等便宜模型,不再消耗宿主的高级模型额度;右键菜单"聊天模型"可在 Haiku / Sonnet / Opus / 跟随宿主 间切换。仅聊天消耗模型,通知/语音/授权联动均不走模型

## [1.5.3] - 2026-07-06

### Changed(发布准备)

- 新增 `.gitignore`:排除 `config.json`(个人 API key/邮箱)、`__pycache__`、生成的表情帧(`assets/emotes/`)与音效文件(版权确认前不入库)
- skill 模板 `emote` 置空,克隆者用 `assets/*.mp4` 自行转换表情
- README 补齐功能清单(授权联动/任务完成音效/离开模式)、`notify_email` 配置项与聊天框 `/email` 命令说明
- INSTALL 新增可选组件表(Node.js / agently-cli / Claude Code)与 hooks 完整配置示例

## [1.5.2] - 2026-07-06

### Fixed

- 修复首次开启离开模式时程序卡死:邮箱填写框原为模态对话框且无置顶标志,被置顶的宠物窗口遮挡后看不见又阻塞全部输入。现改为右键菜单关闭后延迟弹出的**非模态置顶**对话框,即使被遮挡也不影响宠物操作;关闭离开模式时也会在聊天框给出提示

## [1.5.1] - 2026-07-06

### Changed

- 离开模式邮箱改为用户自填:`notify_email` 默认为空,首次开启离开模式时弹输入框填写并记住;未填有效邮箱则不开启
- 聊天框新增本地命令 `/email`:`/email` 查看当前通知邮箱,`/email 新地址` 随时修改(带格式校验,不发给 AI)

## [1.5.0] - 2026-07-06

### Added

- 离开模式(邮件远程审批):人不在电脑旁时,授权请求经腾讯 Agent Mail(agently-cli,agent 邮箱 OAuth 授权,无需密钥)发到 `notify_email`,回复邮件正文首行 `yes` / `no` / `15min` 即完成远程授权;任务完成也发邮件通知
  - 新增 `mail_notify.py`:两阶段确认自动完成的发信封装 + 收件箱回复解析(只识别三个决定词,只信任主题带请求编号且发件人为本人的回复,邮件内容不作为指令执行)
  - 宠物右键菜单新增"离开模式(邮件审批)"开关(状态存 `~/.loki-pet/away_mode.json`);宠物每 60 秒轮询一次回复
  - `hook_bridge.py`:离开模式下授权等待从 25 秒延长到 15 分钟;`~/.claude/settings.json` 的 PermissionRequest hook 超时相应调至 920 秒
  - `config.json` 新增 `notify_email`
- 依赖(外部工具):`@tencent-qqmail/agently-cli`(npm 全局)+ agently-mail skill

## [1.4.1] - 2026-07-06

### Added

- 任务完成 BGM:Claude Code 任务完成(Stop hook)时,宠物播放 `assets/sounds/task_end.mp3`(DQ 风格捷报音乐)
- 新增配置项 `stop_sound`(默认 `assets/sounds/task_end.mp3`,替换文件可换曲,设为空串关闭)
- 音效走独立播放通道(`sfx_player`),与语音朗读互不干扰;`install_skill.ps1` 同步拷贝 `assets/sounds/`

## [1.4.0] - 2026-07-06

### Added

- Claude Code 授权联动:新增 `hook_bridge.py` 桥接脚本,通过 `~/.loki-pet/` 文件队列(心跳/收件箱/回执)与宠物通信
  - PermissionRequest hook:弹授权提示时转发给宠物,聊天框出现 允许 / Yes 15分钟 / 拒绝 / 忽略 按钮,25 秒未处理回落终端
  - PreToolUse hook:临时授权生效期间所有命令快速自动放行(不阻塞)
  - Notification / Stop hook:等待输入、任务完成时宠物弹泡泡(权限与等待类通知带语音)
  - 宠物右键菜单新增"自动帮按 Yes(15分钟)"开关;宠物离线时 hooks 静默跳过
- hooks 已配置到 `~/.claude/settings.json`(保留原有气泡提醒)

## [1.3.0] - 2026-07-05

### Added

- 对话新增 CLI 后端(`backend: "cli"`):通过宿主 agent 的命令行(默认 `claude -p`,可配 `cli_command`)获取回复,消耗其登录账号额度,无需配置 API key;原 HTTP 接口保留为 `backend: "api"`(默认)
- 打包为 Agent Skill:新增 `skill/SKILL.md`(skill 定义)、`skill/config.json`(skill 版默认配置,backend=cli)与一键安装脚本 `install_skill.ps1`,安装到 `~/.claude/skills/loki-pet/` 后可被 Claude Code 等支持 Agent Skills 标准的 agent 直接调度(启动宠物、转换表情等)

## [1.2.0] - 2026-07-05

### Added

- 动态表情系统:宠物可播放透明背景的帧序列动画,替代静态图片,按视频原帧率循环
- 新增 `emote_studio.py` "表情工坊":选择视频 → 自动逐帧去背景 → 生成透明 PNG 帧序列(原分辨率无损),导入即生效;支持预览(棋盘格底)、切换、恢复静态、删除
- 抠图采用"边缘连通泛洪"方案:只去除与画面边界连通的纯色背景,角色内部与背景同色的区域(白发/白衣)完整保留;含防漏缝处理(腐蚀切断细连接后再还原)
- 命令行转换入口: `python emote_studio.py <视频> [表情名]`
- 右键菜单新增"表情工坊…"入口
- `config.json` 新增配置项 `emote`(当前表情名,空串为静态图片)
- 新增依赖 `opencv-python`、`numpy`;新增 `requirements.txt`
- 内置首个表情 `loki-DT1`(由 assets/loki-DT1.mp4 转换,121 帧 / 24fps)

### Notes

- 表情帧按原分辨率存盘(loki-DT1 约 85MB),显示时缩放到 `pet_width`,内存占用很小

## [1.1.1] - 2026-07-05

### Fixed

- 修复回复文本清洗后只剩标点/表情时,edge-tts 报 "No audio was received" 的问题:朗读前检查文本必须包含中文、字母或数字,否则静默跳过
- 语音合成失败时自动重试一次,应对偶发网络抖动;两次均失败才在聊天框显示错误

## [1.1.0] - 2026-07-05

### Added

- 语音朗读功能:Loki 回复时通过 edge-tts(微软神经网络语音,免费、无需 API key)自动朗读,默认音色 `zh-CN-YunxiNeural`
- 新增 `TTSWorker` 后台线程合成语音,播放使用 PySide6 自带 `QtMultimedia`,不阻塞界面
- 朗读前自动过滤 markdown 符号与括号内的动作描写
- 右键菜单新增"语音朗读"开关,状态持久化到 `config.json`
- `config.json` 新增配置项 `tts_enabled`、`tts_voice`
- 新增依赖 `edge-tts`

### Notes

- 临时语音文件存放于系统临时目录,两个文件轮换使用(Windows 上播放器会锁住正在播放的文件)

## [1.0.0] - 2026-07-05

### Added

- 首个版本:幽灵桌面宠物,透明置顶、正弦漂浮动画
- 左键拖拽移动、单击打开/关闭聊天框、右键菜单退出
- AI 对话:OpenAI 兼容 `/chat/completions` 接口,后台线程请求不阻塞界面
- 配置文件 `config.json`(API 信息、人设提示词、宠物尺寸、历史条数),首次运行自动生成
- 依赖:PySide6、requests
