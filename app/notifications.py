import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)


SUCCESS_STATUSES = {'SUCCESS', 'PREFLIGHT_OK'}


def _env_int(name, default, minimum=1):
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        log.warning('Invalid %s value; using %d.', name, default)
        return default


def _notification_text(summary, report_path=None):
    counts = {
        'succeeded': sum(item.get('status') in SUCCESS_STATUSES for item in summary),
        'failed': sum(item.get('status') == 'FAILED' for item in summary),
        'dry_run': sum(item.get('status') == 'DRY_RUN' for item in summary),
    }
    message = (f"Anaplan backup finished: {counts['succeeded']} succeeded, "
               f"{counts['failed']} failed, {counts['dry_run']} dry-run.")
    failed = [item for item in summary if item.get('status') == 'FAILED']
    limit = _env_int('ANAPLAN_NOTIFICATION_FAILURE_LIMIT', 5)
    if failed:
        details = []
        for item in failed[:limit]:
            target = ' / '.join(filter(None, (
                str(item.get('workspace') or '').strip(),
                str(item.get('model') or '').strip()))) or 'unknown target'
            error = ' '.join(str(item.get('error') or 'unknown error').split())
            details.append(f'- {target}: {error[:240]}')
        message += '\nFailed models:\n' + '\n'.join(details)
        if len(failed) > limit:
            message += f'\n- and {len(failed) - limit} more'
    if report_path:
        message += f'\nReport: {Path(report_path)}'
    return message, counts


def _policy_allows(policy, failures, successes, force):
    if force:
        return True
    normalized = policy.strip().lower()
    if normalized in ('off', 'none', 'false'):
        return False
    if normalized in ('failure', 'failures', 'failure_only'):
        return failures > 0
    if normalized in ('success', 'success_only'):
        return failures == 0 and successes > 0
    if normalized not in ('always', 'all'):
        log.warning('Unknown ANAPLAN_NOTIFICATION_POLICY=%r; using always.', policy)
    return True


def _native_notification(message):
    if sys.platform == 'darwin' and os.getenv('ANAPLAN_NOTIFY_MACOS', 'false').lower() == 'true':
        script = 'display notification ' + json.dumps(message[:1000]) + ' with title "Anaplan Backup"'
        return 'macos', ['osascript', '-e', script]
    if sys.platform == 'win32' and os.getenv('ANAPLAN_NOTIFY_WINDOWS', 'false').lower() == 'true':
        script = (
            'Add-Type -AssemblyName System.Windows.Forms;'
            '$n=New-Object System.Windows.Forms.NotifyIcon;'
            '$n.Icon=[System.Drawing.SystemIcons]::Information;'
            "$n.BalloonTipTitle='Anaplan Backup';"
            '$n.BalloonTipText=$env:ANAPLAN_NOTIFICATION_TEXT;'
            '$n.Visible=$true;$n.ShowBalloonTip(5000);Start-Sleep -Seconds 6;$n.Dispose()')
        return 'windows', ['powershell.exe', '-NoProfile', '-Command', script]
    return None, None


def notify(summary, message_override=None, report_path=None, force=False):
    message, counts = _notification_text(summary, report_path)
    if message_override:
        message = message_override
    policy = os.getenv('ANAPLAN_NOTIFICATION_POLICY', 'always')
    if not _policy_allows(policy, counts['failed'], counts['succeeded'], force):
        log.info('Notification skipped by policy %r.', policy)
        return []

    deliveries = []
    channel, command = _native_notification(message)
    if command:
        environment = os.environ.copy()
        environment['ANAPLAN_NOTIFICATION_TEXT'] = message[:1000]
        try:
            completed = subprocess.run(
                command, check=False, timeout=10, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, env=environment)
            delivery = {'channel': channel, 'delivered': completed.returncode == 0,
                        'attempts': 1}
            if completed.returncode:
                delivery['error'] = f'notification command exited {completed.returncode}'
            deliveries.append(delivery)
        except (FileNotFoundError, subprocess.SubprocessError) as exc:
            log.warning('Could not send the %s backup notification: %s', channel, exc)
            deliveries.append({'channel': channel, 'delivered': False,
                               'attempts': 1, 'error': str(exc)})

    webhook = os.getenv('ANAPLAN_NOTIFICATION_WEBHOOK', '').strip()
    if webhook:
        attempts = _env_int('ANAPLAN_NOTIFICATION_RETRY_ATTEMPTS', 3)
        timeout = _env_int('ANAPLAN_NOTIFICATION_TIMEOUT_SECONDS', 15)
        delay = _env_int('ANAPLAN_NOTIFICATION_RETRY_DELAY_SECONDS', 2, minimum=0)
        payload = {'text': message, 'summary': summary, 'counts': counts,
                   'report': str(report_path) if report_path else None}
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                requests.post(webhook, json=payload, timeout=timeout).raise_for_status()
                deliveries.append({'channel': 'webhook', 'delivered': True,
                                   'attempts': attempt})
                break
            except requests.RequestException as exc:
                last_error = exc
                if attempt < attempts:
                    log.warning('Backup notification webhook attempt %d/%d failed: %s',
                                attempt, attempts, exc)
                    if delay:
                        time.sleep(delay)
        else:
            log.warning('Backup notification webhook failed after %d attempts: %s',
                        attempts, last_error)
            deliveries.append({'channel': 'webhook', 'delivered': False,
                               'attempts': attempts, 'error': str(last_error)})
    return deliveries
