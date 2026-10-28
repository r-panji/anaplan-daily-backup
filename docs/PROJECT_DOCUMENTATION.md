# Anaplan Daily Backup: Project Documentation

## 1. Purpose

This macOS and Windows project automates Anaplan's browser-based **Copy & Archive** process.
It can back up one model, every enabled model in one workspace, or enabled
models across several workspaces.

The automation:

1. Loads enabled model targets from `config/models.yaml`.
2. Resolves missing IDs through the documented Anaplan API when Basic API
   discovery is enabled.
3. Opens a persistent Chromium profile.
4. Signs in through Anaplan login when credentials are configured.
5. Opens each target using its workspace ID and model ID.
6. Opens Model Management and selects the exact model name.
7. Runs Copy & Archive, supplies a timestamped name, and confirms with OK.
8. Verifies the new archive in Model Management.
9. Writes a JSON result report and closes the browser.

Models run sequentially. A failure for one target is recorded, and processing
continues with the next enabled target.

## 2. Requirements

- macOS or Windows 10/11
- Python 3
- Network access to Anaplan
- An Anaplan account that can access every configured target
- Workspace Administrator permission for Copy & Archive
- An interactive desktop session when `HEADLESS=false`

The setup script installs Python dependencies and Playwright Chromium into a
local virtual environment.

## 3. Project layout

| Path | Purpose |
|---|---|
| `app/main.py` | Command-line entry point, batch orchestration, scheduling, and result reports |
| `app/browser.py` | Login, Anaplan UI navigation, Copy & Archive, verification, and diagnostics |
| `app/anaplan_api.py` | Optional Basic API authentication and model ID discovery |
| `app/backup.py` | Model configuration objects and archive-name generation |
| `app/config.py` | YAML configuration loader |
| `config/models.yaml` | Timezone, schedule, run mode, and model targets |
| `.env` | Local credentials and browser settings; ignored by Git |
| `.env.example` | Environment variable template |
| `.browser-profile/` | Persistent Chromium session; ignored by Git |
| `logs/` | Runtime log, JSON reports, and failure diagnostics; ignored by Git |
| `tests/` | Local browser fixtures and batch orchestration tests |
| `run.sh` | Shell entry point |
| `setup.sh` | Creates the virtual environment and installs dependencies |
| `install-launchd.sh` | Installs the macOS launch agent |
| `uninstall-launchd.sh` | Removes the macOS launch agent |
| `run.bat` | Windows Command Prompt entry point |
| `setup.bat` | Creates the Windows virtual environment and installs dependencies |
| `install-scheduled-task.bat` | Installs an interactive Windows daily task |
| `uninstall-scheduled-task.bat` | Removes the Windows daily task |

## 4. Installation

On macOS, from the project directory:

```bash
chmod +x setup.sh run.sh install-launchd.sh uninstall-launchd.sh
./setup.sh
```

The setup script:

- creates `.venv`;
- installs packages from `requirements.txt`;
- installs Playwright Chromium;
- copies `.env.example` to `.env` if `.env` does not exist;
- creates `logs/` and `.browser-profile/`.

### Windows setup step by step

Use Windows 10 or Windows 11 with a normal desktop session. The browser must be
allowed to open, and the Windows user must remain signed in during a backup that
requires SSO, MFA, or human verification.

1. Install Python 3 from `https://www.python.org/downloads/windows/`. In the
   installer, enable **Add Python to PATH** and install the Python launcher.
2. Copy or extract the project to a local directory, for example
   `C:\AnaplanBackup`. Avoid a network drive because the browser profile and run
   lock are stored inside the project directory.
3. Open the project folder in File Explorer. Select the address bar, type
   `cmd`, and press Enter. This opens Command Prompt in the correct directory.
4. Run the setup script:

```bat
setup.bat
```

The script creates `.venv`, installs the Python packages and Playwright
Chromium, creates `.env` from `.env.example` when needed, and prepares `logs`
and `.browser-profile`. If Windows reports that `py` is not recognized, repair
or reinstall Python with the launcher enabled, then reopen Command Prompt.

5. Open `.env` in Notepad:

```bat
notepad .env
```

Set the Anaplan home URL for your region and enter the login email. Enter the
password only when automatic password entry is required. Save and close the
file.

```dotenv
ANAPLAN_HOME_URL=https://id1.app.anaplan.com/home
HEADLESS=false
ANAPLAN_EMAIL=your.email@example.com
ANAPLAN_PASSWORD=your-password
ANAPLAN_BROWSER_AUTO_LOGIN=true
```

