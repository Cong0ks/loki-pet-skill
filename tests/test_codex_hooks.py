import unittest
from pathlib import Path

import hook_bridge
import install_codex_hooks


class CodexHookBridgeTests(unittest.TestCase):
    def test_event_name_can_come_from_codex_payload(self):
        payload = {"hook_event_name": "PermissionRequest"}

        self.assertEqual(hook_bridge.resolve_event([], payload), "permissionrequest")

    def test_extracts_codex_permission_detail(self):
        payload = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "git status --short",
                "description": "needs approval",
            },
        }

        self.assertEqual(
            hook_bridge.permission_detail(payload),
            "git status --short",
        )

    def test_agent_name_prefers_codex_payload(self):
        self.assertEqual(
            hook_bridge.agent_name(["codex_hook_bridge.py"], {"hook_event_name": "Stop"}),
            "codex",
        )

    def test_permission_message_includes_agent(self):
        msg = hook_bridge.build_permission_message(
            {"tool_name": "Bash", "tool_input": {"command": "pwd"}},
            agent="codex",
            msg_id="abc123",
            now=123.0,
        )

        self.assertEqual(msg["agent"], "codex")
        self.assertEqual(msg["type"], "permission")
        self.assertEqual(msg["text"], "pwd")

    def test_codex_hooks_config_uses_wrapper(self):
        cfg = install_codex_hooks.build_hooks_config(Path("C:/skill/loki-pet"))

        permission_hook = cfg["hooks"]["PermissionRequest"][0]["hooks"][0]
        self.assertEqual(cfg["hooks"]["PermissionRequest"][0]["matcher"], "*")
        self.assertIn("codex_hook_bridge.py", permission_hook["commandWindows"])
        self.assertIn("--agent codex", permission_hook["commandWindows"])
        self.assertNotIn(".claude", permission_hook["commandWindows"])

    def test_merge_preserves_existing_hooks(self):
        existing = {
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "commandWindows": "python existing.py",
                            }
                        ]
                    }
                ]
            }
        }

        merged = install_codex_hooks.merge_hooks(
            existing, install_codex_hooks.build_hooks_config(Path("C:/skill/loki-pet"))
        )

        stop_commands = [
            h["commandWindows"]
            for group in merged["hooks"]["Stop"]
            for h in group["hooks"]
        ]
        self.assertIn("python existing.py", stop_commands)
        self.assertTrue(any("codex_hook_bridge.py" in c for c in stop_commands))


if __name__ == "__main__":
    unittest.main()
