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
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import edge_tts
import requests
from PySide6.QtCore import QPoint, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu,
    QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

import mail_notify
from emote_studio import EmoteStudio, load_emote_frames

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
SPRITE_PATH = BASE_DIR / "assets" / "loki.png"

# 与 Claude Code hooks 的文件队列桥接目录(见 hook_bridge.py)
BRIDGE_DIR = Path.home() / ".loki-pet"
INBOX = BRIDGE_DIR / "inbox"
REPLIES = BRIDGE_DIR / "replies"
TEMP_AUTH = BRIDGE_DIR / "temp_auth.json"
HEARTBEAT = BRIDGE_DIR / "heartbeat"
TEMP_AUTH_MINUTES = 15

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
    # Claude 任务完成时播放的音效(相对本目录;空串关闭)
    "stop_sound": "assets/sounds/task_end.mp3",
    # 离开模式的通知邮箱(经 agently-cli 发送,回复 yes/no/15min 即远程授权)
    # 首次开启离开模式时弹框填写并记住;聊天框输入 /email 新地址 可随时修改
    "notify_email": "",
}

EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")


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
        self.setFixedSize(300, 260)

        box = QWidget(self)
        box.setGeometry(0, 0, 300, 260)
        box.setStyleSheet(
            "background: rgba(25,25,35,235); border-radius: 12px;"
        )
        layout = QVBoxLayout(box)
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

    def show_approval(self, msg: dict):
        self.append("Claude", f'想执行 <code>{msg["tool"]}: {msg["text"]}</code>')
        self.pending_id = msg["id"]
        self.approve_bar.show()

    def cancel_approval(self, ref: str):
        if self.pending_id == ref:
            self.pending_id = None
            self.approve_bar.hide()
            self.append("Loki", "(等太久啦,这条请求回终端处理咯)")

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
        # 本地命令: /email 查看或修改离开模式通知邮箱,不发给 AI
        if text.startswith("/email"):
            self.input.clear()
            self.pet.handle_email_command(text[len("/email"):].strip())
            return
        if self.worker and self.worker.isRunning():
            return
        self.input.clear()
        self.append("我", text)
        self.pet.history.append({"role": "user", "content": text})

        cfg = self.pet.cfg
        msgs = [{"role": "system", "content": cfg["system_prompt"]}]
        msgs += self.pet.history[-cfg["max_history"]:]
        self.worker = ChatWorker(cfg, msgs)
        self.worker.finished_ok.connect(self.on_reply)
        self.worker.failed.connect(lambda e: self.append("Loki", e))
        self.worker.start()

    def on_reply(self, text: str):
        self.pet.history.append({"role": "assistant", "content": text})
        self.append("Loki", text)
        self.pet.speak(text)

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
        self._mail_workers: list = []
        self.mail_timer = QTimer(self)
        self.mail_timer.timeout.connect(self.poll_mail_replies)
        self.mail_timer.start(60000)

    # ---- Claude Code hook 桥接 ----
    def poll_inbox(self):
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
            if mail_notify.away_mode_active() and self.cfg.get("notify_email"):
                self.pending_emails[msg["id"]] = time.time()
                self.run_mail(mail_notify.send_permission_email,
                              self.cfg["notify_email"], msg["id"],
                              msg.get("tool", "?"), msg.get("text", ""))
        elif kind == "cancel":
            self.chat.cancel_approval(msg.get("ref", ""))
            self.pending_emails.pop(msg.get("ref", ""), None)
        elif kind == "notify":
            self.chat.append("Claude", msg.get("text", ""))
            self.show_chat()
            self.speak("Claude 在叫你啦!")
        elif kind == "stop":
            self.chat.append("Claude", msg.get("text", ""))
            self.show_chat()  # 任务完成只弹泡泡,不朗读,避免频繁打扰
            self.play_sfx()
            if mail_notify.away_mode_active() and self.cfg.get("notify_email"):
                self.run_mail(mail_notify.send_notify_email,
                              self.cfg["notify_email"], "任务完成",
                              msg.get("text", "Claude 任务完成啦!"))

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
        if self._studio is None:
            self._studio = EmoteStudio(current=self.cfg.get("emote", ""))
            self._studio.emote_applied.connect(self.apply_emote)
        self._studio.show()
        self._studio.raise_()
        self._studio.activateWindow()

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
        # 聊天模型选择(仅 cli 后端): 闲聊用便宜模型,省宿主额度
        model_menu = menu.addMenu("聊天模型")
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
