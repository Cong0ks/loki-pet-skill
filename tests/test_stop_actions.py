import unittest

import pet


class StopActionTests(unittest.TestCase):
    def test_short_stop_does_not_play_sound_or_notify(self):
        actions = pet.stop_actions(duration=30, threshold=120, seconds_since_last=999)

        self.assertFalse(actions["play_sound"])
        self.assertFalse(actions["notify"])

    def test_long_stop_plays_sound_and_notifies(self):
        actions = pet.stop_actions(duration=180, threshold=120, seconds_since_last=999)

        self.assertTrue(actions["play_sound"])
        self.assertTrue(actions["notify"])

    def test_cooldown_suppresses_sound_and_notification(self):
        actions = pet.stop_actions(duration=180, threshold=120, seconds_since_last=10)

        self.assertFalse(actions["play_sound"])
        self.assertFalse(actions["notify"])

    def test_agent_label_uses_codex_when_present(self):
        self.assertEqual(pet.agent_label({"agent": "codex"}), "Codex")
        self.assertEqual(pet.agent_label({"agent": "claude"}), "Claude")

    def test_approval_voice_prompt_uses_agent(self):
        self.assertEqual(
            pet.approval_voice_prompt({"agent": "codex"}),
            "你的 Codex 在找你",
        )
        self.assertEqual(
            pet.approval_voice_prompt({"agent": "claude"}),
            "你的 Claude 在找你",
        )


if __name__ == "__main__":
    unittest.main()