Keep `HEADLESS=false` for the first run so login, MFA, and verification pages
are visible. The `.env` file contains credentials and must not be shared.

6. Open the model configuration:

```bat
notepad config\models.yaml
```

Enter each workspace and model. Keep `backup.dry_run: true` during setup. Add
another item under `backup.models` for every additional model, including its
own workspace ID and model ID. Set `enabled: false` to temporarily skip a
target.

```yaml
backup:
  suffix_format: "_[BACKUP]_%Y%m%d_%H%M%S"
  dry_run: true
  models:
    - workspace_name: "Workspace name"
      workspace_id: "WORKSPACE_ID"
      model_name: "Model name"
      model_id: "MODEL_ID"
      enabled: true
```

7. Validate the settings without opening the browser:

```bat
run.bat --check-config
run.bat --dry-run
```

Correct every reported configuration error before continuing.

8. Check browser access without creating an archive:

```bat
run.bat --preflight
```

Complete SSO or MFA if requested. If Anaplan displays **Verify you are human**
or **Something went wrong, try again**, the program closes the browser and
returns a failure. Wait briefly and run the command again.

9. Test Copy & Archive with one enabled target:

```bat
run.bat --test-copy
```

Confirm in Anaplan that the timestamped archive exists and review the result in
the `logs` directory.

10. Run all enabled models live:

```bat
run.bat --live
```

For scheduled operation, change `backup.dry_run` to `false`, save
`config\models.yaml`, run one successful live backup manually, and then follow
the Windows scheduling steps in Section 8. `run.bat --run-once` follows the
`backup.dry_run` value in the YAML file.

For future commands on Windows, replace `./run.sh` in this guide with
`run.bat`.

## 5. Environment configuration

Edit `.env` locally. Do not commit or share this file.

```dotenv
ANAPLAN_HOME_URL=https://id1.app.anaplan.com/home
HEADLESS=false
LOGIN_TIMEOUT_MS=180000
UI_TIMEOUT_MS=20000
ARCHIVE_VERIFY_TIMEOUT_MS=600000

ANAPLAN_AUTH_MODE=browser
ANAPLAN_AUTH_URL=https://auth.anaplan.com/token/authenticate
ANAPLAN_API_BASE_URL=https://api.anaplan.com/2/0
ANAPLAN_EMAIL=your.email@example.com
ANAPLAN_PASSWORD=
ANAPLAN_KEYCHAIN_SERVICE=anaplan-daily-backup
ANAPLAN_BROWSER_AUTO_LOGIN=true

REPORT_RETENTION_DAYS=90
DIAGNOSTIC_RETENTION_DAYS=14
ANAPLAN_STORAGE_MONITOR=false
ANAPLAN_NOTIFY_MACOS=false
```

### Environment variable reference

