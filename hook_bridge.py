# -*- coding: utf-8 -*-
"""
Claude Code hook 桥接 — 把权限请求/通知转发给 Loki 桌宠,支持宠物端帮按 Yes。

在 ~/.claude/settings.json 的 hooks 里配置(见 README):
  PreToolUse        → python hook_bridge.py --event pretooluse
                      (只做临时授权快速放行,永不阻塞——它对每条命令都触发)
  PermissionRequest → python hook_bridge.py --event permissionrequest
                      (只在真正弹授权提示时触发,阻塞等待宠物端点击)
  Notification      → python hook_bridge.py --event notification
  Stop              → python hook_bridge.py --event stop

与宠物通过 ~/.loki-pet/ 下的文件队列通信:
  heartbeat        宠物每 5 秒刷新,判断宠物是否在线
  temp_auth.json   临时授权(含到期时间戳),生效期间 PreToolUse 直接放行
  inbox/*.json     发给宠物的消息(权限请求/通知)
  replies/*.json   宠物写回的批准结果
仅用标准库,不依赖 Qt。
"""
import json
import sys
import time
import uuid
from pathlib import Path

BRIDGE_DIR = Path.home() / ".loki-pet"
INBOX = BRIDGE_DIR / "inbox"
REPLIES = BRIDGE_DIR / "replies"
TEMP_AUTH = BRIDGE_DIR / "temp_auth.json"
HEARTBEAT = BRIDGE_DIR / "heartbeat"
AWAY_MODE = BRIDGE_DIR / "away_mode.json"

WAIT_SECONDS = 300       # 等待宠物端点击的时长(5 分钟),超时回落到终端授权
AWAY_WAIT_SECONDS = 900  # 离开模式(邮件审批): 等邮件回复,最长 15 分钟


def away_mode_active() -> bool:
    try:
        data = json.loads(AWAY_MODE.read_text(encoding="utf-8-sig"))
        return bool(data.get("enabled"))
    except (OSError, ValueError):
        return False


def pet_alive() -> bool:
    try:
        return time.time() - HEARTBEAT.stat().st_mtime < 15
    except OSError:
        return False


def temp_auth_active() -> bool:
    try:
        data = json.loads(TEMP_AUTH.read_text(encoding="utf-8-sig"))
        return time.time() < float(data.get("until", 0))
    except (OSError, ValueError):
        return False


def send(msg: dict):
    INBOX.mkdir(parents=True, exist_ok=True)
    path = INBOX / f"{msg['id']}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(msg, ensure_ascii=False), encoding="utf-8")
    tmp.rename(path)  # 原子落盘,避免宠物读到半个文件


def decide(event: str, decision: str, reason: str):
    if event == "pretooluse":
        out = {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }}
    else:  # permissionrequest: canUseTool 形状的 decision
        d = {"behavior": decision}
        if decision == "deny":
            d["message"] = reason
        out = {"hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": d,
        }}
    print(json.dumps(out, ensure_ascii=False))


def handle_permission_request(payload: dict):
    """只在 Claude Code 真正要弹授权提示时被调用: 转给宠物,阻塞等点击。"""
    if temp_auth_active():
        decide("permissionrequest", "allow", "Loki 临时授权生效中")
        return
    if not pet_alive():
        return  # 宠物不在线: 不干预,走正常终端授权

    tool_input = payload.get("tool_input") or {}
    detail = str(tool_input.get("command") or tool_input.get("file_path")
                 or json.dumps(tool_input, ensure_ascii=False))[:150]
    msg_id = uuid.uuid4().hex[:12]
    send({"id": msg_id, "type": "permission", "ts": time.time(),
          "tool": payload.get("tool_name", "?"), "text": detail})

    reply_path = REPLIES / f"{msg_id}.json"
    wait = AWAY_WAIT_SECONDS if away_mode_active() else WAIT_SECONDS
    deadline = time.time() + wait
    while time.time() < deadline:
        if reply_path.exists():
            try:
                decision = json.loads(
                    reply_path.read_text(encoding="utf-8")).get("decision")
            except (OSError, ValueError):
                decision = None
            try:
                reply_path.unlink()
            except OSError:
                pass
            if decision in ("allow", "temp"):
                decide("permissionrequest", "allow", "Loki 宠物端批准")
            elif decision == "deny":
                decide("permissionrequest", "deny", "Loki 宠物端拒绝")
            return  # ignore → 无输出,走终端授权
        time.sleep(0.3)
    # 超时: 通知宠物撤回该请求,回落到终端授权
    send({"id": uuid.uuid4().hex[:12], "type": "cancel",
          "ref": msg_id, "ts": time.time()})


def main():
    event = ""
    if "--event" in sys.argv:
        event = sys.argv[sys.argv.index("--event") + 1]
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        payload = {}

    if event == "pretooluse":
        # 对每条命令都会触发,因此只做临时授权快速放行,绝不阻塞
        if temp_auth_active():
            decide("pretooluse", "allow", "Loki 临时授权生效中")
    elif event == "permissionrequest":
        handle_permission_request(payload)
    elif event == "notification" and pet_alive():
        send({"id": uuid.uuid4().hex[:12], "type": "notify", "ts": time.time(),
              "text": str(payload.get("message", "Claude 在等你哦"))[:200]})
    elif event == "promptsubmit":
        # 记录本轮开始时间,供 stop 事件计算轮次耗时
        sid = str(payload.get("session_id", "unknown"))[:32]
        turns = BRIDGE_DIR / "turns"
        turns.mkdir(parents=True, exist_ok=True)
        (turns / f"{sid}.txt").write_text(str(time.time()), encoding="utf-8")
        # 记录最近活跃会话的工作目录,供宠物"计划任务续跑"定位项目
        cwd = payload.get("cwd")
        if cwd:
            (BRIDGE_DIR / "last_session.json").write_text(
                json.dumps({"cwd": str(cwd), "ts": time.time()},
                           ensure_ascii=False), encoding="utf-8")
    elif event == "stop" and pet_alive():
        # 计算本轮耗时: 只有长任务才值得打扰用户(由宠物按阈值过滤)
        sid = str(payload.get("session_id", "unknown"))[:32]
        turn_file = BRIDGE_DIR / "turns" / f"{sid}.txt"
        duration = -1.0
        try:
            duration = time.time() - float(turn_file.read_text(encoding="utf-8"))
            turn_file.unlink()
        except (OSError, ValueError):
            pass
        send({"id": uuid.uuid4().hex[:12], "type": "stop", "ts": time.time(),
              "duration": round(duration), "text": "Claude 任务完成啦!"})


if __name__ == "__main__":
    main()
