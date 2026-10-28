# Anaplan Daily Backup

Back up enabled models sequentially, in the same workspace or across workspaces,
using Anaplan's browser Copy & Archive flow.

This community project is licensed under the MIT License. It is not affiliated
with or endorsed by Anaplan. Test with non-production models first and follow
your organization's access, retention, and security policies.

For architecture, configuration reference, operating procedures, scheduling,
and troubleshooting, see [Project documentation](docs/PROJECT_DOCUMENTATION.md).

Formatted Word and PDF copies can be generated locally with
`tools/build_project_document.py`; generated files under `output/` are not
committed.

## Setup

macOS:

```bash
./setup.sh
```

Windows Command Prompt:

```bat
setup.bat
run.bat --check-config
run.bat --dry-run
```

The commands and configuration are the same on both platforms. On Windows,
replace `./run.sh` with `run.bat` in the examples below.

Configure `.env` with your regional `ANAPLAN_HOME_URL`, `ANAPLAN_EMAIL`, and
`ANAPLAN_PASSWORD`. Automatic browser login selects Anaplan login, fills email,
clicks Continue, and submits the password. SSO/MFA may require interaction.
Set `ANAPLAN_BROWSER_AUTO_LOGIN=false` for manual login. The persistent browser
profile reuses valid sessions. `LOGIN_TIMEOUT_MS` defaults to 180000;
`UI_TIMEOUT_MS` defaults to 20000.

For macOS Keychain, leave `ANAPLAN_PASSWORD` empty, set
`ANAPLAN_KEYCHAIN_SERVICE=anaplan-daily-backup`, and save the password once:

```bash
security add-generic-password -U -s anaplan-daily-backup -a "your@email.com" -w
```

## Models

Create your local target configuration before the first run. It is ignored by
Git because it can contain internal workspace and model identifiers:

```bash
cp config/models.example.yaml config/models.yaml
```

On Windows:

```bat
copy config\models.example.yaml config\models.yaml
```

Add entries under `backup.models` in `config/models.yaml`:

```yaml
timezone: Asia/Jakarta
schedule:
  hour: 1
  minute: 0
backup:
  dry_run: true
  suffix_format: "_[BACKUP]_%Y%m%d_%H%M%S"
  models:
    - workspace_name: "Workspace A"
      workspace_id: "YOUR_WORKSPACE_ID"
      model_name: "Model A"
      model_id: "YOUR_MODEL_ID"
      tags: [daily, production]
      enabled: true
    - workspace_name: "Workspace B"
      workspace_id: "ANOTHER_WORKSPACE_ID"
      model_name: "Model B"
      model_id: "ANOTHER_MODEL_ID"
      tags: [weekly, development]
      enabled: true
```

Replace placeholders with real IDs. Repeat a workspace ID for models in the
same workspace. Live targets must have both IDs; the browser account needs
Workspace Administrator access. Supplied IDs select the exact model link;
API discovery is used to resolve missing IDs only when `ANAPLAN_AUTH_MODE=basic`.

## Run

```bash
./run.sh --dry-run     # Preview all enabled targets without opening a browser
./run.sh --live        # LIVE: back up all enabled targets once
./run.sh --test-copy   # LIVE: requires exactly one enabled model
./run.sh --run-once    # Run once using backup.dry_run from YAML
./run.sh --check-config # Validate YAML, IDs, timezone, and schedule
./run.sh --preflight    # Check login, model access, and Model Management
./run.sh --health-check # Full local, browser, login, and model-access checklist
./run.sh               # Schedule using backup.dry_run and schedule from YAML
```

On Windows, use the same options with `run.bat`. The health check creates no
archive and writes `logs/health_check_<timestamp>.json`. It reports
configuration, credentials, log-directory access, free disk space, notification
configuration, browser startup, authentication, and access to every selected
model. Limit it with `--only-model` or `--only-workspace` when needed.

Send an explicit notification test with:

```bash
./run.sh --health-check --test-notification
```

This flag sends through every configured notification channel. A normal health
check only reports whether a channel is configured.

Limit a run by exact name or ID:

```bash
./run.sh --live --only-model "Model A"
./run.sh --preflight --only-workspace "Workspace A"
./run.sh --retry-failed logs/backup_results_YYYYMMDD_HHMMSS_ffffff.json
./run.sh --dry-run --tag daily
./run.sh --live --tag production
```

Tags are optional and case-insensitive. Repeat `--tag` to match any of several
groups, for example `--tag daily --tag weekly`. Tag selection can be combined
with `--only-model`, `--only-workspace`, or `--retry-failed`. Models without a
matching tag are skipped.

