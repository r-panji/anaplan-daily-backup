from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"
OUTPUT = ROOT / "output" / "dashboard" / "index.html"


def load_reports() -> list[dict]:
    reports = []
    for path in sorted(LOGS.glob("backup_results_*.json")):
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(rows, list):
            continue
        stamp = path.stem.removeprefix("backup_results_")
        try:
            run_at = datetime.strptime(stamp, "%Y%m%d_%H%M%S_%f")
        except ValueError:
            continue
        reports.append(
            {
                "timestamp": run_at.isoformat(),
                "displayTime": run_at.strftime("%d %b %Y, %H:%M"),
                "filename": path.name,
                "results": rows,
            }
        )
    return reports


def build() -> None:
    reports = load_reports()
    payload = json.dumps(reports, ensure_ascii=True).replace("</", "<\\/")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        TEMPLATE.replace("__REPORT_DATA__", payload), encoding="utf-8"
    )
    print(OUTPUT)


TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Anaplan Backup Operations</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #17202a;
      --muted: #65717e;
      --line: #d8dee5;
      --paper: #ffffff;
      --canvas: #eef1f4;
      --navy: #163a5f;
      --navy-soft: #e8f0f7;
      --green: #157347;
      --green-soft: #e5f4ec;
      --red: #b42318;
      --red-soft: #fce9e7;
      --amber: #8a5700;
      --amber-soft: #fff2d8;
      --focus: #0067b8;
      --radius: 10px;
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--canvas); color: var(--ink); font: 15px/1.45 Arial, Helvetica, sans-serif; }
    button, select, input { font: inherit; }
    button, select { min-height: 44px; }
    button:focus-visible, select:focus-visible, input:focus-visible, a:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
    .shell { min-height: 100vh; }
    header { background: var(--navy); color: white; }
    .header-inner { max-width: 1240px; margin: auto; padding: 28px 24px 25px; display: flex; justify-content: space-between; gap: 24px; align-items: flex-end; }
    .eyebrow { margin: 0 0 5px; color: #c9d9e8; font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
    h1 { margin: 0; font-size: clamp(27px, 4vw, 40px); line-height: 1.08; letter-spacing: -.02em; }
    .subtitle { margin: 8px 0 0; color: #dce7f1; }
    .header-meta { text-align: right; color: #dce7f1; font-size: 13px; }
    main { max-width: 1240px; margin: auto; padding: 28px 24px 48px; }
    .notice { margin-bottom: 18px; padding: 11px 14px; background: var(--amber-soft); border-left: 4px solid #b87800; color: #593900; }
    .summary { display: grid; grid-template-columns: 1.5fr repeat(3, 1fr); gap: 14px; margin-bottom: 22px; }
    .metric { background: var(--paper); border: 1px solid var(--line); border-radius: var(--radius); padding: 18px; min-width: 0; }
    .metric.primary { border-top: 4px solid var(--navy); padding-top: 15px; }
    .metric-label { color: var(--muted); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; }
    .metric-value { display: block; margin-top: 8px; font-size: 29px; line-height: 1; font-weight: 700; font-variant-numeric: tabular-nums; }
    .metric-detail { display: block; margin-top: 8px; color: var(--muted); font-size: 13px; }
    .panel { background: var(--paper); border: 1px solid var(--line); border-radius: var(--radius); margin-top: 18px; }
    .panel-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 20px; border-bottom: 1px solid var(--line); }
    h2 { margin: 0; font-size: 19px; }
    .filters { display: flex; flex-wrap: wrap; gap: 8px; }
    .filter { border: 1px solid #aeb8c2; border-radius: 6px; background: white; color: var(--ink); padding: 8px 13px; cursor: pointer; }
    .filter[aria-pressed="true"] { background: var(--navy); color: white; border-color: var(--navy); }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; min-width: 770px; }
    th, td { padding: 14px 16px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: middle; }
    th { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; background: #f7f8fa; }
    tbody tr:last-child td { border-bottom: 0; }
    tbody tr:hover { background: #f8fafc; }
    .model { font-weight: 700; }
    .workspace { color: var(--muted); font-size: 13px; margin-top: 2px; }
    .status { display: inline-flex; align-items: center; gap: 7px; font-weight: 700; }
    .status::before { content: ""; width: 9px; height: 9px; border-radius: 50%; background: currentColor; }
    .status.success { color: var(--green); }
    .status.failed { color: var(--red); }
    .status.other { color: var(--amber); }
    .archive { max-width: 340px; overflow-wrap: anywhere; font-family: "Courier New", monospace; font-size: 12px; }
    .details { border: 1px solid #9da9b5; background: white; border-radius: 6px; padding: 8px 12px; cursor: pointer; }
    .lower { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(280px, .75fr); gap: 18px; }
    .trend { padding: 20px; }
    .bars { display: grid; gap: 12px; margin-top: 20px; }
    .bar-row { display: grid; grid-template-columns: 120px 1fr 48px; gap: 12px; align-items: center; }
    .track { height: 12px; border-radius: 3px; background: #e6eaee; overflow: hidden; }
    .fill { height: 100%; background: var(--green); }
    .rate { text-align: right; font-variant-numeric: tabular-nums; }
    .runs { list-style: none; margin: 0; padding: 4px 20px 12px; }
    .runs li { padding: 13px 0; border-bottom: 1px solid var(--line); }
    .runs li:last-child { border-bottom: 0; }
    .run-top { display: flex; justify-content: space-between; gap: 12px; }
    .run-date { font-weight: 700; }
    .run-count { color: var(--muted); }
    .report-link { display: inline-block; margin-top: 6px; color: var(--navy); font-weight: 700; }
    .state { padding: 34px 20px; text-align: center; color: var(--muted); }
    dialog { width: min(680px, calc(100% - 32px)); border: 0; border-radius: 10px; padding: 0; box-shadow: 0 20px 60px rgba(14, 31, 48, .28); }
    dialog::backdrop { background: rgba(13, 25, 38, .58); }
    .dialog-head { background: var(--navy); color: white; padding: 18px 20px; display: flex; align-items: center; justify-content: space-between; gap: 16px; }
    .dialog-head h2 { font-size: 18px; }
    .close { min-width: 44px; border: 1px solid #b8cada; border-radius: 6px; background: transparent; color: white; cursor: pointer; font-size: 22px; }
    .dialog-body { padding: 20px; }
    .detail-grid { display: grid; grid-template-columns: 130px 1fr; gap: 10px 14px; }
    .detail-grid dt { color: var(--muted); }
    .detail-grid dd { margin: 0; overflow-wrap: anywhere; }
    .error-box { margin-top: 18px; padding: 14px; background: var(--red-soft); color: #6f1812; white-space: pre-wrap; max-height: 210px; overflow: auto; font: 12px/1.45 "Courier New", monospace; }
    footer { max-width: 1240px; margin: auto; padding: 0 24px 30px; color: var(--muted); font-size: 13px; }
    @media (max-width: 850px) {
      .header-inner { align-items: flex-start; flex-direction: column; }
      .header-meta { text-align: left; }
      .summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .lower { grid-template-columns: 1fr; }
    }
    @media (max-width: 560px) {
      main { padding: 20px 14px 36px; }
      .header-inner { padding: 23px 16px; }
      .summary { grid-template-columns: 1fr; }
      .panel-head { align-items: flex-start; flex-direction: column; }
      .filters { width: 100%; }
      .filter { flex: 1; }
      .bar-row { grid-template-columns: 92px 1fr 42px; gap: 8px; }
      .detail-grid { grid-template-columns: 1fr; gap: 3px; }
      .detail-grid dd { margin-bottom: 10px; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div class="header-inner">
        <div>
          <p class="eyebrow">Backup operations</p>
          <h1>Anaplan archive status</h1>
          <p class="subtitle">One view of model health, recent runs, and failures.</p>
        </div>
        <div class="header-meta"><strong id="latest-time">Loading reports</strong><br>Asia/Jakarta</div>
      </div>
    </header>
    <main>
      <div class="notice"><strong>Preview:</strong> this page reads a snapshot of local JSON reports generated when the preview was built.</div>
      <section class="summary" aria-label="Latest run summary">
        <article class="metric primary"><span class="metric-label">Latest run</span><strong class="metric-value" id="run-status">Loading</strong><span class="metric-detail" id="run-detail">Reading report data</span></article>
        <article class="metric"><span class="metric-label">Successful</span><strong class="metric-value" id="success-count">0</strong><span class="metric-detail">Verified archives</span></article>
        <article class="metric"><span class="metric-label">Failed</span><strong class="metric-value" id="failed-count">0</strong><span class="metric-detail">Models needing attention</span></article>
        <article class="metric"><span class="metric-label">Workspaces</span><strong class="metric-value" id="workspace-count">0</strong><span class="metric-detail">In the latest run</span></article>
      </section>

      <section class="panel" aria-labelledby="models-heading">
        <div class="panel-head">
          <h2 id="models-heading">Latest model results</h2>
          <div class="filters" role="group" aria-label="Filter model status">
            <button class="filter" type="button" data-filter="all" aria-pressed="true">All</button>
            <button class="filter" type="button" data-filter="success" aria-pressed="false">Successful</button>
            <button class="filter" type="button" data-filter="failed" aria-pressed="false">Failed</button>
          </div>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Model</th><th>Status</th><th>Archive</th><th>Verified</th><th>Details</th></tr></thead>
            <tbody id="model-rows"><tr><td class="state" colspan="5">Loading model results</td></tr></tbody>
          </table>
        </div>
      </section>

      <div class="lower">
        <section class="panel trend" aria-labelledby="trend-heading">
          <h2 id="trend-heading">Recent success rate</h2>
          <div class="bars" id="trend-bars"><div class="state">Loading history</div></div>
        </section>
        <section class="panel" aria-labelledby="runs-heading">
          <div class="panel-head"><h2 id="runs-heading">Recent reports</h2></div>
          <ul class="runs" id="recent-runs"><li class="state">Loading reports</li></ul>
        </section>
      </div>
    </main>
    <footer>Generated from local backup result files. No workspace or model IDs are displayed.</footer>
  </div>

  <dialog id="detail-dialog" aria-labelledby="dialog-title">
    <div class="dialog-head"><h2 id="dialog-title">Model result</h2><button class="close" type="button" aria-label="Close details">&times;</button></div>
    <div class="dialog-body" id="dialog-content"></div>
  </dialog>

  <script id="report-data" type="application/json">__REPORT_DATA__</script>
  <script>
    (() => {
      const reports = JSON.parse(document.getElementById('report-data').textContent);
      const latest = reports.at(-1);
      const rows = document.getElementById('model-rows');
      const dialog = document.getElementById('detail-dialog');
      const content = document.getElementById('dialog-content');
      let filter = 'all';

      const esc = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
      const normalized = value => String(value || 'OTHER').toLowerCase();
      const statusLabel = value => value === 'SUCCESS' ? 'Successful' : value === 'FAILED' ? 'Failed' : String(value || 'Unknown');

      function showDetails(index) {
        const item = latest.results[index];
        content.innerHTML = `<dl class="detail-grid">
          <dt>Workspace</dt><dd>${esc(item.workspace)}</dd>
          <dt>Model</dt><dd>${esc(item.model)}</dd>
          <dt>Status</dt><dd>${esc(statusLabel(item.status))}</dd>
          <dt>Archive</dt><dd>${esc(item.archive || 'Not created')}</dd>
          <dt>Verified</dt><dd>${item.verified ? 'Yes' : 'No'}</dd>
        </dl>${item.error ? `<div class="error-box" aria-label="Failure detail">${esc(item.error)}</div>` : ''}`;
        document.getElementById('dialog-title').textContent = item.model || 'Model result';
        dialog.showModal();
      }

      function renderRows() {
        const visible = latest.results.map((item, index) => ({item, index})).filter(({item}) => filter === 'all' || normalized(item.status) === filter);
        if (!visible.length) {
          rows.innerHTML = '<tr><td class="state" colspan="5">No models match this filter.</td></tr>';
          return;
        }
        rows.innerHTML = visible.map(({item, index}) => `<tr>
          <td><div class="model">${esc(item.model)}</div><div class="workspace">${esc(item.workspace)}</div></td>
          <td><span class="status ${esc(normalized(item.status))}">${esc(statusLabel(item.status))}</span></td>
          <td class="archive">${esc(item.archive || 'Not created')}</td>
          <td>${item.verified ? 'Yes' : 'No'}</td>
          <td><button class="details" type="button" data-index="${index}">View</button></td>
        </tr>`).join('');
        rows.querySelectorAll('.details').forEach(button => button.addEventListener('click', () => showDetails(Number(button.dataset.index))));
      }

      if (!latest || !Array.isArray(latest.results)) {
        document.getElementById('run-status').textContent = 'No reports';
        document.getElementById('run-detail').textContent = 'Run a backup to create dashboard data.';
        rows.innerHTML = '<tr><td class="state" colspan="5">No backup result reports were found.</td></tr>';
        document.getElementById('trend-bars').innerHTML = '<div class="state">No run history is available.</div>';
        document.getElementById('recent-runs').innerHTML = '<li class="state">No reports are available.</li>';
        return;
      }

      const successful = latest.results.filter(item => item.status === 'SUCCESS').length;
      const failed = latest.results.filter(item => item.status === 'FAILED').length;
      const workspaces = new Set(latest.results.map(item => item.workspace)).size;
      document.getElementById('latest-time').textContent = `Latest report: ${latest.displayTime}`;
      document.getElementById('run-status').textContent = failed ? 'Needs attention' : 'Healthy';
      document.getElementById('run-detail').textContent = `${latest.results.length} models processed`;
      document.getElementById('success-count').textContent = successful;
      document.getElementById('failed-count').textContent = failed;
      document.getElementById('workspace-count').textContent = workspaces;
      renderRows();

      document.querySelectorAll('.filter').forEach(button => button.addEventListener('click', () => {
        filter = button.dataset.filter;
        document.querySelectorAll('.filter').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
        renderRows();
      }));

      const recent = reports.slice(-7).reverse();
      document.getElementById('trend-bars').innerHTML = recent.map(report => {
        const total = report.results.length;
        const ok = report.results.filter(item => item.status === 'SUCCESS').length;
        const rate = total ? Math.round(ok / total * 100) : 0;
        return `<div class="bar-row"><span>${esc(report.displayTime.split(',')[0])}</span><div class="track" aria-label="${rate} percent successful"><div class="fill" style="width:${rate}%"></div></div><span class="rate">${rate}%</span></div>`;
      }).join('');
      document.getElementById('recent-runs').innerHTML = recent.slice(0, 5).map(report => {
        const failedCount = report.results.filter(item => item.status === 'FAILED').length;
        return `<li><div class="run-top"><span class="run-date">${esc(report.displayTime)}</span><span class="run-count">${failedCount ? `${failedCount} failed` : 'All passed'}</span></div><a class="report-link" href="../../logs/${encodeURIComponent(report.filename)}">Open JSON report</a></li>`;
      }).join('');

      dialog.querySelector('.close').addEventListener('click', () => dialog.close());
      dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
    })();
  </script>
</body>
</html>
'''


if __name__ == "__main__":
    build()
