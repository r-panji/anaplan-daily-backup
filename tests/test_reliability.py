import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from app.config import ConfigError, load_config, validate_config
from app.credentials import load_credentials
from app.runtime import SingleRunLock, cleanup_old_files, remove_old_files

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import main


def valid_config():
    return {
        "timezone": "Asia/Jakarta",
        "schedule": {"hour": 1, "minute": 0},
        "backup": {"models": [{
            "workspace_name": "Workspace",
            "workspace_id": "A" * 32,
            "model_name": "Model",
            "model_id": "B" * 32,
            "enabled": True,
        }]},
    }


class ReliabilityTests(unittest.TestCase):
    def test_configuration_validation(self):
        self.assertEqual(validate_config(valid_config())["timezone"], "Asia/Jakarta")
        cfg = valid_config()
        cfg["schedule"]["hour"] = 25
        with self.assertRaisesRegex(ConfigError, "schedule.hour"):
            validate_config(cfg)

    def test_configuration_validates_model_tags(self):
        cfg = valid_config()
        cfg["backup"]["models"][0]["tags"] = "daily"
        with self.assertRaisesRegex(ConfigError, "tags must be a YAML list"):
            validate_config(cfg)
        cfg["backup"]["models"][0]["tags"] = ["Daily", "daily"]
        with self.assertRaisesRegex(ConfigError, "duplicate tag"):
            validate_config(cfg)

    def test_configuration_reports_bad_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.yaml"
            path.write_text("backup: [", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "Invalid YAML"):
                load_config(path)

    def test_single_run_lock_rejects_second_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = SingleRunLock(Path(tmp) / "backup.lock")
            second = SingleRunLock(Path(tmp) / "backup.lock")
            first.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    second.acquire()
            finally:
                first.release()

    def test_retry_report_selects_only_failed_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.json"
            report.write_text(json.dumps([
                {"status": "SUCCESS", "workspace_id": "one", "model_id": "a"},
                {"status": "FAILED", "workspace_id": "two", "model_id": "b"},
            ]), encoding="utf-8")
            self.assertEqual(main.retry_keys_from_report(report), {("two", "b")})

    def test_retry_report_skips_submitted_unverified_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.json"
            report.write_text(json.dumps([
                {"status": "FAILED", "workspace_id": "one", "model_id": "a",
                 "model": "Unsafe", "submission_state": "submitted_unverified"},
                {"status": "FAILED", "workspace_id": "two", "model_id": "b",
                 "model": "Safe", "submission_state": "not_submitted"},
            ]), encoding="utf-8")
            self.assertEqual(main.retry_keys_from_report(report), {("two", "b")})

    def test_retry_report_rejects_when_every_failure_may_have_submitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.json"
            report.write_text(json.dumps([
                {"status": "FAILED", "workspace_id": "one", "model_id": "a",
                 "model": "Unsafe", "submission_state": "submitted_unverified"},
            ]), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "no failures that are safe"):
                main.retry_keys_from_report(report)

    def test_keychain_is_used_when_env_password_is_empty(self):
        completed = Mock(stdout="secret\n")
        env = {"ANAPLAN_EMAIL": "user@example.com", "ANAPLAN_PASSWORD": "",
               "ANAPLAN_KEYCHAIN_SERVICE": "anaplan-backup"}
        with patch.dict(os.environ, env, clear=True), patch("subprocess.run", return_value=completed) as run:
            self.assertEqual(load_credentials(), ("user@example.com", "secret"))
            run.assert_called_once()

    def test_retention_removes_expired_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.json"
            path.write_text("{}", encoding="utf-8")
            os.utime(path, (1, 1))
            self.assertEqual(remove_old_files(Path(tmp), "*.json", 1), 1)
            self.assertFalse(path.exists())

    def test_retention_preview_does_not_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.json"
            path.write_text("{}", encoding="utf-8")
            os.utime(path, (1, 1))
            result = cleanup_old_files(Path(tmp), "*.json", 1, preview=True)
            self.assertEqual(result['candidates'], [str(path)])
            self.assertEqual(result['removed'], [])
            self.assertTrue(path.exists())

    def test_retention_preserves_configured_latest_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            files = []
            for index in range(3):
                path = directory / f"report_{index}.json"
                path.write_text("{}", encoding="utf-8")
                os.utime(path, (index + 1, index + 1))
                files.append(path)
            result = cleanup_old_files(directory, "report_*.json", 1,
                                       keep_latest=2, now=200000)
            self.assertEqual(result['removed'], [str(files[0])])
            self.assertFalse(files[0].exists())
            self.assertTrue(files[1].exists())
            self.assertTrue(files[2].exists())

    def test_retention_ignores_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            target = directory / "target.txt"
            target.write_text("keep", encoding="utf-8")
            link = directory / "old.json"
            link.symlink_to(target)
            result = cleanup_old_files(directory, "*.json", 0, now=200000)
            self.assertEqual(result['removed'], [])
            self.assertTrue(target.exists())
            self.assertTrue(link.exists())

    def test_main_returns_failure_for_failed_result(self):
        operation = object()
        with patch.object(main, "parse_args"), patch.object(
                main, "async_main", new=Mock(return_value=operation)), patch.object(
                main.asyncio, "run", return_value=[{"status": "FAILED"}]) as run:
            self.assertEqual(main.main(), 1)
            run.assert_called_once_with(operation)


class PreflightTests(unittest.IsolatedAsyncioTestCase):
    async def test_preflight_does_not_copy(self):
        browser = AsyncMock()
        browser.preflight_target.return_value = {"status": "PREFLIGHT_OK"}
        with tempfile.TemporaryDirectory() as tmp, patch.object(main, "LOG_DIR", Path(tmp)), \
                patch.object(main, "AnaplanBrowser", return_value=browser):
            results = await main.run_backup(valid_config(), preflight=True)
            self.assertEqual(results[0]["status"], "PREFLIGHT_OK")
            browser.preflight_target.assert_awaited_once()
            browser.copy_and_archive.assert_not_awaited()