| Variable | Default | Meaning |
|---|---|---|
| `ANAPLAN_HOME_URL` | `https://us1a.app.anaplan.com/home` | Regional Anaplan Home URL opened by the browser |
| `HEADLESS` | `false` | Runs Chromium without a visible window when set to `true` |
| `BROWSER_PROFILE` | `.browser-profile` | Optional persistent browser-profile path |
| `LOGIN_TIMEOUT_MS` | `180000` | Maximum wait for login, model loading, and Model Management |
| `UI_TIMEOUT_MS` | `20000` | Normal UI action and verification timeout |
| `ARCHIVE_VERIFY_TIMEOUT_MS` | `600000` | Maximum wait for a submitted archive to appear |
| `ANAPLAN_SAFE_RETRY_ATTEMPTS` | `2` | Maximum attempts for transient failures before archive submission |
| `ANAPLAN_SAFE_RETRY_DELAY_SECONDS` | `2` | Delay between safe pre-submission retry attempts |
| `HEALTH_MIN_FREE_MB` | `500` | Minimum free disk space required by the health check |
| `ANAPLAN_BROWSER_AUTO_LOGIN` | `true` | Enables Anaplan email/password form automation |
| `ANAPLAN_EMAIL` | empty | Email used by browser login and Basic API authentication |
| `ANAPLAN_PASSWORD` | empty | Password used by browser login and Basic API authentication |
| `ANAPLAN_KEYCHAIN_SERVICE` | empty | macOS Keychain service used when the environment password is empty |
| `ANAPLAN_AUTH_MODE` | `browser` | `browser` uses configured IDs; `basic` can discover missing IDs |
| `ANAPLAN_AUTH_URL` | Anaplan authentication endpoint | Basic API authentication URL |
| `ANAPLAN_API_BASE_URL` | Anaplan Integration API endpoint | API base URL used for model discovery |
| `CONFIG_PATH` | `config/models.yaml` | Optional path to another YAML configuration file |
| `REPORT_RETENTION_DAYS` | `90` | Days to retain JSON result reports |
| `HEALTH_REPORT_RETENTION_DAYS` | `90` | Days to retain health-check reports |
| `DIAGNOSTIC_RETENTION_DAYS` | `14` | Days to retain UI diagnostic files |
| `RETENTION_KEEP_LATEST_REPORTS` | `10` | Minimum newest backup and health reports preserved regardless of age |
| `ANAPLAN_STORAGE_MONITOR` | `false` | Enables optional Basic API workspace usage checks |
| `ANAPLAN_NOTIFICATION_POLICY` | `always` | Sends for `always`, `failure`, `success`, or disables with `off` |
| `ANAPLAN_NOTIFY_MACOS` | `false` | Enables completion notifications in macOS Notification Center |
| `ANAPLAN_NOTIFY_WINDOWS` | `false` | Enables native Windows completion notifications |
| `ANAPLAN_NOTIFICATION_WEBHOOK` | empty | Optional JSON completion-notification endpoint |
| `ANAPLAN_NOTIFICATION_RETRY_ATTEMPTS` | `3` | Maximum webhook delivery attempts |
| `ANAPLAN_NOTIFICATION_RETRY_DELAY_SECONDS` | `2` | Delay between webhook attempts |
| `ANAPLAN_NOTIFICATION_TIMEOUT_SECONDS` | `15` | Timeout for each webhook request |
| `ANAPLAN_NOTIFICATION_FAILURE_LIMIT` | `5` | Maximum failed targets detailed in one message |

### Browser login sequence

With automatic login enabled, the script performs these steps when they appear:

1. Selects **Anaplan login**.
2. Fills the visible email field from `ANAPLAN_EMAIL`.
3. Clicks **Continue** on each new email form.
4. Fills the password from `ANAPLAN_PASSWORD`.
5. Clicks **Log in** or **Sign in**.
6. Waits until an authenticated Anaplan page is ready.

External identity-provider pages are not given the stored credentials. SSO and
MFA prompts may still require interaction. Set
`ANAPLAN_BROWSER_AUTO_LOGIN=false` to handle the complete login manually.

## 6. Model configuration

Edit `config/models.yaml`:

```yaml
timezone: Asia/Jakarta

schedule:
  hour: 1
  minute: 0

backup:
  suffix_format: "_[BACKUP]_%Y%m%d_%H%M%S"
  dry_run: true
  models:
    - workspace_name: "Planning DEV"
      workspace_id: "WORKSPACE_ID_1"
      model_name: "Finance Model"
      model_id: "MODEL_ID_1"
      tags: [daily, production]
      enabled: true

    - workspace_name: "Planning DEV"
      workspace_id: "WORKSPACE_ID_1"
      model_name: "Operations Model"
      model_id: "MODEL_ID_2"
      tags: [daily, development]
      enabled: true

    - workspace_name: "Planning QA"
      workspace_id: "WORKSPACE_ID_2"
      model_name: "QA Model"
      model_id: "MODEL_ID_3"
      tags: [weekly, qa]
      enabled: true
```

Use the same `workspace_id` for multiple models in the same workspace. Use a
different workspace name and ID for models in another workspace.

### Model fields

| Field | Required for live backup | Meaning |
|---|---:|---|
| `workspace_name` | Yes | Human-readable workspace name used in logs and reports |
| `workspace_id` | Yes | Anaplan workspace ID used for exact browser navigation |
| `model_name` | Yes | Exact visible model name in Model Management |
| `model_id` | Yes | Anaplan model ID used for exact browser navigation |
| `tags` | No | Optional list used to select groups of models from commands |
| `enabled` | Yes | Only entries set to `true` are processed |

For live operation, both IDs must be present. When `ANAPLAN_AUTH_MODE=basic`,
the project can query the documented API to resolve missing IDs from names.
The match must be unique.

Duplicate workspace/model ID pairs are skipped.

### Archive names

Archive names use the configured timezone and `suffix_format`. The default:

```text
Finance Model_[BACKUP]_20260930_143045
```

