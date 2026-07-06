# -*- coding: utf-8 -*-
"""
Loki 幽灵桌面宠物 — 跨平台 (Windows / macOS)
功能: 漂浮动画 / 拖拽 / 单击打开聊天 / AI 对话(OpenAI 兼容接口) / 语音朗读 /
      动态表情(透明帧序列动画, 见 emote_studio.py) / 右键菜单
依赖: PySide6, requests, edge-tts, opencv-python, numpy
"""
import asyncio
import json
import math
import random
import re
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import edge_tts
import requests
from PySide6.QtCore import QPoint, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu,
    QPushButton, QSizeGrip, QTextBrowser, QVBoxLayout, QWidget,
)

import mail_notify
from emote_studio import EmoteStudio, list_emotes, load_emote_frames

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
SPRITE_PATH = BASE_DIR / "assets" / "loki.png"

# 与 Claude Code hooks 的文件队列桥接目录(见 hook_bridge.py)
BRIDGE_DIR = Path.home() / ".loki-pet"
INBOX = BRIDGE_DIR / "inbox"
REPLIES = BRIDGE_DIR / "replies"
TEMP_AUTH = BRIDGE_DIR / "temp_auth.json"
HEARTBEAT = BRIDGE_DIR / "heartbeat"
TASKS_PATH = BRIDGE_DIR / "tasks.json"
LAST_SESSION = BRIDGE_DIR / "last_session.json"
TEMP_AUTH_MINUTES = 15


def parse_when(token: str):
    """解析计划时间: HH:MM(已过则算明天) 或 +Nm/+Nh,失败返回 None。"""
    m = re.fullmatch(r"\+(\d+)([hm])", token)
    if m:
        return time.time() + int(m.group(1)) * (3600 if m.group(2) == "h" else 60)
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", token)
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        now = datetime.now()
        target = now.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                             second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target.timestamp()
    return None


def run_continuation(cfg: dict, task: dict) -> str:
    """到点续跑: 在记录的项目目录里让宿主恢复最近会话继续任务(后台线程)。"""
    cmd = cfg.get("task_cli", "claude --continue -p")
    instr = task.get("text", "继续执行之前的任务")
    proc = subprocess.run(
        f'{cmd} "{instr}"', shell=True, cwd=task.get("cwd") or None,
        capture_output=True, text=True, encoding="utf-8", timeout=14400,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            (proc.stderr or proc.stdout or "宿主 CLI 调用失败").strip()[:200])
    return (proc.stdout or "").strip()[-300:]

DEFAULT_CONFIG = {
    # backend: "api" = HTTP 调 OpenAI 兼容接口; "cli" = 调宿主 agent 命令行
    # (如 claude / codex),消耗其登录账号的额度,无需 API key
    "backend": "api",
    "cli_command": "claude -p",
    # cli 后端使用的模型: 宠物闲聊用便宜模型即可,不要浪费宿主的高级模型额度
    # 可选 haiku / sonnet / opus,空串 = 跟随宿主默认;也可右键菜单切换
    "cli_model": "sonnet",
    "api_base": "https://api.deepseek.com/v1",
    "api_key": "sk-你的key",
    "model": "deepseek-chat",
    "system_prompt": (
        "你是 Loki,一只白发红眼、坏笑着的小幽灵桌面宠物。"
        "说话简短、俏皮、带点恶作剧气质,每次回复不超过三句话。"
    ),
    "pet_width": 180,
    "max_history": 20,
    "tts_enabled": True,
    "tts_voice": "zh-CN-YunxiNeural",
    "emote": "",
    # 表情随机轮播: 导入多个表情后,每隔 N 分钟随机切换一个(右键菜单开关)
    "emote_shuffle": False,
    "emote_shuffle_minutes": 5,
    # Claude 任务完成时播放的音效(相对本目录;空串关闭)
    "stop_sound": "assets/sounds/task_end.mp3",
    # 离开模式的通知邮箱(经 agently-cli 发送,回复 yes/no/15min 即远程授权)
    # 首次开启离开模式时弹框填写并记住;聊天框输入 /email 新地址 可随时修改
    "notify_email": "",
    # 授权风险注解: 收到授权请求时用便宜模型生成一句"命令作用+风险等级"
    "risk_notes": True,
    # 聊天框尺寸(拖拽右下角手柄调整后自动记住)
    "chat_width": 300,
    "chat_height": 260,
    # 任务完成通知阈值(秒): 本轮耗时低于该值不通知,过滤快问快答
    "stop_notify_min_seconds": 120,
    # 计划任务续跑用的宿主命令(/task 到点时执行,追加任务指令)
    "task_cli": "claude --continue -p",
    # 轻量记忆: 每 10 轮对话用便宜模型提炼一次"关于主人的事实+近况",
    # 存 ~/.loki-pet/memory.md(40 条封顶),注入聊天人设; /memory 查看管理
    "memory_enabled": True,
}

EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")

RISK_PROMPT = (
    "你是给不懂编程的用户解释命令的安全助手。用中文一句话(不超过50字)说明"
    "下面这条操作会做什么,开头标注[低风险]/[中风险]/[高风险]。"
    "删除或覆盖文件、下载执行、修改系统配置、对外发送数据属于中高风险,"
    "只读查询属于低风险。只输出这一句话,不要任何其他内容。\n操作: "
)


