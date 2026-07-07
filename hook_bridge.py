# -*- coding: utf-8 -*-
"""
Agent hook 桥接 — 把权限请求/通知转发给 Loki 桌宠,支持宠物端帮按 Yes。

在 ~/.claude/settings.json 的 hooks 里配置(见 README):
  PreToolUse        → python hook_bridge.py --event pretooluse
                      (只做临时授权快速放行,永不阻塞——它对每条命令都触发)
  PermissionRequest → python hook_bridge.py --event permissionrequest
                      (只在真正弹授权提示时触发,阻塞等待宠物端点击)
  Notification      → python hook_bridge.py --event notification
  Stop              → python hook_bridge.py --event stop

Codex 使用 install_codex_hooks.py 生成 ~/.codex/hooks.json,入口为
codex_hook_bridge.py。Claude 与 Codex 共用 ~/.loki-pet/ 文件队列,但各自的
hook 配置互不覆盖。

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


EVENT_ALIASES = {
    "permissionrequest": "permissionrequest",
    "pretooluse": "pretooluse",
    "notification": "notification",
    "stop": "stop",
    "postcompact": "postcompact",
    "sessionend": "sessionend",
    "promptsubmit": "promptsubmit",
    "userpromptsubmit": "promptsubmit",
}


def resolve_event(argv: list[str], payload: dict) -> str:
    """兼容 Claude 的 --event 参数和 Codex 的 hook_event_name 字段。"""
    event = ""
    if "--event" in argv:
        idx = argv.index("--event")
        if idx + 1 < len(argv):
            event = argv[idx + 1]
    if not event:
        event = str(payload.get("hook_event_name", ""))
    normalized = event.replace("_", "").replace("-", "").lower()
    return EVENT_ALIASES.get(normalized, normalized)


def permission_detail(payload: dict) -> str:
    """提取 Claude/Codex 权限请求里最适合展示给用户的详情。"""
    tool_input = payload.get("tool_input") or {}
    detail = (
        tool_input.get("command")
        or tool_input.get("file_path")
        or tool_input.get("description")
        or json.dumps(tool_input, ensure_ascii=False)
    )
    return str(detail)[:150]


def build_permission_message(payload: dict, agent: str, msg_id: str, now: float) -> dict:
    """构造发给宠物端的授权请求消息。"""
    return {
        "id": msg_id,
        "type": "permission",
        "ts": now,
        "agent": agent,
        "tool": payload.get("tool_name", "?"),
        "text": permission_detail(payload),
    }


def agent_name(argv: list[str], payload: dict) -> str:
    if "--agent" in argv:
        idx = argv.index("--agent")
        if idx + 1 < len(argv):
            return argv[idx + 1].strip().lower()
    if payload.get("hook_event_name"):
        return "codex"
    return "claude"


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


def handle_permission_request(payload: dict, agent: str = "claude"):
    """真正要弹授权提示时被调用: 转给宠物,阻塞等点击。"""
    if temp_auth_active():
        decide("permissionrequest", "allow", "Loki 临时授权生效中")
        return
    if not pet_alive():
        return  # 宠物不在线: 不干预,走正常终端授权

    msg_id = uuid.uuid4().hex[:12]
    send(build_permission_message(payload, agent, msg_id, time.time()))

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


def forward_handoff(event: str, payload: dict):
    """压缩/会话结束时把断点档案素材转发给宠物(宠物负责存档与提炼)。"""
    cwd = str(payload.get("cwd") or "")
    if not cwd:
        return
    if event == "postcompact":
        # 宿主压缩时自带摘要,白捡存档,零模型成本(字段名做多版本兼容)
        for key in ("summary", "compact_summary", "compactSummary"):
            val = payload.get(key)
            if val:
                send({"id": uuid.uuid4().hex[:12], "type": "handoff_summary",
                      "cwd": cwd, "text": str(val)[:8000], "ts": time.time()})
                return
    # 拿不到现成摘要(或 sessionend): 给出会话记录路径,由宠物提炼
    tp = payload.get("transcript_path")
    if tp and Path(tp).exists() and Path(tp).stat().st_size > 30000:
        send({"id": uuid.uuid4().hex[:12], "type": "handoff_session",
              "cwd": cwd, "transcript": str(tp), "ts": time.time()})


def main():
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        payload = {}
    event = resolve_event(sys.argv, payload)
    agent = agent_name(sys.argv, payload)

    if event == "pretooluse":
        # 对每条命令都会触发,因此只做临时授权快速放行,绝不阻塞
        if temp_auth_active():
            decide("pretooluse", "allow", "Loki 临时授权生效中")
    elif event == "permissionrequest":
        handle_permission_request(payload, agent)
    elif event in ("postcompact", "sessionend") and pet_alive():
        forward_handoff(event, payload)
    elif event == "notification" and pet_alive():
        label = "Codex" if agent == "codex" else "Claude"
        send({"id": uuid.uuid4().hex[:12], "type": "notify", "ts": time.time(),
              "agent": agent,
              "text": str(payload.get("message", f"{label} 在等你哦"))[:200]})
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
              "agent": agent,
              "duration": round(duration),
              "text": f"{'Codex' if agent == 'codex' else 'Claude'} 任务完成啦!"})


if __name__ == "__main__":
    main()
