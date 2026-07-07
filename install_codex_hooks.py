# -*- coding: utf-8 -*-
"""安装 Loki Pet 的 Codex hooks,只合并 ~/.codex/hooks.json,不触碰 Claude hooks。"""
import json
import sys
from pathlib import Path


def _command(script: Path) -> str:
    return f'python "{script}" --agent codex'


def _hook(script: Path, status: str, timeout: int = 600) -> dict:
    cmd = _command(script)
    return {
        "type": "command",
        "command": cmd,
        "commandWindows": cmd,
        "timeout": timeout,
        "statusMessage": status,
    }


def build_hooks_config(skill_dir: Path) -> dict:
    script = skill_dir.resolve() / "codex_hook_bridge.py"
    return {
        "hooks": {
            "PermissionRequest": [
                {
                    "matcher": "*",
                    "hooks": [
                        _hook(script, "Waiting for Loki approval", timeout=900)
                    ],
                }
            ],
            "UserPromptSubmit": [
                {
                    "hooks": [
                        _hook(script, "Notifying Loki of prompt", timeout=30)
                    ],
                }
            ],
            "PostCompact": [
                {
                    "matcher": "*",
                    "hooks": [
                        _hook(script, "Saving Loki handoff", timeout=60)
                    ],
                }
            ],
            "Stop": [
                {
                    "hooks": [
                        _hook(script, "Notifying Loki of completion", timeout=30)
                    ],
                }
            ],
        }
    }


def _hook_key(hook: dict) -> tuple:
    return (
        hook.get("type", ""),
        hook.get("commandWindows") or hook.get("command") or "",
    )


def merge_hooks(existing: dict, addition: dict) -> dict:
    merged = dict(existing or {})
    merged_hooks = {
        event: list(groups)
        for event, groups in (merged.get("hooks") or {}).items()
    }
    for event, groups in addition["hooks"].items():
        target_groups = merged_hooks.setdefault(event, [])
        existing_keys = {
            _hook_key(hook)
            for group in target_groups
            for hook in group.get("hooks", [])
        }
        for group in groups:
            new_hooks = [
                hook for hook in group.get("hooks", [])
                if _hook_key(hook) not in existing_keys
            ]
            if not new_hooks:
                continue
            cloned = dict(group)
            cloned["hooks"] = new_hooks
            target_groups.append(cloned)
            existing_keys.update(_hook_key(hook) for hook in new_hooks)
    merged["hooks"] = merged_hooks
    return merged


def install(skill_dir: Path, codex_home: Path | None = None) -> Path:
    codex_home = codex_home or Path.home() / ".codex"
    codex_home.mkdir(parents=True, exist_ok=True)
    hooks_path = codex_home / "hooks.json"
    if hooks_path.exists():
        data = json.loads(hooks_path.read_text(encoding="utf-8-sig"))
    else:
        data = {}
    merged = merge_hooks(data, build_hooks_config(skill_dir))
    hooks_path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return hooks_path


def main():
    skill_dir = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent
    hooks_path = install(skill_dir)
    print(f"Codex hooks installed: {hooks_path}")
    print("在 Codex 里运行 /hooks 审核并 trust 新 hooks 后生效。")


if __name__ == "__main__":
    main()
