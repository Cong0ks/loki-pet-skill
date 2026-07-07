import unittest
from pathlib import Path

import pet


class AgentModelTests(unittest.TestCase):
    def test_codex_models_default_to_gpt5_4mini(self):
        choices = pet.recommended_cli_models("codex exec")

        self.assertEqual(choices[0], ("GPT-5.4 Mini(最省)", "gpt5.4mini"))
        self.assertIn(("跟随宿主默认", ""), choices)

    def test_claude_models_keep_cheap_first(self):
        choices = pet.recommended_cli_models("claude -p")

        self.assertEqual(choices[0], ("Haiku(最省)", "haiku"))
        self.assertEqual(choices[-1], ("跟随宿主默认", ""))

    def test_unknown_agent_only_follows_host_default(self):
        self.assertEqual(
            pet.recommended_cli_models("custom-agent"),
            [("跟随宿主默认", "")],
        )

    def test_invalid_model_for_agent_falls_back_to_cheapest(self):
        self.assertEqual(
            pet.normalize_cli_model("codex exec", "sonnet"),
            "gpt5.4mini",
        )
        self.assertEqual(
            pet.normalize_cli_model("codex exec", ""),
            "",
        )

    def test_cli_model_arg_matches_agent(self):
        self.assertEqual(
            pet.build_cli_command("claude -p", "haiku"),
            "claude -p --model haiku",
        )
        self.assertEqual(
            pet.build_cli_command("codex exec", "gpt5.4mini"),
            "codex exec --model gpt5.4mini",
        )
        self.assertEqual(
            pet.build_cli_command("gemini -p", "gemini-2.5-flash"),
            "gemini -p --model gemini-2.5-flash",
        )
        self.assertEqual(
            pet.build_cli_command("custom-agent", "anything"),
            "custom-agent",
        )

    def test_codex_skill_path_migrates_old_claude_defaults(self):
        cfg = {
            "backend": "cli",
            "cli_command": "claude -p",
            "cli_model": "sonnet",
        }

        pet.normalize_cli_settings(
            cfg,
            base_dir=Path("H:/loki/.codex/skills/loki-pet"),
            environ={},
        )

        self.assertEqual(cfg["cli_command"], "codex exec")
        self.assertEqual(cfg["cli_model"], "gpt5.4mini")

    def test_explicit_non_default_claude_command_is_not_migrated(self):
        cfg = {
            "backend": "cli",
            "cli_command": "claude --continue -p",
            "cli_model": "sonnet",
        }

        pet.normalize_cli_settings(
            cfg,
            base_dir=Path("H:/loki/.codex/skills/loki-pet"),
            environ={},
        )

        self.assertEqual(cfg["cli_command"], "claude --continue -p")
        self.assertEqual(cfg["cli_model"], "sonnet")


if __name__ == "__main__":
    unittest.main()
