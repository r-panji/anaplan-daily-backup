import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

try:
    from anaplan_api import AnaplanAPI
    from backup import enabled_targets
    from browser import AnaplanBrowser, FatalPageError
    from credentials import load_credentials
    from notifications import notify
    from runtime import SingleRunLock
except ModuleNotFoundError:
    from .anaplan_api import AnaplanAPI
    from .backup import enabled_targets
    from .browser import AnaplanBrowser, FatalPageError
    from .credentials import load_credentials
    from .notifications import notify
    from .runtime import SingleRunLock


def check_result(check,status,message,**extra):
    result={'check':check,'status':status,'message':message}
    result.update(extra)
    return result


def local_health_checks(root:Path,log_dir:Path):
    results=[]
    email,password=load_credentials()
    auto_login=os.getenv('ANAPLAN_BROWSER_AUTO_LOGIN','true').lower()=='true'
    if auto_login and not email:
        results.append(check_result(
            'credentials','FAILED',
            'ANAPLAN_BROWSER_AUTO_LOGIN is enabled but ANAPLAN_EMAIL is empty.'))
    elif auto_login and not password:
        results.append(check_result(
            'credentials','WARN',
            'Email is configured; password is empty, so SSO or manual authentication may be required.'))
    else:
        results.append(check_result(
            'credentials','PASS',
            'Browser authentication settings are present.' if auto_login
            else 'Automatic browser login is disabled; interactive login will be used.'))

    try:
        log_dir.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix='health_',dir=log_dir):
            pass
        results.append(check_result('log_directory','PASS',f'Log directory is writable: {log_dir}'))
    except OSError as exc:
        results.append(check_result('log_directory','FAILED',f'Log directory is not writable: {exc}'))

    minimum_mb=max(1,int(os.getenv('HEALTH_MIN_FREE_MB','500')))
    free_mb=shutil.disk_usage(root).free//(1024*1024)
    status='PASS' if free_mb>=minimum_mb else 'FAILED'
    results.append(check_result(
        'disk_space',status,
        f'{free_mb:,} MB free; minimum required by HEALTH_MIN_FREE_MB is {minimum_mb:,} MB.',
        free_mb=free_mb,minimum_mb=minimum_mb))

    webhook=bool(os.getenv('ANAPLAN_NOTIFICATION_WEBHOOK','').strip())
    macos=(os.getenv('ANAPLAN_NOTIFY_MACOS','false').lower()=='true' and os.sys.platform=='darwin')
    windows=(os.getenv('ANAPLAN_NOTIFY_WINDOWS','false').lower()=='true' and os.sys.platform=='win32')
    if webhook or macos or windows:
        channels=', '.join(name for name,enabled in (
            ('webhook',webhook),('macOS',macos),('Windows',windows)) if enabled)
        results.append(check_result('notification_config','PASS',f'Configured channels: {channels}.'))
    else:
        results.append(check_result(
            'notification_config','WARN','No notification channel is configured.'))
    return results


async def run_health_check(cfg,root:Path,log_dir:Path,only_model=None,
                           only_workspace=None,tags=None,test_notification=False):
    results=[check_result('configuration','PASS','Configuration loaded and validated.')]
    results.extend(local_health_checks(root,log_dir))
    targets=[]
    api=AnaplanAPI()
    for target in enabled_targets(cfg):
        if only_model and only_model.lower() not in (target.model.lower(),target.model_id.lower()):
            continue
        if only_workspace and only_workspace.lower() not in (
                target.workspace.lower(),target.workspace_id.lower()):
            continue
        if tags:
            requested={tag.strip().casefold() for tag in tags if tag.strip()}
            target_tags={tag.casefold() for tag in target.tags}
            if requested and requested.isdisjoint(target_tags):
                continue
        try:
            resolved=api.resolve(target)
            if not (resolved.workspace_id and resolved.model_id):
                raise RuntimeError('workspace_id and model_id are required for the live health check.')
            targets.append(resolved)
        except Exception as exc:
            results.append(check_result(
                'target_config','FAILED',str(exc),workspace=target.workspace,model=target.model))
    if not targets:
        results.append(check_result('targets','FAILED','No enabled models matched the health check.'))

    browser=AnaplanBrowser(root)
    lock=SingleRunLock(Path(os.getenv('BACKUP_LOCK_FILE',str(log_dir/'backup.lock'))))
    locked=False
    browser_started=False
    if targets and not any(item['status']=='FAILED' and item['check']=='credentials' for item in results):
        try:
            lock.acquire()
            locked=True
            await browser.start()
            browser_started=True
            results.append(check_result('browser_start','PASS','Playwright Chromium opened successfully.'))
            await browser.ensure_authenticated()
            results.append(check_result('authentication','PASS','Anaplan authentication completed.'))
            for target in targets:
                try:
                    await browser.preflight_target(target)
                    results.append(check_result(
                        'model_access','PASS','Model Management is accessible.',
                        workspace=target.workspace,model=target.model))
                except FatalPageError:
                    raise
                except Exception as exc:
                    results.append(check_result(
                        'model_access','FAILED',str(exc),
                        workspace=target.workspace,model=target.model))
        except Exception as exc:
            check='browser_start' if not browser_started else 'authentication'
            results.append(check_result(check,'FAILED',str(exc)))
        finally:
            try:
                await browser.stop()
            finally:
                if locked:
                    lock.release()

    if test_notification:
        deliveries=notify([],message_override='Anaplan backup health-check notification test.',
                          force=True)
        if not deliveries:
            results.append(check_result(
                'notification_delivery','FAILED','No notification channel is configured.'))
        for delivery in deliveries:
            results.append(check_result(
                f"notification_{delivery['channel']}",
                'PASS' if delivery['delivered'] else 'FAILED',
                'Test notification delivered.' if delivery['delivered']
                else f"Test notification failed: {delivery.get('error','unknown error')}"))

    report=log_dir/f"health_check_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
    report.write_text(json.dumps(results,indent=2),encoding='utf-8')
    return results,report
