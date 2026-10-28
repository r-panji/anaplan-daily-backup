import unittest
from datetime import datetime

from app.backup import (
    ArchiveNameError,
    MAX_ARCHIVE_NAME_LENGTH,
    ModelTarget,
    backup_name,
    plan_archive_names,
)
from app.config import ConfigError, validate_config


class ArchiveNameTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 27, 12, 34, 56)
        self.suffix = "_[BACKUP]_%Y%m%d_%H%M%S"

    def test_name_is_deterministic_and_limited_to_anaplan_maximum(self):
        name = backup_name("A" * 80, self.suffix, self.now)
        self.assertEqual(len(name), MAX_ARCHIVE_NAME_LENGTH)
        self.assertTrue(name.endswith("_[BACKUP]_20261027_123456"))

    def test_suffix_must_leave_room_for_model_name(self):
        with self.assertRaisesRegex(ArchiveNameError, "shorter than 60"):
            backup_name("Model", "X" * 60, self.now)

    def test_batch_collision_in_same_workspace_is_rejected(self):
        targets = [
            ModelTarget("Workspace", "A" * 70, "workspace-id", "model-1"),
            ModelTarget("Workspace", "A" * 69 + "B", "workspace-id", "model-2"),
        ]
        with self.assertRaisesRegex(ArchiveNameError, "collision"):
            plan_archive_names(targets, self.suffix, self.now)

    def test_same_generated_name_is_allowed_in_different_workspaces(self):
        targets = [
            ModelTarget("One", "Model", "workspace-1", "model-1"),
            ModelTarget("Two", "Model", "workspace-2", "model-2"),
        ]
        plans = plan_archive_names(targets, self.suffix, self.now)
        self.assertEqual(plans[0][1], plans[1][1])

    def test_config_rejects_suffix_that_cannot_produce_safe_name(self):
        cfg = {
            "backup": {
                "suffix_format": "X" * 60,
                "models": [{
                    "workspace_name": "Workspace",
                    "model_name": "Model",
                    "enabled": True,
                }],
            }
        }
        with self.assertRaisesRegex(ConfigError, "suffix_format"):
            validate_config(cfg)


if __name__ == "__main__":
    unittest.main()
