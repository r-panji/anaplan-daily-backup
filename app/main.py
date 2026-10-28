import argparse
import asyncio
import json
import logging
import os
import stat
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from anaplan_api import AnaplanAPI
from backup import enabled_targets, plan_archive_names
from browser import AnaplanBrowser, ArchiveOperationError, FatalPageError
from config import ConfigError, load_config
from health import run_health_check
from notifications import notify
from runtime import SingleRunLock, cleanup_old_files

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
load_dotenv(PROJECT_ROOT / ".env")

handlers = [logging.StreamHandler(), RotatingFileHandler(
    LOG_DIR / "backup.log",
    maxBytes=int(os.getenv("LOG_MAX_BYTES", "5242880")),
    backupCount=int(os.getenv("LOG_BACKUP_COUNT", "5")),
)]
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
log = logging.getLogger("anaplan-backup")


def _target_key(target):
    return (target.workspace_id.lower() or target.workspace.lower(),
            target.model_id.lower() or target.model.lower())


def _selected(target, only_model=None, only_workspace=None, retry_keys=None,tags=None):
    if only_model and only_model.lower() not in (target.model.lower(), target.model_id.lower()):
        return False
    if only_workspace and only_workspace.lower() not in (target.workspace.lower(), target.workspace_id.lower()):
        return False
    if retry_keys is not None and _target_key(target) not in retry_keys:
        return False
    if tags:
        requested={tag.strip().casefold() for tag in tags if tag.strip()}
        target_tags={tag.casefold() for tag in target.tags}
        if requested and requested.isdisjoint(target_tags):
            return False
    return True