The timestamp format is `YYYYMMDD_HHMMSS`. Anaplan model names are limited to
60 characters, so the original model name is shortened when required. Before
the browser opens, the program generates and logs every name for the batch. It
rejects a suffix that leaves no room for the source model name and stops the
entire batch when two models in the same workspace would produce the same
archive name.

For a live run, Model Management is checked for the exact generated archive
name immediately before Copy & Archive. If that archive already exists, the
target fails without submitting another copy. Use `--dry-run` to review every
planned name without opening the browser.

## 7. Commands

### Validate configuration

```bash
./run.sh --check-config
```

This checks the YAML structure, timezone, schedule, required names, 32-character
hexadecimal IDs, and duplicate enabled targets without opening a browser.

### Validate all enabled targets

```bash
./run.sh --dry-run
```

This does not open the browser or change Anaplan. Review every target and
generated archive name before using live mode.

### Verify access without creating an archive

```bash
./run.sh --preflight
```

This opens every selected model, enters Model Management, and selects the exact
configured model. It verifies login, model access, and Workspace Administrator
access without clicking Copy & Archive.

### Run the complete health check

```bash
./run.sh --health-check
```

On Windows:

```bat
run.bat --health-check
```

The health check creates no archive. It verifies configuration, credential
readiness, log-directory access, free disk space, notification configuration,
Chromium startup, Anaplan authentication, and Model Management access for each
selected target. The result is written to
`logs/health_check_YYYYMMDD_HHMMSS_microseconds.json`.

Use `--only-model` or `--only-workspace` to limit the targets. Notification
delivery is tested only when explicitly requested:

```bash
./run.sh --health-check --test-notification
```

That option sends a test through each configured channel. Without the option,
the health check only reports whether notifications are configured.

### Test one model

```bash
./run.sh --test-copy
```

This is a live operation. Exactly one model may be enabled. It is useful when
validating login, UI selectors, permissions, and archive verification.

### Back up all enabled models once

```bash
./run.sh --live
```

This is a live operation. It overrides `backup.dry_run` for the current run,
processes all enabled models sequentially, and closes the browser afterward.

### Select or retry targets

```bash
./run.sh --live --only-model "Model A"
./run.sh --preflight --only-workspace "Workspace A"
./run.sh --retry-failed logs/backup_results_YYYYMMDD_HHMMSS_microseconds.json
./run.sh --dry-run --tag daily
./run.sh --live --tag production
```

Selectors accept an exact configured name or ID. `--retry-failed` reads failed
workspace/model pairs from a prior report and runs only those targets as a live
operation. It skips targets marked `submitted_unverified`; inspect those targets
in Anaplan because repeating them could create another archive.

Tags are optional and case-insensitive. Repeat `--tag` to match models carrying
any selected tag, for example `--tag daily --tag weekly`. A tag filter can be
combined with workspace, model, health-check, or failed-report selection.

### Run once using the YAML mode

```bash
./run.sh --run-once
```

This follows `backup.dry_run` from `config/models.yaml`.

### Start the internal daily scheduler

```bash
./run.sh
```

The process stays running. It uses `schedule.hour`, `schedule.minute`, and the
top-level `timezone`. Each scheduled execution reloads `models.yaml`, so model
and mode changes take effect on the next run without restarting the scheduler.

## 8. Scheduling on macOS

Before scheduling, verify both commands interactively:

```bash
./run.sh --dry-run
./run.sh --live
```

To install the launch agent:

```bash
./install-launchd.sh
```

The launch agent starts `run.sh`, and the Python scheduler controls the daily
time. Its label is `com.local.anaplan-daily-backup`.

To remove it:

```bash
./uninstall-launchd.sh
```

The scheduled process must have access to a logged-in macOS desktop session
when a visible browser or interactive SSO/MFA is required. A valid persistent
browser session reduces interactive login prompts.

### Scheduling on Windows

Run this from Command Prompt to create a daily interactive task at 01:00:

```bat
install-scheduled-task.bat
```

Supply another 24-hour time as the first argument when needed:

```bat
install-scheduled-task.bat 02:30
```

The task runs `run.bat --run-once`, so `backup.dry_run` in `models.yaml`
controls whether the scheduled operation is live. Remove the task with:

```bat
uninstall-scheduled-task.bat
```