def cheap_complete(cfg: dict, prompt: str, max_tokens: int = 200) -> str:
    """用便宜模型跑一个小提示词(风险注解/记忆提炼共用,后台线程中调用)。"""
    if cfg.get("backend", "cli") != "api":
        cmd = cfg.get("cli_command", "claude -p")
        if cmd.startswith("claude"):
            cmd += " --model haiku"  # 杂务固定用最便宜的模型
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                              encoding="utf-8", shell=True, timeout=90)
        text = (proc.stdout or "").strip()
        if proc.returncode != 0 or not text:
            raise RuntimeError((proc.stderr or "CLI 无输出").strip()[:100])
        return text
    resp = requests.post(
        cfg["api_base"].rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {cfg['api_key']}",
                 "Content-Type": "application/json"},
        json={"model": cfg["model"], "temperature": 0, "max_tokens": max_tokens,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def generate_risk_note(cfg: dict, tool: str, detail: str) -> str:
    """用便宜模型给授权请求生成一句人话风险注解(在后台线程中调用)。"""
    text = cheap_complete(cfg, RISK_PROMPT + f"{tool}: {detail}", max_tokens=100)
    return text.splitlines()[0][:100]


# ---------------- 轻量记忆 ----------------
MEMORY_PATH = BRIDGE_DIR / "memory.md"
MAX_FACTS = 40
MEMORY_EVERY_ROUNDS = 10

MEM_PROMPT = (
    "你在为一只桌宠提炼关于'主人'的长期记忆。从下面对话中提取值得长期记住的"
    "稳定事实(偏好/称呼/长期项目/习惯,0~3条,每条不超过30字,临时状态不要);"
    "再用一句话(不超过50字)概括主人近况。严格按此格式输出,没有新事实就只输出"
    " RECENT 行:\nFACT: <事实>\nRECENT: <近况>\n"
)


def load_memory() -> dict:
    facts, recent, section = [], [], ""
    try:
        text = MEMORY_PATH.read_text(encoding="utf-8")
    except OSError:
        return {"facts": [], "recent": ""}
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## 事实"):
            section = "f"
        elif s.startswith("## 近况"):
            section = "r"
        elif section == "f" and s.startswith("- "):
            facts.append(s[2:])
        elif section == "r" and s and not s.startswith("#"):
            recent.append(s)
    return {"facts": facts, "recent": " ".join(recent)}


def save_memory(mem: dict):
    lines = ["# Loki 的记忆(纯文本,可手动编辑;删除本文件即清空)", "", "## 事实"]
    lines += [f"- {f}" for f in mem["facts"]]
    lines += ["", "## 近况", mem.get("recent", ""), ""]
    MEMORY_PATH.write_text("\n".join(lines), encoding="utf-8")


def extract_memory(cfg: dict, dialog: str, known_facts: str):
    """便宜模型从近期对话提炼新事实与近况(后台线程)。"""
    prompt = MEM_PROMPT
    if known_facts:
        prompt += f"\n已记住的事实(不要重复输出): {known_facts}\n"
    prompt += f"\n对话:\n{dialog}"
    text = cheap_complete(cfg, prompt, max_tokens=250)
    facts, recent = [], ""
    for line in text.splitlines():
        s = line.strip()
        if s.upper().startswith("FACT:"):
            facts.append(s[5:].strip())
        elif s.upper().startswith("RECENT:"):
            recent = s[7:].strip()
    return facts, recent


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    else:
        CONFIG_PATH.write_text(
            json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return cfg


class ChatWorker(QThread):
    """后台线程获取 AI 回复,避免阻塞 UI。

    backend="api": HTTP 调 OpenAI 兼容 /chat/completions
    backend="cli": 调宿主 agent 的命令行(claude -p 等),用其账号额度
    """
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, cfg: dict, messages: list):
        super().__init__()
        self.cfg = cfg
        self.messages = messages

    def run(self):
        try:
            if self.cfg.get("backend", "api") == "cli":
                self.finished_ok.emit(self.run_cli())
            else:
                self.finished_ok.emit(self.run_api())
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"(请求失败: {e})")

    def run_cli(self) -> str:
        # 把对话历史拼成单个提示词,经 stdin 交给宿主 agent CLI
        lines = []
        for m in self.messages:
            if m["role"] == "system":
                lines.append(m["content"])
                lines.append("\n以下是对话记录,请以上述人设回复最后一条,"
                             "只输出回复内容本身,不要任何前缀或解释:\n")
            else:
                who = "我" if m["role"] == "user" else "Loki"
                lines.append(f"{who}: {m['content']}")
        cmd = self.cfg.get("cli_command", "claude -p")
        model = self.cfg.get("cli_model", "").strip()
        if model and cmd.startswith("claude"):
            cmd += f" --model {model}"
        proc = subprocess.run(
            cmd,
            input="\n".join(lines),
            capture_output=True, text=True, encoding="utf-8",
            shell=True, timeout=180,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                (proc.stderr or proc.stdout or "CLI 调用失败").strip()[:300])
        text = (proc.stdout or "").strip()
        if not text:
            raise RuntimeError("CLI 没有返回内容")
        return text

    def run_api(self) -> str:
        resp = requests.post(
                self.cfg["api_base"].rstrip("/") + "/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.cfg['api_key']}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.cfg["model"],
                    "messages": self.messages,
                    "temperature": 0.9,
                },
                timeout=60,
            )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


class TTSWorker(QThread):
    """后台线程调 edge-tts 合成语音文件,完成后交给主线程播放。"""
    ready = Signal(str)
    failed = Signal(str)

    def __init__(self, text: str, voice: str, out_path: Path):
        super().__init__()
        self.text = text
        self.voice = voice
        self.out_path = out_path

    def run(self):
        last_err = None
        for _ in range(2):  # 网络抖动时自动重试一次
            try:
                tts = edge_tts.Communicate(self.text, self.voice)
                asyncio.run(tts.save(str(self.out_path)))
                self.ready.emit(str(self.out_path))
                return
            except Exception as e:  # noqa: BLE001
                last_err = e
        self.failed.emit(f"(语音合成失败: {last_err})")


class MailWorker(QThread):
    """后台线程跑 agently-cli(发邮件 / 查回复),不阻塞界面。"""
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn = fn
        self.args = args

    def run(self):
        try:
            self.done.emit(self.fn(*self.args))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e)[:200])


