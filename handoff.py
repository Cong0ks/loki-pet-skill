# -*- coding: utf-8 -*-
"""
会话断点档案 — 本地集中存储各项目的交接快照。

存储位置: ~/.loki-pet/handoffs/<项目名-路径哈希>/<时间>_<来源>.md
不写入任何项目目录;每个项目滚动保留最近 KEEP_SNAPSHOTS 份,除非用户
手动清理(/resume clear 或直接删目录)。
来源: compact = 宿主压缩时白捡的官方摘要; session = 会话结束时便宜模型提炼。
"""
import hashlib
import shutil
import time
from pathlib import Path

HANDOFF_DIR = Path.home() / ".loki-pet" / "handoffs"
KEEP_SNAPSHOTS = 10


def project_key(cwd: str) -> str:
    name = Path(cwd).name or "project"
    digest = hashlib.md5(str(cwd).lower().encode("utf-8")).hexdigest()[:8]
    return f"{name}-{digest}"


def save_snapshot(cwd: str, text: str, source: str) -> Path:
    d = HANDOFF_DIR / project_key(cwd)
    d.mkdir(parents=True, exist_ok=True)
    (d / "cwd.txt").write_text(str(cwd), encoding="utf-8")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = d / f"{stamp}_{source}.md"
    header = (f"# 交接快照 {time.strftime('%Y-%m-%d %H:%M')} (来源: {source})\n"
              f"项目: {cwd}\n\n")
    path.write_text(header + text.strip() + "\n", encoding="utf-8")
    snaps = sorted(d.glob("*_*.md"))
    for old in snaps[:-KEEP_SNAPSHOTS]:
        old.unlink(missing_ok=True)
    return path


def list_projects() -> list:
    """各项目最新快照概览,按时间倒序: [{key, cwd, mtime, path, preview}]"""
    out = []
    if not HANDOFF_DIR.exists():
        return out
    for d in HANDOFF_DIR.iterdir():
        if not d.is_dir():
            continue
        snaps = sorted(d.glob("*_*.md"))
        if not snaps:
            continue
        latest = snaps[-1]
        try:
            cwd = (d / "cwd.txt").read_text(encoding="utf-8").strip()
        except OSError:
            cwd = ""
        preview = ""
        for line in latest.read_text(encoding="utf-8").splitlines()[3:]:
            s = line.strip("#*- ").strip()
            if s:
                preview = s[:60]
                break
        out.append({"key": d.name, "cwd": cwd, "path": latest,
                    "mtime": latest.stat().st_mtime, "preview": preview})
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


def latest_text(key: str) -> str:
    snaps = sorted((HANDOFF_DIR / key).glob("*_*.md"))
    return snaps[-1].read_text(encoding="utf-8") if snaps else ""


def clear_all() -> int:
    n = 0
    if HANDOFF_DIR.exists():
        for d in HANDOFF_DIR.iterdir():
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)
                n += 1
    return n
