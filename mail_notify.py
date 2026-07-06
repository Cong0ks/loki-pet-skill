# -*- coding: utf-8 -*-
"""
离开模式邮件桥 — 通过腾讯 agently-cli 把授权请求发到用户邮箱,并读取回复。

安全约束(邮件内容属于不可信外部输入):
  * 只解析"主题含请求编号且发件人为 notify_email"的回复
  * 回复正文只识别 yes / no / 15min 三个决定词,其余内容一律忽略
  * 发出的邮件只发给用户自己配置的地址
写操作走 CLI 的两阶段确认: 第一次拿 ctk 令牌,第二次带令牌执行。此处由代码
自动完成两步,前提是用户已通过宠物右键菜单显式开启"离开模式"。
"""
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

BRIDGE_DIR = Path.home() / ".loki-pet"
AWAY_MODE = BRIDGE_DIR / "away_mode.json"

SUBJECT_PREFIX = "[Loki授权]"
DECISIONS = {"yes": "allow", "y": "allow", "允许": "allow",
             "no": "deny", "n": "deny", "拒绝": "deny",
             "15min": "temp", "15": "temp", "临时授权": "temp"}


def away_mode_active() -> bool:
    try:
        data = json.loads(AWAY_MODE.read_text(encoding="utf-8-sig"))
        return bool(data.get("enabled"))
    except (OSError, ValueError):
        return False


_CLI = shutil.which("agently-cli") or shutil.which("agently-cli.cmd") or "agently-cli"


def _run(args: list, timeout: int = 60) -> dict:
    """执行 agently-cli,返回 stdout 的 JSON envelope;失败抛异常。"""
    proc = subprocess.run(
        [_CLI] + args, capture_output=True, text=True,
        encoding="utf-8", timeout=timeout,
    )
    out = (proc.stdout or "").strip()
    try:
        data = json.loads(out) if out else {}
    except ValueError:
        data = {}
    if proc.returncode != 0:
        msg = (data.get("error") or {}).get("message") or out or proc.stderr
        raise RuntimeError(f"agently-cli 退出 {proc.returncode}: {str(msg)[:200]}")
    return data


def _extract_ctk(exc_or_data) -> str:
    m = re.search(r"ctk_[A-Za-z0-9_\-]+", str(exc_or_data))
    return m.group(0) if m else ""


def send_mail(to: str, subject: str, body: str):
    """发送邮件,自动完成两阶段确认(离开模式下用户已显式授权此自动化)。"""
    args = ["message", "+send", "--to", to, "--subject", subject, "--body", body]
    try:
        data = _run(args)
    except RuntimeError as e:
        ctk = _extract_ctk(e)
        if not ctk:
            raise
        _run(args + ["--confirmation-token", ctk])
        return
    ctk = _extract_ctk(json.dumps(data, ensure_ascii=False))
    if ctk:  # 第一阶段返回令牌 → 第二阶段执行
        _run(args + ["--confirmation-token", ctk])


def send_permission_email(to: str, req_id: str, tool: str, detail: str):
    subject = f"{SUBJECT_PREFIX} #{req_id} Claude 请求执行 {tool}"
    body = (
        f"Claude Code 请求执行:\n\n  {tool}: {detail}\n\n"
        f"直接回复本邮件,正文第一行写下你的决定:\n"
        f"  yes   = 允许这一次\n"
        f"  no    = 拒绝\n"
        f"  15min = 允许并开启 15 分钟临时授权\n\n"
        f"(请求编号 #{req_id},15 分钟内有效;此邮件由 Loki 桌宠自动发送)"
    )
    send_mail(to, subject, body)


def send_notify_email(to: str, subject: str, body: str):
    send_mail(to, f"[Loki] {subject}", body)


def _first_decision_line(body: str) -> str:
    """取回复正文中引用块之前的第一个决定词;识别不了返回空串。"""
    for line in (body or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">") or line.startswith("在") and "写道" in line \
                or line.lower().startswith(("on ", "from:", "发件人")):
            break  # 进入引用区,停止
        word = re.split(r"[\s,，。!！:：]", line)[0].lower()
        return DECISIONS.get(word, "")
    return ""


def check_replies(to: str, pending_ids: list, since_ts: float) -> dict:
    """查收件箱中对未决请求的回复,返回 {req_id: decision}。"""
    if not pending_ids:
        return {}
    results = {}
    after = time.strftime("%Y-%m-%d", time.localtime(since_ts - 86400))
    data = _run(["message", "+list", "--dir", "inbox", "--limit", "20",
                 "--after", after])
    messages = (data.get("data") or {}).get("messages") or []
    for m in messages:
        subject = str(m.get("subject", ""))
        sender = str((m.get("from") or {}).get("address")
                     or m.get("from", ""))
        if SUBJECT_PREFIX not in subject:
            continue
        if to.lower() not in sender.lower():
            continue  # 只信任用户自己的回复
        for rid in pending_ids:
            if f"#{rid}" not in subject or rid in results:
                continue
            detail = _run(["message", "+read", "--id", m.get("id", "")])
            body = str(((detail.get("data") or {}).get("message") or {})
                       .get("body", "") or (detail.get("data") or {}).get("body", ""))
            decision = _first_decision_line(body)
            if decision:
                results[rid] = decision
    return results