class ChatPanel(QWidget):
    """跟随宠物的小聊天面板。"""
    def __init__(self, pet: "PetWindow"):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.pet = pet
        # 尺寸可由用户拖拽右下角手柄调整,并记住到 config
        self.setMinimumSize(260, 200)

        self.box = QWidget(self)
        self.box.setStyleSheet(
            "background: rgba(25,25,35,235); border-radius: 12px;"
        )
        layout = QVBoxLayout(self.box)
        layout.setContentsMargins(10, 10, 10, 10)

        self.history_view = QTextBrowser()
        self.history_view.setStyleSheet(
            "background: transparent; border: none; color: #eee; font-size: 13px;"
        )
        self.input = QLineEdit()
        self.input.setPlaceholderText("对 Loki 说点什么…(回车发送)")
        self.input.setStyleSheet(
            "background: rgba(255,255,255,25); border: 1px solid #555;"
            "border-radius: 6px; color: #fff; padding: 6px; font-size: 13px;"
        )
        self.input.returnPressed.connect(self.send)

        # Claude Code 权限请求的批准按钮条(有待批请求时显示)
        self.approve_bar = QWidget()
        bar_layout = QHBoxLayout(self.approve_bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        btn_style = (
            "QPushButton {{ background: {bg}; color: #fff; border: none;"
            "border-radius: 6px; padding: 5px 8px; font-size: 12px; }}"
        )
        for label, decision, color in (
            ("允许", "allow", "rgba(64,145,108,220)"),
            (f"Yes {TEMP_AUTH_MINUTES}分钟", "temp", "rgba(42,111,151,220)"),
            ("拒绝", "deny", "rgba(190,68,68,220)"),
            ("忽略", "ignore", "rgba(120,120,130,220)"),
        ):
            btn = QPushButton(label)
            btn.setStyleSheet(btn_style.format(bg=color))
            btn.clicked.connect(lambda _=False, d=decision: self.resolve(d))
            bar_layout.addWidget(btn)
        self.approve_bar.hide()

        layout.addWidget(self.history_view)
        layout.addWidget(self.approve_bar)
        layout.addWidget(self.input)

        self.worker = None
        self.pending_id = None

        # 右下角缩放手柄 + 尺寸记忆(停止拖拽 0.8 秒后写入 config)
        self.grip = QSizeGrip(self)
        self.grip.setFixedSize(18, 18)
        self.grip.setStyleSheet("background: transparent;")
        self._size_save_timer = QTimer(self)
        self._size_save_timer.setSingleShot(True)
        self._size_save_timer.timeout.connect(self.save_size)
        self.resize(int(pet.cfg.get("chat_width", 300)),
                    int(pet.cfg.get("chat_height", 260)))
        # 隐藏状态下 resizeEvent 不触发,先手动同步一次内部布局
        self.box.setGeometry(0, 0, self.width(), self.height())
        self.grip.move(self.width() - 20, self.height() - 20)
        self.grip.raise_()

    def resizeEvent(self, e):
        if hasattr(self, "box"):
            self.box.setGeometry(0, 0, self.width(), self.height())
        if hasattr(self, "grip"):
            self.grip.move(self.width() - 20, self.height() - 20)
            self.grip.raise_()
            self._size_save_timer.start(800)
        super().resizeEvent(e)

    def save_size(self):
        self.pet.cfg["chat_width"] = self.width()
        self.pet.cfg["chat_height"] = self.height()
        self.pet.save_cfg()

    def show_approval(self, msg: dict):
        self.append("Claude", f'想执行 <code>{msg["tool"]}: {msg["text"]}</code>')
        self.pending_id = msg["id"]
        # 兜底过期时刻: 桥接被中断收不到 cancel 时,按钮也会静默消失
        wait = 900 if mail_notify.away_mode_active() else 300
        self.pending_deadline = time.time() + wait + 30
        self.approve_bar.show()

    def cancel_approval(self, ref: str):
        # 请求已回落终端(或已在别处处理): 静默收起按钮,不打扰用户
        if self.pending_id == ref:
            self.pending_id = None
            self.approve_bar.hide()

    def check_expiry(self):
        if self.pending_id and time.time() > getattr(self, "pending_deadline", 0):
            self.pending_id = None
            self.approve_bar.hide()

    def resolve(self, decision: str):
        if not self.pending_id:
            return
        REPLIES.mkdir(parents=True, exist_ok=True)
        (REPLIES / f"{self.pending_id}.json").write_text(
            json.dumps({"decision": decision}), encoding="utf-8")
        self.pending_id = None
        self.approve_bar.hide()
        if decision == "temp":
            self.pet.set_temp_auth(True)
        tips = {"allow": "帮你按 Yes 啦!", "temp": f"这{TEMP_AUTH_MINUTES}分钟我全帮你按 Yes~",
                "deny": "帮你拒绝了!", "ignore": "那你去终端自己处理咯~"}
        self.append("Loki", tips[decision])

    def append(self, who: str, text: str):
        color = "#ff6b6b" if who == "Loki" else "#8ecae6"
        self.history_view.append(
            f'<b style="color:{color}">{who}:</b> {text}'
        )
        sb = self.history_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def send(self):
        text = self.input.text().strip()
        if not text:
            return
        # 本地命令(不发给 AI): /email 通知邮箱; /api 自定义 API 配置
        if text.startswith("/email"):
            self.input.clear()
            self.pet.handle_email_command(text[len("/email"):].strip())
            return
        if text.startswith("/api"):
            self.input.clear()
            self.pet.handle_api_command(text[len("/api"):].strip())
            return
        if text.startswith("/face"):
            self.input.clear()
            self.pet.open_studio()
            return
        if text.startswith("/task"):
            self.input.clear()
            self.pet.handle_task_command(text[len("/task"):].strip())
            return
        if text.startswith("/memory"):
            self.input.clear()
            self.pet.handle_memory_command(text[len("/memory"):].strip())
            return
        if self.worker and self.worker.isRunning():
            return
        self.input.clear()
        self.append("我", text)
        self.pet.history.append({"role": "user", "content": text})

        cfg = self.pet.cfg
        msgs = [{"role": "system",
                 "content": cfg["system_prompt"] + self.pet.memory_prompt()}]
        msgs += self.pet.history[-cfg["max_history"]:]
        self.worker = ChatWorker(cfg, msgs)
        self.worker.finished_ok.connect(self.on_reply)
        self.worker.failed.connect(lambda e: self.append("Loki", e))
        self.worker.start()

    def on_reply(self, text: str):
        self.pet.history.append({"role": "assistant", "content": text})
        self.append("Loki", text)
        self.pet.speak(text)
        self.pet.note_exchange()

    def follow_pet(self):
        """贴在宠物左侧或右侧,自动避开屏幕边缘。"""
        g = self.pet.geometry()
        screen = QApplication.primaryScreen().availableGeometry()
        x = g.right() + 8
        if x + self.width() > screen.right():
            x = g.left() - self.width() - 8
        y = max(screen.top(), min(g.top(), screen.bottom() - self.height()))
        self.move(x, y)


class PetWindow(QWidget):
    def __init__(self, cfg: dict):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.cfg = cfg
        self.history: list = []

        self.label = QLabel(self)
        # 表情帧动画: 有导入表情时循环播放,否则显示静态图
        self.frames: list = []
        self.frame_idx = 0
        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self.anim_step)
        self.load_appearance()

        screen = QApplication.primaryScreen().availableGeometry()
        self.base_pos = QPoint(screen.right() - self.width() - 60,
                               screen.bottom() - self.height() - 80)
        self.move(self.base_pos)

        # 漂浮动画: 正弦上下浮动
        self.phase = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.float_step)
        self.timer.start(33)  # ~30fps

        self.chat = ChatPanel(self)
        self._drag_offset = None
        self._moved = False

        # 语音: edge-tts 合成 + QtMultimedia 播放
        self.audio_out = QAudioOutput()
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.audio_out)
        # 独立音效通道(任务完成 BGM 等),不与语音朗读互抢
        self.sfx_out = QAudioOutput()
        self.sfx_player = QMediaPlayer()
        self.sfx_player.setAudioOutput(self.sfx_out)
        self._tts_worker = None
        # 轮换两个临时文件: Windows 上播放器会锁住正在播的文件,不能原地覆盖
        tmp = Path(tempfile.gettempdir())
        self._tts_files = [tmp / "loki_tts_0.mp3", tmp / "loki_tts_1.mp3"]
        self._tts_slot = 0
        self._studio = None

        # Claude Code hook 桥接: 心跳表明宠物在线,轮询收件箱接收请求/通知
        INBOX.mkdir(parents=True, exist_ok=True)
        REPLIES.mkdir(parents=True, exist_ok=True)
        # 每次启动都回到安全默认: 临时授权与离开模式均不开启
        TEMP_AUTH.unlink(missing_ok=True)
        mail_notify.AWAY_MODE.unlink(missing_ok=True)
        self.hb_timer = QTimer(self)
        self.hb_timer.timeout.connect(
            lambda: HEARTBEAT.write_text(str(time.time()), encoding="utf-8"))
        self.hb_timer.start(5000)
        HEARTBEAT.write_text(str(time.time()), encoding="utf-8")
        self.inbox_timer = QTimer(self)
        self.inbox_timer.timeout.connect(self.poll_inbox)
        self.inbox_timer.start(500)

        # 离开模式: 授权请求转发邮件,每 60 秒查一次回复
        self.pending_emails: dict = {}  # req_id -> 发出时间
        self._last_stop_note = 0.0
        self.mem_round = 0
        self._mail_workers: list = []
        self.mail_timer = QTimer(self)
        self.mail_timer.timeout.connect(self.poll_mail_replies)
        self.mail_timer.start(60000)

        # 表情随机轮播
        self.shuffle_timer = QTimer(self)
        self.shuffle_timer.timeout.connect(self.shuffle_emote)
        if self.cfg.get("emote_shuffle"):
            self.shuffle_timer.start(self.shuffle_interval_ms())

        # 计划任务: 每 30 秒检查一次到期任务(重启不丢,存 tasks.json)
        self.tasks_timer = QTimer(self)
        self.tasks_timer.timeout.connect(self.check_tasks)
        self.tasks_timer.start(30000)

    # ---- 轻量记忆 ----
    def memory_prompt(self) -> str:
        if not self.cfg.get("memory_enabled", True):
            return ""
        mem = load_memory()
        if not mem["facts"] and not mem["recent"]:
            return ""
        parts = ["\n\n[你对主人的记忆,自然地运用,不要生硬复述]"]
        if mem["facts"]:
            parts.append("事实: " + "; ".join(mem["facts"]))
        if mem["recent"]:
            parts.append("近况: " + mem["recent"])
        return "\n".join(parts)

    def note_exchange(self):
        """每完成一轮对话计数,攒够 N 轮用便宜模型提炼一次记忆。"""
        if not self.cfg.get("memory_enabled", True):
            return
        self.mem_round += 1
        if self.mem_round < MEMORY_EVERY_ROUNDS:
            return
        self.mem_round = 0
        tail = self.history[-MEMORY_EVERY_ROUNDS * 2:]
        dialog = "\n".join(
            f"{'主人' if m['role'] == 'user' else 'Loki'}: {m['content']}"
            for m in tail)
        known = "; ".join(load_memory()["facts"])[:800]
        worker = MailWorker(extract_memory, self.cfg, dialog, known)
        worker.done.connect(self.on_memory_extracted)
        worker.failed.connect(lambda _e: None)  # 提炼失败静默,下轮再试
        worker.start()
        self._mail_workers.append(worker)

    def on_memory_extracted(self, result):
        new_facts, recent = result
        mem = load_memory()
        today = time.strftime("%Y-%m-%d")
        for f in new_facts:
            f = f.strip()
            core_old = [old.split("] ", 1)[-1] for old in mem["facts"]]
            if f and f not in core_old:
                mem["facts"].append(f"[{today}] {f}")
        mem["facts"] = mem["facts"][-MAX_FACTS:]  # 封顶,最旧的先淘汰
        if recent:
            mem["recent"] = f"[{today}] {recent}"
        save_memory(mem)

    def handle_memory_command(self, arg: str):
        """聊天框 /memory 命令: 查看/删除/清空记忆。"""
        mem = load_memory()
        if not arg:
            if not mem["facts"] and not mem["recent"]:
                self.chat.append("Loki", "我还没有记忆~多聊聊,每 10 轮我会"
                                         "悄悄记下关于你的事。<br>"
                                         "(文件在 ~/.loki-pet/memory.md,可手动编辑)")
                return
            lines = [f"{i}. {f}" for i, f in enumerate(mem["facts"], 1)]
            if mem["recent"]:
                lines.append(f"近况: {mem['recent']}")
            lines.append("<br>管理: <code>/memory forget 关键词</code> 删除 / "
                         "<code>/memory clear</code> 清空")
            self.chat.append("Loki", "<br>".join(lines))
        elif arg.startswith("forget"):
            kw = arg[len("forget"):].strip()
            if not kw:
                self.chat.append("Loki", "(要忘掉什么?/memory forget 关键词)")
                return
            kept = [f for f in mem["facts"] if kw not in f]
            removed = len(mem["facts"]) - len(kept)
            mem["facts"] = kept
            save_memory(mem)
            self.chat.append("Loki", f"(好啦,忘掉了 {removed} 条含「{kw}」的记忆)")
        elif arg == "clear":
            MEMORY_PATH.unlink(missing_ok=True)
            self.chat.append("Loki", "(全忘光啦!我们重新认识吧~)")
        else:
            self.chat.append("Loki", "(用法: /memory 查看 | forget 关键词 | clear)")

    # ---- 计划任务 ----
    def load_tasks(self) -> list:
        try:
            return json.loads(TASKS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def save_tasks(self, tasks: list):
        TASKS_PATH.write_text(json.dumps(tasks, ensure_ascii=False, indent=1),
                              encoding="utf-8")

    def handle_task_command(self, arg: str):
        """聊天框 /task 命令: 查看/添加/删除计划任务。"""
        tasks = self.load_tasks()
        if not arg:
            if not tasks:
                self.chat.append("Loki", "当前没有计划任务~<br>"
                                 "用法: <code>/task 15:00 继续跑测试</code>(到点让本体续跑)<br>"
                                 "<code>/task +2h</code>(2小时后,默认继续之前任务)<br>"
                                 "<code>/task 09:00 提醒 开晨会</code>(仅提醒)<br>"
                                 "<code>/task del 1</code>(删除第1条)")
                return
            lines = []
            for i, t in enumerate(tasks, 1):
                when = time.strftime("%m-%d %H:%M", time.localtime(t["when"]))
                kind = "提醒" if t["mode"] == "remind" else "续跑"
                lines.append(f"{i}. [{kind}] {when} — {t['text']}")
            self.chat.append("Loki", "<br>".join(lines))
            return
        if arg.startswith("del"):
            try:
                idx = int(arg[3:].strip()) - 1
                removed = tasks.pop(idx)
                self.save_tasks(tasks)
                self.chat.append("Loki", f"(已删除计划任务: {removed['text']})")
            except (ValueError, IndexError):
                self.chat.append("Loki", "(没找到这条任务,/task 看看编号)")
            return
        parts = arg.split(None, 1)
        when = parse_when(parts[0])
        if when is None:
            self.chat.append("Loki", "(时间没看懂~支持 15:00 或 +2h / +30m 格式)")
            return
        rest = parts[1].strip() if len(parts) > 1 else ""
        if rest.startswith("提醒"):
            mode, text, cwd = "remind", rest[2:].strip() or "时间到啦!", ""
        else:
            mode = "continue"
            text = rest or "继续执行之前的任务"
            try:
                cwd = json.loads(LAST_SESSION.read_text(
                    encoding="utf-8")).get("cwd", "")
            except (OSError, ValueError):
                cwd = ""
        tasks.append({"id": uuid.uuid4().hex[:8], "when": when,
                      "mode": mode, "text": text, "cwd": cwd})
        self.save_tasks(tasks)
        when_str = time.strftime("%m-%d %H:%M", time.localtime(when))
        if mode == "remind":
            self.chat.append("Loki", f"(记下啦!{when_str} 提醒你: {text})")
        else:
            where = f"<br>项目目录: {cwd}" if cwd else "<br>⚠️ 还没记录到项目目录,届时在宠物所在目录执行"
            self.chat.append("Loki", f"(记下啦!{when_str} 让本体续跑: {text}{where})")

    def check_tasks(self):
        tasks = self.load_tasks()
        due = [t for t in tasks if t["when"] <= time.time()]
        if not due:
            return
        remaining = [t for t in tasks if t["when"] > time.time()]
        self.save_tasks(remaining)
        for t in due:
            self.fire_task(t)

    def fire_task(self, t: dict):
        if t["mode"] == "remind":
            self.chat.append("Loki", f"⏰ {t['text']}")
            self.show_chat()
            self.speak(t["text"])
            self.play_sfx()
            if mail_notify.away_mode_active() and self.cfg.get("notify_email"):
                self.run_mail(mail_notify.send_notify_email,
                              self.cfg["notify_email"], "定时提醒", t["text"])
            return
        self.chat.append("Loki", f"⏰ 到点啦!让本体继续干活: {t['text']}<br>"
                                 "<span style='color:#999'>已在后台启动,"
                                 "会话越长跑得越久(几分钟到更久),完成我会通知你~</span>")
        self.show_chat()
        self.speak("到点啦,我去叫本体继续干活!")
        worker = MailWorker(run_continuation, self.cfg, t)
        worker.done.connect(lambda out, task=t: self.on_task_done(task, out))
        worker.failed.connect(lambda e, task=t: self.on_task_failed(task, e))
        worker.start()
        self._mail_workers.append(worker)

    def on_task_done(self, t: dict, tail: str):
        note = f"✅ 续跑完成: {t['text']}"
        self.chat.append("Loki", f"{note}<br><span style='color:#999'>{tail[-160:]}</span>")
        self.show_chat()
        self.play_sfx()
        if mail_notify.away_mode_active() and self.cfg.get("notify_email"):
            self.run_mail(mail_notify.send_notify_email,
                          self.cfg["notify_email"], "计划任务完成",
                          f"{t['text']}\n\n结尾输出:\n{tail}")

    def on_task_failed(self, t: dict, err: str):
        self.chat.append("Loki", f"❌ 续跑失败: {t['text']}<br>{err}")
        self.show_chat()
        if mail_notify.away_mode_active() and self.cfg.get("notify_email"):
            self.run_mail(mail_notify.send_notify_email,
                          self.cfg["notify_email"], "计划任务失败",
                          f"{t['text']}\n\n{err}")

    # ---- 表情随机轮播 ----
    def shuffle_interval_ms(self) -> int:
        return max(1, int(self.cfg.get("emote_shuffle_minutes", 5))) * 60000

    def shuffle_emote(self):
        candidates = [n for n in list_emotes() if n != self.cfg.get("emote", "")]
        if candidates:
            self.apply_emote(random.choice(candidates))

    def on_shuffle_changed(self, enabled: bool, minutes: int):
        """表情工坊面板的轮播设置变化: 区分开关切换与仅调整间隔。"""
        was = bool(self.cfg.get("emote_shuffle"))
        self.cfg["emote_shuffle_minutes"] = max(1, minutes)
        if enabled == was:  # 只改了间隔
            self.save_cfg()
            if enabled:
                self.shuffle_timer.start(self.shuffle_interval_ms())
            return
        self.set_emote_shuffle(enabled)

    def set_emote_shuffle(self, enabled: bool):
        self.cfg["emote_shuffle"] = enabled
        self.save_cfg()
        if enabled:
            count = len(list_emotes())
            if count < 2:
                self.chat.append("Loki", f"(随机轮播已开启,但目前只有 {count} 个表情,"
                                         "多导入几个才换得起来哦~)")
            else:
                mins = self.cfg.get("emote_shuffle_minutes", 5)
                self.chat.append("Loki", f"(表情随机轮播已开启,每 {mins} 分钟"
                                         f"从 {count} 个表情里随机换一个)")
            self.show_chat()
            self.shuffle_timer.start(self.shuffle_interval_ms())
            self.shuffle_emote()  # 立即换一次,给出直观反馈
        else:
            self.shuffle_timer.stop()

    # ---- Claude Code hook 桥接 ----
    def poll_inbox(self):
        self.chat.check_expiry()
        for f in sorted(INBOX.glob("*.json")):
            try:
                msg = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                msg = None
            try:
                f.unlink()
            except OSError:
                pass
            if msg:
                self.handle_bridge_msg(msg)

    def handle_bridge_msg(self, msg: dict):
        kind = msg.get("type")
        if kind == "permission":
            self.chat.show_approval(msg)
            self.show_chat()
            self.speak("有命令等你批准哦!")
            # 风险注解生成后再发离席邮件,让注解一并写进邮件正文
            if self.cfg.get("risk_notes", True):
                worker = MailWorker(generate_risk_note, self.cfg,
                                    msg.get("tool", "?"), msg.get("text", ""))
                worker.done.connect(lambda note, m=msg: self.on_risk_note(m, note))
                worker.failed.connect(lambda _e, m=msg: self.send_away_email(m, ""))
                worker.start()
                self._mail_workers.append(worker)
            else:
                self.send_away_email(msg, "")
        elif kind == "cancel":
            self.chat.cancel_approval(msg.get("ref", ""))
            self.pending_emails.pop(msg.get("ref", ""), None)
        elif kind == "notify":
            self.chat.append("Claude", msg.get("text", ""))
            self.show_chat()
            self.speak("Claude 在叫你啦!")
        elif kind == "stop":
            # 只报"长任务"完成: 快问快答的每轮结束不打扰(duration<0 表示
            # 未配置 UserPromptSubmit hook,无法计时,保持旧行为全部通知)
            duration = float(msg.get("duration", -1))
            threshold = int(self.cfg.get("stop_notify_min_seconds", 120))
            if 0 <= duration < threshold:
                return
            if time.time() - self._last_stop_note < 45:
                return  # 冷却: 防止多会话同时完成时连环轰炸
            self._last_stop_note = time.time()
            mins = f"(耗时 {int(duration // 60)} 分钟)" if duration > 0 else ""
            self.chat.append("Claude", msg.get("text", "") + mins)
            self.show_chat()  # 任务完成只弹泡泡,不朗读,避免频繁打扰
            self.play_sfx()
            if mail_notify.away_mode_active() and self.cfg.get("notify_email"):
                self.run_mail(mail_notify.send_notify_email,
                              self.cfg["notify_email"], "任务完成",
                              msg.get("text", "Claude 任务完成啦!") + mins)

    def on_risk_note(self, msg: dict, note: str):
        if note:
            self.chat.append("Loki", f"🔎 {note}")
        self.send_away_email(msg, note)

    def send_away_email(self, msg: dict, note: str):
        if mail_notify.away_mode_active() and self.cfg.get("notify_email"):
            self.pending_emails[msg["id"]] = time.time()
            self.run_mail(mail_notify.send_permission_email,
                          self.cfg["notify_email"], msg["id"],
                          msg.get("tool", "?"), msg.get("text", ""), note)

    # ---- 离开模式(邮件审批) ----
    def run_mail(self, fn, *args):
        worker = MailWorker(fn, *args)
        worker.failed.connect(lambda e: self.chat.append("Loki", f"(邮件操作失败: {e})"))
        if fn is mail_notify.check_replies:
            worker.done.connect(self.on_mail_decisions)
        worker.start()
        self._mail_workers = [w for w in self._mail_workers if w.isRunning()]
        self._mail_workers.append(worker)

    def poll_mail_replies(self):
        if not mail_notify.away_mode_active() or not self.pending_emails:
            return
        # 清掉超过 15 分钟的过期请求(桥接端也已超时)
        now = time.time()
        self.pending_emails = {k: v for k, v in self.pending_emails.items()
                               if now - v < 900}
        if self.pending_emails:
            self.run_mail(mail_notify.check_replies, self.cfg["notify_email"],
                          list(self.pending_emails), min(self.pending_emails.values()))

    def on_mail_decisions(self, decisions):
        for rid, decision in (decisions or {}).items():
            REPLIES.mkdir(parents=True, exist_ok=True)
            (REPLIES / f"{rid}.json").write_text(
                json.dumps({"decision": decision}), encoding="utf-8")
            self.pending_emails.pop(rid, None)
            if decision == "temp":
                self.set_temp_auth(True)
            if self.chat.pending_id == rid:
                self.chat.pending_id = None
                self.chat.approve_bar.hide()
            tips = {"allow": "已按邮件回复放行", "deny": "已按邮件回复拒绝",
                    "temp": f"已按邮件回复开启 {TEMP_AUTH_MINUTES} 分钟临时授权"}
            self.chat.append("Loki", f"(📧 {tips.get(decision, decision)})")

    def handle_email_command(self, arg: str):
        """聊天框 /email 命令: 查看或修改通知邮箱。"""
        if not arg:
            cur = self.cfg.get("notify_email") or "(未设置)"
            self.chat.append("Loki", f"当前通知邮箱: {cur}<br>"
                                     "输入 <code>/email 新地址</code> 即可修改~")
            return
        self.set_notify_email(arg)

    def set_notify_email(self, addr: str) -> bool:
        if not EMAIL_RE.match(addr):
            self.chat.append("Loki", f"({addr} 看起来不像邮箱地址,没有修改哦)")
            return False
        self.cfg["notify_email"] = addr
        self.save_cfg()
        self.chat.append("Loki", f"(通知邮箱已设为 {addr},我记住啦!)")
        return True

    def set_away_mode(self, enabled: bool):
        if enabled:
            if not self.cfg.get("notify_email"):
                # 延迟到右键菜单完全关闭后再弹,且用非模态置顶对话框,
                # 避免模态框被置顶宠物窗口挡住导致整个程序卡死
                QTimer.singleShot(0, self.ask_email_then_enable)
                return
            self.enable_away()
        else:
            mail_notify.AWAY_MODE.unlink(missing_ok=True)
            self.chat.append("Loki", "(离开模式已关闭)")

    def ask_email_then_enable(self):
        dlg = QInputDialog(self)
        dlg.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)
        dlg.setWindowTitle("Loki 离开模式")
        dlg.setLabelText("第一次开启离开模式,请填写接收授权邮件的常用邮箱:")
        dlg.setModal(False)  # 非模态: 即使被遮挡也不会卡死宠物

        def on_finished(result: int):
            addr = dlg.textValue().strip()
            if result and addr and self.set_notify_email(addr):
                self.enable_away()
            else:
                self.chat.append("Loki", "(没有拿到有效邮箱,离开模式没有开启;"
                                         "也可以用 <code>/email 地址</code> 先设置)")
                self.show_chat()
            dlg.deleteLater()

        dlg.finished.connect(on_finished)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def enable_away(self):
        mail_notify.AWAY_MODE.write_text(
            json.dumps({"enabled": True}), encoding="utf-8")
        self.chat.append(
            "Loki",
            f"(离开模式已开启,授权请求会发到 {self.cfg['notify_email']};"
            "聊天框输入 <code>/email 新地址</code> 可随时修改)")
        self.show_chat()

    def play_sfx(self):
        sound = self.cfg.get("stop_sound", "")
        if not sound:
            return
        path = BASE_DIR / sound
        if not path.exists():
            return
        self.sfx_player.stop()
        self.sfx_player.setSource(QUrl.fromLocalFile(str(path)))
        self.sfx_player.play()

    def show_chat(self):
        if not self.chat.isVisible():
            self.chat.follow_pet()
            self.chat.show()

    def temp_auth_active(self) -> bool:
        try:
            data = json.loads(TEMP_AUTH.read_text(encoding="utf-8-sig"))
            return time.time() < float(data.get("until", 0))
        except (OSError, ValueError):
            return False

    def set_temp_auth(self, enabled: bool):
        if enabled:
            until = time.time() + TEMP_AUTH_MINUTES * 60
            TEMP_AUTH.write_text(json.dumps({"until": until}), encoding="utf-8")
        else:
            TEMP_AUTH.unlink(missing_ok=True)

    # ---- 外观 / 表情动画 ----
    def load_appearance(self):
        name = self.cfg.get("emote", "")
        self.frames, self.frame_idx, fps = [], 0, 24.0
        if name:
            try:
                self.frames, fps = load_emote_frames(name, self.cfg["pet_width"])
            except Exception as e:  # noqa: BLE001
                print(f"加载表情 {name} 失败: {e}")
        if self.frames:
            pix = self.frames[0]
            self.anim_timer.start(max(15, int(1000 / fps)))
        else:
            self.anim_timer.stop()
            pix = QPixmap(str(SPRITE_PATH)).scaledToWidth(
                self.cfg["pet_width"], Qt.SmoothTransformation
            )
        self.label.setPixmap(pix)
        self.label.resize(pix.size())
        self.resize(pix.size())

    def anim_step(self):
        if not self.frames:
            return
        self.frame_idx = (self.frame_idx + 1) % len(self.frames)
        self.label.setPixmap(self.frames[self.frame_idx])

    def apply_emote(self, name: str):
        self.cfg["emote"] = name
        self.save_cfg()
        self.load_appearance()

    def open_studio(self):
        try:
            if self._studio is None:
                self._studio = EmoteStudio(
                    current=self.cfg.get("emote", ""),
                    shuffle_on=bool(self.cfg.get("emote_shuffle")),
                    shuffle_minutes=int(self.cfg.get("emote_shuffle_minutes", 5)),
                )
                self._studio.emote_applied.connect(self.apply_emote)
                self._studio.shuffle_changed.connect(self.on_shuffle_changed)
            self._studio.show()
            # 移到主屏中央,排除多显示器/越界坐标导致的"看不见"
            geo = self._studio.frameGeometry()
            geo.moveCenter(QApplication.primaryScreen().availableGeometry().center())
            self._studio.move(geo.topLeft())
            self._studio.raise_()
            self._studio.activateWindow()
        except Exception as e:  # noqa: BLE001
            self.chat.append("Loki", f"(表情工坊打开失败: {e})")
            self.show_chat()

    def set_backend(self, backend: str):
        self.cfg["backend"] = backend
        self.save_cfg()
        if backend == "api":
            if self.cfg.get("api_key"):
                self.chat.append("Loki", f"(已切换到自定义 API: {self.cfg['api_base']}"
                                         f" / {self.cfg['model']})")
            else:
                self.chat.append(
                    "Loki",
                    "(已切换到自定义 API,但还没配密钥~<br>"
                    "在这里输入: <code>/api 你的key [接口地址] [模型名]</code><br>"
                    "例: <code>/api sk-xxxx https://api.deepseek.com/v1 deepseek-chat</code><br>"
                    "只给 key 时默认用 DeepSeek)")
        else:
            self.chat.append("Loki", "(已切换回宿主 Agent CLI,用它的账号额度聊天)")
        self.show_chat()

    def handle_api_command(self, arg: str):
        """聊天框 /api 命令: 查看或配置自定义 API(key/地址/模型)。"""
        if not arg:
            key = self.cfg.get("api_key", "")
            masked = (key[:6] + "…" + key[-4:]) if len(key) > 12 else ("(未设置)" if not key else "***")
            self.chat.append(
                "Loki",
                f"对话后端: {self.cfg.get('backend', 'cli')}<br>"
                f"API 地址: {self.cfg.get('api_base', '')}<br>"
                f"模型: {self.cfg.get('model', '')}<br>API key: {masked}<br>"
                "修改: <code>/api 新key [接口地址] [模型名]</code>")
            return
        parts = arg.split()
        self.cfg["api_key"] = parts[0]
        if len(parts) > 1:
            self.cfg["api_base"] = parts[1]
        if len(parts) > 2:
            self.cfg["model"] = parts[2]
        self.cfg["backend"] = "api"
        self.save_cfg()
        self.chat.append("Loki", f"(自定义 API 已配置并启用: {self.cfg['api_base']}"
                                 f" / {self.cfg['model']},key 已保存在本地 config.json)")

    def set_cli_model(self, model: str):
        self.cfg["cli_model"] = model
        self.save_cfg()
        name = model or "宿主默认"
        self.chat.append("Loki", f"(聊天模型已切换为 {name})")

    def save_cfg(self):
        CONFIG_PATH.write_text(
            json.dumps(self.cfg, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---- 语音 ----
    def speak(self, text: str):
        if not self.cfg.get("tts_enabled", True):
            return
        # 去掉不适合朗读的符号(markdown、括号动作描写等)
        clean = re.sub(r"[*_`#>~\[\]]|\(.*?\)|（.*?）", "", text).strip()
        # 只剩标点/表情时没有可朗读内容,edge-tts 会报 No audio was received
        if not re.search(r"[0-9A-Za-z一-鿿]", clean):
            return
        self._tts_slot ^= 1
        self._tts_worker = TTSWorker(
            clean, self.cfg.get("tts_voice", "zh-CN-YunxiNeural"),
            self._tts_files[self._tts_slot],
        )
        self._tts_worker.ready.connect(self._play)
        self._tts_worker.failed.connect(lambda e: self.chat.append("Loki", e))
        self._tts_worker.start()

    def _play(self, path: str):
        self.player.stop()
        self.player.setSource(QUrl())  # 释放上一个文件的占用
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()

    def float_step(self):
        if self._drag_offset is not None:
            return  # 拖拽中不漂浮
        self.phase += 0.05
        dy = int(math.sin(self.phase) * 8)
        self.move(self.base_pos.x(), self.base_pos.y() + dy)
        if self.chat.isVisible():
            self.chat.follow_pet()

    # ---- 鼠标交互 ----
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.pos()
            self._moved = False

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None:
            self.move(e.globalPosition().toPoint() - self._drag_offset)
            self._moved = True

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self._moved:
                self.base_pos = self.pos()
            else:  # 单击: 切换聊天框
                if self.chat.isVisible():
                    self.chat.hide()
                else:
                    self.chat.follow_pet()
                    self.chat.show()
                    self.chat.input.setFocus()
            self._drag_offset = None
            if self.chat.isVisible():
                self.chat.follow_pet()

    def contextMenuEvent(self, e):
        menu = QMenu(self)
        studio_act = QAction("表情工坊…", menu)
        studio_act.triggered.connect(self.open_studio)
        menu.addAction(studio_act)
        auth_act = QAction(f"自动帮按 Yes({TEMP_AUTH_MINUTES}分钟)", menu)
        auth_act.setCheckable(True)
        auth_act.setChecked(self.temp_auth_active())
        auth_act.toggled.connect(self.set_temp_auth)
        menu.addAction(auth_act)
        away_act = QAction("离开模式(邮件审批)", menu)
        away_act.setCheckable(True)
        away_act.setChecked(mail_notify.away_mode_active())
        away_act.toggled.connect(self.set_away_mode)
        menu.addAction(away_act)
        # 对话后端: 宿主 agent CLI(默认) / 用户自备的便宜 API(DeepSeek 等)
        backend_menu = menu.addMenu("对话后端")
        cur_backend = self.cfg.get("backend", "cli")
        for label, value in (("宿主 Agent(默认)", "cli"),
                             ("自定义 API(DeepSeek 等)", "api")):
            act = QAction(label, backend_menu)
            act.setCheckable(True)
            act.setChecked(value == cur_backend)
            act.triggered.connect(lambda _=False, v=value: self.set_backend(v))
            backend_menu.addAction(act)
        # 聊天模型选择(仅 cli 后端): 闲聊用便宜模型,省宿主额度
        model_menu = menu.addMenu("聊天模型(宿主后端)")
        current = self.cfg.get("cli_model", "")
        for label, value in (("Haiku(最省)", "haiku"), ("Sonnet(推荐)", "sonnet"),
                             ("Opus(贵)", "opus"), ("跟随宿主默认", "")):
            act = QAction(label, model_menu)
            act.setCheckable(True)
            act.setChecked(value == current)
            act.triggered.connect(lambda _=False, v=value: self.set_cli_model(v))
            model_menu.addAction(act)
        tts_act = QAction("语音朗读", menu)
        tts_act.setCheckable(True)
        tts_act.setChecked(self.cfg.get("tts_enabled", True))
        tts_act.toggled.connect(self.toggle_tts)
        menu.addAction(tts_act)
        quit_act = QAction("退出", menu)
        quit_act.triggered.connect(QApplication.instance().quit)
        menu.addAction(quit_act)
        menu.exec(e.globalPos())

    def toggle_tts(self, enabled: bool):
        self.cfg["tts_enabled"] = enabled
        if not enabled:
            self.player.stop()
        self.save_cfg()


def main():
    # 宠物以隐藏进程运行,未捕获异常写入日志便于排查
    import traceback
    err_log = Path.home() / ".loki-pet" / "pet_error.log"

    def excepthook(tp, val, tb):
        err_log.parent.mkdir(parents=True, exist_ok=True)
        with open(err_log, "a", encoding="utf-8") as f:
            f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            traceback.print_exception(tp, val, tb, file=f)

    sys.excepthook = excepthook
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    if not SPRITE_PATH.exists():
        print(f"缺少角色图: {SPRITE_PATH}")
        sys.exit(1)
    pet = PetWindow(load_config())
    pet.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