The task uses the current Windows user and interactive logon mode. The user must
be logged in when a visible browser, SSO, MFA, or human-verification page is
required. Windows Task Scheduler does not use `schedule.hour` and
`schedule.minute`; the installation time passed to the batch file controls the
Windows schedule.

## 9. Runtime behavior

For a live batch, the browser starts once and authentication runs once. Before
each model, the script returns to Anaplan Home and locates the exact target link
using its workspace and model IDs. This prevents duplicate model names in
different workspaces from selecting the wrong target.

Within each target model, the script:

1. selects **Manage models**;
2. waits for the Model Management dialog, including content inside Anaplan's
   modeling iframe;
3. selects the exact model name;
4. clicks **Copy & Archive**;
5. enters the timestamped archive name;
6. submits the operation;
7. clicks **OK** in the Copy & Archive confirmation;
8. verifies that the exact archive name appears, enabling **Show archived
   models** when needed.

The browser closes in a `finally` block after the batch, including when a model
fails.

Live and preflight runs hold `logs/backup.lock`. If another scheduled or manual
run is active, the new process exits without opening a second browser. Ordinary
model failures are recorded and the batch continues. Human-verification and
fatal Anaplan error pages stop the entire run and close the browser.

Archive verification polls for the configured
`ARCHIVE_VERIFY_TIMEOUT_MS`, which defaults to 600000 milliseconds. The script
does not submit a second archive while waiting. It also checks for an existing
exact archive name before submission and stops the target when a duplicate is
found.

## 10. Logs, reports, and diagnostics

### Runtime log

```text
logs/backup.log
```

This contains login stages, model navigation, Copy & Archive actions, results,
and tracebacks.

### Per-run JSON report

```text
logs/backup_results_YYYYMMDD_HHMMSS_microseconds.json
```

Each result has a status:

- `SUCCESS`: Copy & Archive completed and the archive name was verified.
- `FAILED`: target resolution or UI processing failed.
- `DRY_RUN`: target was evaluated without opening a browser.
- `PREFLIGHT_OK`: model access and Model Management were verified without a copy.

The report may contain workspace names, model names, IDs, archive names, and
error messages. Treat it as internal operational data.

Each live result also records `submission_state`:

- `not_submitted`: Copy & Archive is known not to have been submitted.
- `submitted_unverified`: submission may have occurred, but verification did
  not complete. Inspect Anaplan before taking another action.
- `confirmed`: the archive was submitted and verified.

### UI diagnostics

Failures during Copy & Archive save files under:

```text
logs/diagnostics/
```

Possible files include a screenshot, outer-page HTML, iframe HTML, URL, and
page title. These files can expose internal Anaplan names and IDs. Do not share
them publicly.

Login interaction problems write `logs/diagnostics/login_status.json`. It
records the failed stage and submission flags without storing form values.

### Important result behavior

The batch continues after individual failures. Always inspect the final summary
or JSON report. A failed or unverified submission is not retried automatically
because Anaplan may already have created the archive.

The command exits with status `1` after a completed batch containing failures.
Invalid configuration, lock contention, and fatal page errors exit with status
`2`. Successful runs exit with status `0`.

`backup.log` rotates at `LOG_MAX_BYTES` and keeps `LOG_BACKUP_COUNT` old files.
Backup reports, health-check reports, and diagnostics are removed after their
configured retention periods. Defaults are 5 MB, five log files, 90 days for
both report types, and 14 diagnostic days. The newest 10 backup reports and
newest 10 health reports are always preserved by default, regardless of age.
Cleanup ignores symbolic links and is restricted to managed patterns under
`logs/`.

Preview expired files without deleting them:

```bash
./run.sh --retention-preview
```

Apply cleanup immediately:

```bash
./run.sh --retention-cleanup
```

Cleanup also runs after backup and health-check commands. This local policy
never deletes Anaplan models or archived models.

## 11. Troubleshooting

### YAML parser error

Typical message:

```text
yaml.scanner.ScannerError: while scanning a quoted scalar
```

Check `config/models.yaml` for an unclosed quote, missing colon, or incorrect
indentation. Then run `./run.sh --dry-run` again.

### Email is filled but Continue is not clicked

Check `logs/backup.log` for both messages:

```text
Filled login email from ANAPLAN_EMAIL in .env.
Clicked Continue after filling email; waiting for password or SSO/MFA.
```

The automation supports successive email forms and clicks Continue once on
each new form. If Anaplan changes the page structure, use manual login by
setting `ANAPLAN_BROWSER_AUTO_LOGIN=false` and retain diagnostics for selector
maintenance.