`--retry-failed` selects only `FAILED` targets from the report. It is a live
operation. Targets marked `submitted_unverified` are skipped because repeating
them could create another archive. Inspect those targets directly in Anaplan.
If every failure may already have been submitted, the retry command exits
without opening the browser.

`--live` overrides `backup.dry_run` for that run. To enable scheduled live backups,
set `backup.dry_run: false`. Keep it true until your model list is ready.
No schedule is installed automatically. On macOS, `install-launchd.sh` installs
the launch agent. On Windows, this installs an interactive daily task at 01:00:

```bat
install-scheduled-task.bat
```

Pass another 24-hour time when needed, for example
`install-scheduled-task.bat 02:30`. Remove it with
`uninstall-scheduled-task.bat`. Scheduled browser runs require the user to be
logged in on both platforms.

Each model gets a timestamped archive name in the configured timezone. The
browser returns to Home between models, including after a failure, and closes
when the batch finishes. Duplicate workspace/model ID pairs are skipped.
A run now plans and logs every archive name before opening the browser. Names
longer than Anaplan's 60-character limit are shortened safely, suffixes that
leave no room for the model name are rejected, and same-workspace collisions
stop the batch before any archive is submitted. Immediately before Copy &
Archive, the browser also checks Model Management for the exact generated name
and stops that target if it already exists.
A failed model is logged and remaining models are attempted. Failed or
unverified submissions are not automatically repeated; inspect Anaplan before
rerunning them because an archive may already have been created.

Live and preflight runs use `logs/backup.lock`; a second process exits instead
of sharing the browser profile. A completed command returns exit code `1` when
any selected target failed and `0` when all selected targets succeeded. Invalid
configuration, lock contention, and fatal Anaplan pages return exit code `2`.

Archive verification polls for up to `ARCHIVE_VERIFY_TIMEOUT_MS` (10 minutes by
default). Backup and health reports are retained for 90 days and diagnostics for
14 days. At least the 10 newest reports of each type are preserved even when
they are older than the retention period. The log rotates at 5 MB with five
retained files; all limits are configurable in `.env`.

Preview local retention without deleting anything:

```bash
./run.sh --retention-preview
```

Run local cleanup immediately:

```bash
./run.sh --retention-cleanup
```

Retention applies only to managed files under `logs/`. It never deletes models
or archives in Anaplan. Configure it with `REPORT_RETENTION_DAYS`,
`HEALTH_REPORT_RETENTION_DAYS`, `DIAGNOSTIC_RETENTION_DAYS`, and
`RETENTION_KEEP_LATEST_REPORTS`.

Transient navigation failures before submission are retried safely. The default
is two attempts with a two-second delay, configured through
`ANAPLAN_SAFE_RETRY_ATTEMPTS` and `ANAPLAN_SAFE_RETRY_DELAY_SECONDS`. Once the
archive confirmation may have been submitted, the operation is never repeated
automatically. JSON reports record `submission_state` as `not_submitted`,
`submitted_unverified`, or `confirmed`.

Optional monitoring and notifications are disabled by default:

```env
ANAPLAN_STORAGE_MONITOR=true
ANAPLAN_STORAGE_WARNING_PERCENT=85
ANAPLAN_NOTIFICATION_POLICY=failure
ANAPLAN_NOTIFY_MACOS=true
ANAPLAN_NOTIFY_WINDOWS=false
ANAPLAN_NOTIFICATION_WEBHOOK=https://your-webhook
```

`ANAPLAN_NOTIFICATION_POLICY` accepts `always`, `failure`, `success`, or `off`.
Failure messages identify failed workspace/model targets, include shortened
errors, and point to the JSON report. Webhook delivery is retried three times
by default. Configure attempts, delay, and timeout with
`ANAPLAN_NOTIFICATION_RETRY_ATTEMPTS`,
`ANAPLAN_NOTIFICATION_RETRY_DELAY_SECONDS`, and
`ANAPLAN_NOTIFICATION_TIMEOUT_SECONDS`. On Windows, set
`ANAPLAN_NOTIFY_WINDOWS=true` for a native notification. Notification failures
are logged but never change the backup command's exit status.

Storage monitoring requires Basic API mode and capacity fields from the tenant.
If usage is unavailable, the backup continues and logs a warning. The project
does not delete archives automatically.

Results are logged to `logs/backup.log` and saved in
`logs/backup_results_<timestamp>.json`. UI failures save diagnostics under
`logs/diagnostics`; these may contain internal workspace/model information.
Login interaction diagnostics contain step names and flags, not credentials.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Tests use local browser fixtures and mocked batch operations, not live backups.