def retry_keys_from_report(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read retry report {path}: {exc}") from None
    if not isinstance(payload, list):
        raise RuntimeError("Retry report must contain a JSON list of backup results.")
    keys = set()
    skipped = []
    for result in payload:
        if isinstance(result, dict) and result.get("status") == "FAILED":
            state = result.get("submission_state")
            error = str(result.get("error") or "").lower()
            if state in ("submitted_unverified", "confirmed") or (
                    state is None and ("was submitted" in error or "could not be verified" in error)):
                skipped.append(str(result.get("model") or result.get("model_id") or "unknown model"))
                continue
            workspace = str(result.get("workspace_id") or result.get("workspace") or "").lower()
            model = str(result.get("model_id") or result.get("model") or "").lower()
            if workspace and model:
                keys.add((workspace, model))
    if not keys:
        if skipped:
            raise RuntimeError(
                "The retry report contains no failures that are safe to repeat. Inspect Anaplan "
                f"for submitted or unverified archives: {', '.join(skipped)}."
            )
        raise RuntimeError("The retry report contains no failed targets.")
    if skipped:
        log.warning("Skipping submitted or unverified failures during retry: %s", ", ".join(skipped))
    return keys


def _check_env_permissions():
    path = PROJECT_ROOT / ".env"
    if os.name != "nt" and path.exists() and path.stat().st_mode & (stat.S_IRGRP | stat.S_IROTH):
        log.warning("%s can be read by other users. Run: chmod 600 %s", path, path)


def _apply_retention(preview=False):
    reports = int(os.getenv("REPORT_RETENTION_DAYS", "90"))
    health_reports = int(os.getenv("HEALTH_REPORT_RETENTION_DAYS", str(reports)))
    diagnostics = int(os.getenv("DIAGNOSTIC_RETENTION_DAYS", "14"))
    keep_latest = max(0, int(os.getenv("RETENTION_KEEP_LATEST_REPORTS", "10")))
    policies = [
        cleanup_old_files(LOG_DIR, "backup_results_*.json", reports,
                          keep_latest=keep_latest, preview=preview),
        cleanup_old_files(LOG_DIR, "health_check_*.json", health_reports,
                          keep_latest=keep_latest, preview=preview),
        cleanup_old_files(LOG_DIR / "diagnostics", "*", diagnostics,
                          preview=preview),
    ]
    candidate_count = sum(len(item['candidates']) for item in policies)
    removed_count = sum(len(item['removed']) for item in policies)
    error_count = sum(len(item['errors']) for item in policies)
    action = 'would remove' if preview else 'removed'
    log.info("Retention %s %d file(s); %d error(s).", action,
             candidate_count if preview else removed_count, error_count)
    for policy in policies:
        for path in policy['candidates'] if preview else policy['removed']:
            log.info("Retention %s: %s", 'candidate' if preview else 'removed', path)
        for error in policy['errors']:
            log.warning("Retention could not process %s: %s",
                        error['path'], error['error'])
    return {'preview': preview, 'candidate_count': candidate_count,
            'removed_count': removed_count, 'error_count': error_count,
            'policies': policies}


def _monitor_storage(api, targets):
    if os.getenv("ANAPLAN_STORAGE_MONITOR", "false").lower() != "true":
        return
    threshold = float(os.getenv("ANAPLAN_STORAGE_WARNING_PERCENT", "85"))
    checked = set()
    for target in targets:
        if not target.workspace_id or target.workspace_id in checked:
            continue
        checked.add(target.workspace_id)
        try:
            usage = api.workspace_usage(target.workspace_id)
            if usage is None:
                log.warning("Workspace storage usage is unavailable for %s; backup will continue.", target.workspace)
            elif usage["percent"] >= threshold:
                log.warning("Workspace %s storage usage is %.2f%% (warning threshold %.2f%%).",
                            target.workspace, usage["percent"], threshold)
            else:
                log.info("Workspace %s storage usage is %.2f%%.", target.workspace, usage["percent"])
        except Exception as exc:
            log.warning("Could not read storage usage for %s: %s", target.workspace, exc)


async def run_backup(cfg, force_dry_run=False, test_copy=False, live=False, preflight=False,
                     only_model=None, only_workspace=None, retry_keys=None,tags=None):
    targets = [target for target in enabled_targets(cfg)
               if _selected(target, only_model, only_workspace, retry_keys,tags)]
    if not targets:
        raise RuntimeError("No enabled models matched the requested selection.")
    if test_copy and len(targets) != 1:
        raise RuntimeError("--test-copy requires exactly ONE selected enabled model.")
    dry_run = force_dry_run or (not (test_copy or live or preflight)
                                and bool(cfg.get("backup", {}).get("dry_run", True)))
    api = AnaplanAPI()
    resolved = []
    results = []
    seen = set()
    for target in targets:
        try:
            target = api.resolve(target)
            if not dry_run and not (target.workspace_id and target.model_id):
                raise RuntimeError("Live backup and preflight require workspace_id and model_id.")
            key = _target_key(target)
            if key in seen:
                log.warning("Skipping duplicate target: %s / %s", target.workspace, target.model)
                continue
            seen.add(key)
            resolved.append(target)
        except Exception as exc:
            results.append({"status": "FAILED", "workspace": target.workspace,
                            "model": target.model, "error": str(exc)})
            log.exception("Target resolution failed for %s / %s", target.workspace, target.model)

    browser = AnaplanBrowser(PROJECT_ROOT)
    lock = SingleRunLock(Path(os.getenv("BACKUP_LOCK_FILE", str(LOG_DIR / "backup.lock"))))
    locked = False
    try:
        run_time = datetime.now(ZoneInfo(cfg.get("timezone", "Asia/Jakarta")))
        plans = plan_archive_names(
            resolved,
            cfg.get("backup", {}).get("suffix_format", "_[BACKUP]_%Y%m%d_%H%M%S"),
            run_time,
        )
        for target, name in plans:
            log.info("Archive name preview: workspace=%r model=%r archive=%r",
                     target.workspace, target.model, name)
        if resolved and not dry_run:
            lock.acquire()
            locked = True
            _monitor_storage(api, resolved)
            await browser.start()
            await browser.ensure_authenticated()
        for target, name in plans:
            try:
                if preflight:
                    result = await browser.preflight_target(target)
                else:
                    result = await browser.copy_and_archive(
                        target, name, dry_run=dry_run, test_copy=test_copy)
            except FatalPageError as exc:
                results.append({"status": "FAILED", "workspace": target.workspace,
                                "workspace_id": target.workspace_id, "model": target.model,
                                "model_id": target.model_id, "archive": name, "error": str(exc)})
                log.error("Fatal Anaplan page detected. Stopping this run; the browser will close.")
                raise
            except Exception as exc:
                result = {"status": "FAILED", "workspace": target.workspace,
                          "workspace_id": target.workspace_id, "model": target.model,
                          "model_id": target.model_id, "archive": name, "error": str(exc),
                          "submission_state": getattr(exc,"submission_state","not_submitted")}
                log.exception("Operation failed for %s / %s; continuing with next target",
                              target.workspace, target.model)
            results.append(result)
            log.info("Backup result: %s", result)
    finally:
        try:
            await browser.stop()
        finally:
            if locked:
                lock.release()
            report = LOG_DIR / f"backup_results_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
            report.write_text(json.dumps(results, indent=2), encoding="utf-8")
            log.info("Backup summary: %d succeeded, %d failed, %d dry-run; report: %s",
                     sum(r.get("status") in ("SUCCESS", "PREFLIGHT_OK") for r in results),
                     sum(r.get("status") == "FAILED" for r in results),
                     sum(r.get("status") == "DRY_RUN" for r in results), report)
            _apply_retention()
            try:
                deliveries = notify(results, report_path=report)
                for delivery in deliveries:
                    log.info("Notification channel=%s delivered=%s attempts=%s",
                             delivery["channel"], delivery["delivered"],
                             delivery.get("attempts", 1))
            except Exception:
                log.exception("Unexpected notification failure; backup result is unchanged.")
    return results


async def _scheduled_run(config_path):
    try:
        cfg = load_config(config_path)
        await run_backup(cfg)
    except Exception:
        log.exception("Scheduled backup run failed.")


async def async_main(args):
    config_path = Path(os.getenv("CONFIG_PATH", str(PROJECT_ROOT / "config" / "models.yaml")))
    cfg = load_config(config_path)
    _check_env_permissions()
    if args.check_config:
        log.info("Configuration is valid: %s", config_path)
        return []
    if args.retention_preview or args.retention_cleanup:
        result = _apply_retention(preview=args.retention_preview)
        if result['error_count']:
            raise RuntimeError(
                f"Retention completed with {result['error_count']} file error(s).")
        return []
    if args.health_check:
        results,report=await run_health_check(
            cfg,PROJECT_ROOT,LOG_DIR,args.only_model,args.only_workspace,
            args.tag,args.test_notification)
        for result in results:
            log.info("Health check %-7s %-22s %s",result['status'],result['check'],result['message'])
        log.info("Health-check report: %s",report)
        _apply_retention()
        return results
    retry_keys = retry_keys_from_report(args.retry_failed) if args.retry_failed else None
    common = {"only_model": args.only_model, "only_workspace": args.only_workspace,
              "retry_keys": retry_keys,"tags": args.tag}
    if args.test_copy:
        return await run_backup(cfg, test_copy=True, **common)
    if args.live or args.retry_failed:
        return await run_backup(cfg, live=True, **common)
    if args.preflight:
        return await run_backup(cfg, preflight=True, **common)
    if args.run_once or args.dry_run:
        return await run_backup(cfg, force_dry_run=args.dry_run, **common)
    schedule = cfg.get("schedule", {})
    scheduler = AsyncIOScheduler(timezone=cfg.get("timezone", "Asia/Jakarta"))
    scheduler.add_job(_scheduled_run, "cron", hour=schedule.get("hour", 1),
                      minute=schedule.get("minute", 0), args=[config_path], max_instances=1)
    scheduler.start()
    log.info("Scheduler started: daily %02d:%02d %s", schedule.get("hour", 1),
             schedule.get("minute", 0), cfg.get("timezone"))
    await asyncio.Event().wait()


def parse_args():
    parser = argparse.ArgumentParser(description="Anaplan Daily Backup for macOS and Windows")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--live", action="store_true", help="LIVE: back up selected enabled models once")
    group.add_argument("--run-once", action="store_true")
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--test-copy", action="store_true", help="LIVE: Copy & Archive exactly one selected model")
    group.add_argument("--preflight", action="store_true", help="Check login, access, and Model Management without copying")
    group.add_argument("--check-config", action="store_true", help="Validate configuration and exit")
    group.add_argument("--retention-preview", action="store_true", help="List expired local artifacts without deleting them")
    group.add_argument("--retention-cleanup", action="store_true", help="Delete expired local reports and diagnostics")
    group.add_argument("--health-check", action="store_true", help="Check local setup, browser, login, and model access without copying")
    group.add_argument("--retry-failed", metavar="REPORT", help="Retry FAILED targets from a JSON report")
    parser.add_argument("--only-model", help="Select one exact model name or model ID")
    parser.add_argument("--only-workspace", help="Select one exact workspace name or workspace ID")
    parser.add_argument("--tag", action="append", default=[], help="Select models with this tag; repeat to match any selected tag")
    parser.add_argument("--test-notification", action="store_true", help="Send a test notification during --health-check")
    args=parser.parse_args()
    if args.test_notification and not args.health_check:
        parser.error("--test-notification requires --health-check")
    return args


def main():
    try:
        results = asyncio.run(async_main(parse_args()))
    except (ConfigError, RuntimeError, FatalPageError) as exc:
        log.error("%s", exc)
        return 2
    return 1 if any(result.get("status") == "FAILED" for result in results) else 0


if __name__ == "__main__":
    sys.exit(main())