### Login timeout

Confirm that:

- `ANAPLAN_HOME_URL` matches your Anaplan region;
- `ANAPLAN_EMAIL` and `ANAPLAN_PASSWORD` are correct;
- the account is not waiting for SSO or MFA interaction;
- `LOGIN_TIMEOUT_MS` allows enough time.

### Model cannot be opened

Confirm the workspace ID and model ID. Also confirm that the browser account
can see that exact model. Run `./run.sh --dry-run` to inspect configured IDs.

### Model Management does not appear

The account normally needs Workspace Administrator permission. Inspect the
newest screenshot and iframe HTML in `logs/diagnostics/`.

### Archive submitted but verification failed

Inspect Anaplan before rerunning. The archive may exist even when the UI did not
show it within `ARCHIVE_VERIFY_TIMEOUT_MS`. Increase that timeout if the
workspace is slow.
Do not immediately rerun a failed target without checking for a duplicate.

### One model fails in a batch

Later targets still run. Open the newest JSON report to find the failed target
and its error. Correct that target, disable models that already succeeded if
necessary, run a dry run, and then use live mode again.

### Safe retry behavior

Temporary navigation and browser failures are retried only before the archive
name is submitted. By default the program makes two attempts with a two-second
delay. Permission errors, existing archive names, fatal Anaplan pages, and
configuration errors are not retried.

After submission begins, the program never automatically repeats Copy &
Archive. An unverified result is marked `submitted_unverified`. The
`--retry-failed` command skips such targets and retries only failures known to
be `not_submitted`.

## 12. Testing

Run the complete local test suite:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The tests use local HTML fixtures and mocked batch operations. They do not
perform live Anaplan backups.

Run only browser-flow tests:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_browser_navigation.py' -v
```

Run only batch tests:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_batch.py' -v
```

## 13. Security and operational notes

- `.env`, `.browser-profile/`, and `logs/` are excluded by `.gitignore`.
- Keep `.env` readable only by the account that runs the backup.
- The program warns when `.env` is readable by the group or other users.
- On macOS, Keychain can replace the password in `.env`. Leave
  `ANAPLAN_PASSWORD` empty and set
  `ANAPLAN_KEYCHAIN_SERVICE`. Save the password with `security
  add-generic-password`; the configured email is used as the Keychain account.
- Do not commit passwords, diagnostics, result reports, or browser profiles.
- Automatic credentials are only entered on HTTPS hosts equal to
  `anaplan.com` or ending in `.anaplan.com`.
- External SSO pages are left for manual interaction.
- Use a dedicated Anaplan automation account when your access policy permits.
- Keep `backup.dry_run: true` while editing the target list.
- Verify storage capacity and archive-retention practices in each workspace.

Optional storage monitoring uses Basic API mode and warns when usage reaches
`ANAPLAN_STORAGE_WARNING_PERCENT`. Tenant responses do not always provide
capacity fields; unavailable usage produces a warning and does not block the
backup. Automatic archive deletion is not implemented.

Optional completion notifications support macOS Notification Center with
`ANAPLAN_NOTIFY_MACOS=true` and a JSON webhook with
`ANAPLAN_NOTIFICATION_WEBHOOK`. Notification errors are logged and do not
change the backup result.

Windows native notifications are enabled with `ANAPLAN_NOTIFY_WINDOWS=true`.
Use `ANAPLAN_NOTIFICATION_POLICY=failure` to notify only when at least one model
fails. Failure messages contain the workspace and model, a shortened error, and
the result-report path. Webhook failures are retried using the configured
attempt count, delay, and timeout. Notification delivery never changes the
backup exit status.

Windows uses `ANAPLAN_PASSWORD` from the process environment or `.env`; the
macOS Keychain and macOS Notification Center options are ignored there. Native
Windows and webhook notifications are supported.

## 14. Recommended operating procedure

When adding or changing models:

1. Update `config/models.yaml`.
2. Run `./run.sh --check-config`.
3. Run `./run.sh --dry-run` and check names, IDs, enabled flags, and archive names.
4. Run `./run.sh --preflight` to verify access without creating an archive.
5. Enable only one new target and run `./run.sh --test-copy` when validating a
   new workspace or changed UI flow.
6. Restore the intended enabled targets.
7. Run `./run.sh --live`.
8. Review the exit status, summary, and newest JSON report.
9. Confirm archive retention and available workspace storage in Anaplan.
