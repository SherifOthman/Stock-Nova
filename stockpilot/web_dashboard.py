"""
StockNova AI — Modern Analytics Web Dashboard.
Runs locally on http://localhost:8585 without requiring external web frameworks.
Provides:
- Real-time Acceptance Rate Trends (Increasing / Decreasing charts)
- Multi-Tier Quotas: 1000 Pro & 200 Plus progress bars, Free 50 video credits
- Top concepts vs Blacklisted styles
- Accounts and API Keys status
- One-click Google Drive Cloud Backup & Pipeline Trigger
"""

from __future__ import annotations

import http.server
import json
import socketserver
import threading
import urllib.parse
from pathlib import Path
from typing import Any

from stockpilot.core.config import Config
from stockpilot.core.database import Database
from stockpilot.core.dynamic_controller import DynamicController
from stockpilot.core.cloud_backup import CloudBackupEngine
from stockpilot.core.logger import get_logger

logger = get_logger("web_dashboard")
PORT = 8585


def get_dashboard_data() -> dict[str, Any]:
    """Compiles all real-time stats for the UI."""
    db = Database()
    dynamic = DynamicController()
    metrics = dynamic.get_metrics()

    # Credit pools
    pools_data = []
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT pool_id, tier, total_credits, remaining_credits, used_today, target_consumption_days FROM credit_pools")
        for p in cursor.fetchall():
            burn_today = p["used_today"]
            total = p["total_credits"]
            rem = p["remaining_credits"]
            used_pct = round(((total - rem) / total) * 100, 1) if total > 0 else 0
            daily_target = dynamic.calculate_dynamic_daily_burn(p["pool_id"])
            pools_data.append({
                "pool_id": p["pool_id"],
                "tier": p["tier"].upper(),
                "total": total,
                "remaining": rem,
                "used_today": burn_today,
                "daily_target": daily_target,
                "used_percentage": used_pct
            })

        # Free accounts
        cursor.execute("SELECT profile_name, tier, daily_video_credits_limit, daily_video_credits_used, status FROM accounts WHERE tier = 'free'")
        free_accs = [dict(r) for r in cursor.fetchall()]

        # Strategy learnings
        cursor.execute("""
            SELECT pattern_or_concept, category, total_submitted, total_accepted, total_rejected, rejection_rate, action_taken
            FROM strategy_learnings
            ORDER BY total_submitted DESC
            LIMIT 10
        """)
        learnings = [dict(r) for r in cursor.fetchall()]

        # API Keys
        cursor.execute("SELECT key_alias, priority, status, requests_today FROM gemini_keys")
        api_keys = [dict(r) for r in cursor.fetchall()]

    # Blacklisted patterns from creative_strategy.json
    strat_file = Path(r"d:\Stock Automation\config\creative_strategy.json")
    blacklisted = []
    if strat_file.exists():
        try:
            with open(strat_file, "r", encoding="utf-8") as f:
                blacklisted = json.load(f).get("blacklisted_patterns", [])
        except Exception:
            pass

    # Pipeline folder counts
    ws_root = Config.get_path("paths.workspace_root", Path(r"d:\Stock Automation\workspace"))
    folder_counts = {
        "raw": len(list((ws_root / "0_Raw_Downloads").glob("*.*"))),
        "qc1_approved": len(list((ws_root / "1_QC1_Approved").glob("*.*"))),
        "qc2_approved": len(list((ws_root / "2_QC2_Approved").glob("*.*"))),
        "batched": len(list((ws_root / "3_Batched_Ready").glob("Batch_*"))),
        "awaiting_submit": len(list((ws_root / "4_Uploaded_Awaiting_Submit").glob("Batch_*"))),
    }

    return {
        "project_name": "StockNova AI",
        "metrics": metrics,
        "credit_pools": pools_data,
        "free_accounts": free_accs,
        "folder_counts": folder_counts,
        "learnings": learnings,
        "blacklisted": blacklisted,
        "api_keys": api_keys,
        "models": {
            "image": Config.get("models.image", "nano banana pro"),
            "video": Config.get("models.video", "omni flash"),
            "duration": Config.get("models.video_duration_seconds", 10),
            "upscaler": Config.get("upscayl.default_model", "high-fidelity-4x")
        }
    }


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>StockNova AI — Intelligence & Analytics Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    :root {
      --bg: #0d1117;
      --card-bg: #161b22;
      --border: #30363d;
      --text: #c9d1d9;
      --text-bright: #f0f6fc;
      --accent: #2ea043;
      --accent-blue: #58a6ff;
      --danger: #f85149;
      --warning: #d29922;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); padding: 24px; }
    .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
    .header h1 { font-size: 24px; color: var(--text-bright); display: flex; align-items: center; gap: 10px; }
    .header .actions { display: flex; gap: 10px; }
    .btn { background: #21262d; color: var(--text-bright); border: 1px solid var(--border); padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 500; transition: 0.2s; }
    .btn:hover { background: #30363d; }
    .btn-primary { background: var(--accent); border-color: var(--accent); color: #fff; }
    .btn-primary:hover { background: #2c974b; }
    
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; margin-bottom: 24px; }
    .card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 20px; }
    .card h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; color: #8b949e; margin-bottom: 8px; }
    .card .val { font-size: 28px; font-weight: 700; color: var(--text-bright); }
    .card .sub { font-size: 12px; margin-top: 6px; color: #8b949e; }
    
    .progress-bar-bg { width: 100%; height: 8px; background: #21262d; border-radius: 4px; overflow: hidden; margin-top: 10px; }
    .progress-bar-fill { height: 100%; background: var(--accent-blue); border-radius: 4px; transition: width 0.4s; }

    .two-col { display: grid; grid-template-columns: 2fr 1fr; gap: 16px; margin-bottom: 24px; }
    @media (max-width: 900px) { .two-col { grid-template-columns: 1fr; } }

    table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }
    th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); }
    th { color: #8b949e; font-weight: 600; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }
    .badge-success { background: rgba(46, 160, 67, 0.15); color: #3fb950; }
    .badge-danger { background: rgba(248, 81, 73, 0.15); color: #f85149; }
    .badge-warning { background: rgba(210, 153, 34, 0.15); color: #d29922; }

    .tag { display: inline-block; background: #21262d; border: 1px solid var(--border); border-radius: 4px; padding: 3px 8px; font-size: 11px; margin: 2px; }
    .chart-container { position: relative; height: 260px; width: 100%; margin-top: 12px; }
  </style>
</head>
<body>

  <div class="header">
    <h1>🚀 StockNova AI <span style="font-size: 14px; font-weight: 400; color: #8b949e;">Autonomous Stock Strategy Engine</span></h1>
    <div class="actions">
      <button class="btn" onclick="triggerBackup()">☁️ Google Drive Backup</button>
      <button class="btn btn-primary" onclick="runPipeline()">▶ Run Pipeline Step</button>
    </div>
  </div>

  <!-- KPI Cards -->
  <div class="grid">
    <div class="card">
      <h3>Adobe Acceptance Rate</h3>
      <div class="val" id="acc-rate">--%</div>
      <div class="sub" id="acc-sub">Accepted: 0 | Rejected: 0</div>
    </div>
    <div class="card">
      <h3>Pro Pool (1000 Credits)</h3>
      <div class="val" id="pro-rem">---</div>
      <div class="progress-bar-bg"><div class="progress-bar-fill" id="pro-prog"></div></div>
      <div class="sub" id="pro-sub">Burned today: 0 | Target: 0/day</div>
    </div>
    <div class="card">
      <h3>Plus Pool (200 Credits)</h3>
      <div class="val" id="plus-rem">---</div>
      <div class="progress-bar-bg"><div class="progress-bar-fill" id="plus-prog" style="background: var(--warning);"></div></div>
      <div class="sub" id="plus-sub">Burned today: 0 | Target: 0/day</div>
    </div>
    <div class="card">
      <h3>Pipeline Ready (Weekly Batch)</h3>
      <div class="val" id="batches-ready">-</div>
      <div class="sub" id="folders-sub">Raw: 0 | QC1: 0 | QC2: 0</div>
    </div>
  </div>

  <div class="two-col">
    <!-- Chart -->
    <div class="card">
      <h3>Review Outcomes Performance</h3>
      <div class="chart-container">
        <canvas id="reviewChart"></canvas>
      </div>
    </div>

    <!-- Free Accounts Video Credits -->
    <div class="card">
      <h3>Free Accounts (50 Daily Videos)</h3>
      <table id="free-accounts-table">
        <thead><tr><th>Profile</th><th>Daily Used</th><th>Status</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>

  <!-- Strategy & Auto-Pivot Table -->
  <div class="card" style="margin-bottom: 24px;">
    <h3>🧠 Self-Evolving Concept Intelligence (Winning vs Blacklisted)</h3>
    <table>
      <thead>
        <tr>
          <th>Concept / Pattern</th>
          <th>Category</th>
          <th>Submissions</th>
          <th>Accepted</th>
          <th>Rejected</th>
          <th>Acceptance Rate</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody id="learnings-tbody"></tbody>
    </table>
    
    <div style="margin-top: 16px;">
      <h4 style="font-size: 12px; color: #8b949e; margin-bottom: 8px;">🚫 ACTIVE BLACKLISTED CONCEPTS (Auto-Pivoted to prevent credit waste):</h4>
      <div id="blacklisted-tags"></div>
    </div>
  </div>

  <script>
    let reviewChartInstance = null;

    async function loadData() {
      try {
        const res = await fetch('/api/data');
        const d = await res.json();

        // 1. Acceptance Rate
        const rate = (d.metrics.acceptance_rate * 100).toFixed(1);
        document.getElementById('acc-rate').textContent = rate + '%';
        document.getElementById('acc-sub').textContent = 
          `Accepted: ${d.metrics.accepted_count} | Rejected: ${d.metrics.rejected_count} | Pending: ${d.metrics.pending_review}`;

        // 2. Pools
        d.credit_pools.forEach(p => {
          if (p.tier === 'PRO') {
            document.getElementById('pro-rem').textContent = `${p.remaining} / ${p.total}`;
            document.getElementById('pro-prog').style.width = p.used_percentage + '%';
            document.getElementById('pro-sub').textContent = `Burned today: ${p.used_today} | Target: ${p.daily_target}/day`;
          } else if (p.tier === 'PLUS') {
            document.getElementById('plus-rem').textContent = `${p.remaining} / ${p.total}`;
            document.getElementById('plus-prog').style.width = p.used_percentage + '%';
            document.getElementById('plus-sub').textContent = `Burned today: ${p.used_today} | Target: ${p.daily_target}/day`;
          }
        });

        // 3. Batches
        document.getElementById('batches-ready').textContent = `${d.folder_counts.batched} Batches`;
        document.getElementById('folders-sub').textContent = 
          `Raw: ${d.folder_counts.raw} | QC1: ${d.folder_counts.qc1_approved} | QC2: ${d.folder_counts.qc2_approved} | Uploaded: ${d.folder_counts.awaiting_submit}`;

        // 4. Free accounts table
        const fBody = document.querySelector('#free-accounts-table tbody');
        fBody.innerHTML = '';
        d.free_accounts.forEach(a => {
          const tr = document.createElement('tr');
          tr.innerHTML = `
            <td><strong>${a.profile_name}</strong></td>
            <td>${a.daily_video_credits_used} / ${a.daily_video_credits_limit}</td>
            <td><span class="badge ${a.daily_video_credits_used >= a.daily_video_credits_limit ? 'badge-danger' : 'badge-success'}">${a.status}</span></td>
          `;
          fBody.appendChild(tr);
        });

        // 5. Learnings Table
        const lBody = document.getElementById('learnings-tbody');
        lBody.innerHTML = '';
        if (d.learnings.length === 0) {
          lBody.innerHTML = '<tr><td colspan="7" style="color: #8b949e; text-align: center;">No review outcomes recorded yet. The system is generating and preparing initial batches.</td></tr>';
        } else {
          d.learnings.forEach(l => {
            const tr = document.createElement('tr');
            const accRate = ((1 - l.rejection_rate) * 100).toFixed(0);
            const isBlack = l.action_taken === 'blacklisted';
            tr.innerHTML = `
              <td><strong>${l.pattern_or_concept}</strong></td>
              <td>${l.category}</td>
              <td>${l.total_submitted}</td>
              <td style="color: #3fb950;">${l.total_accepted}</td>
              <td style="color: #f85149;">${l.total_rejected}</td>
              <td><strong>${accRate}%</strong></td>
              <td><span class="badge ${isBlack ? 'badge-danger' : 'badge-success'}">${l.action_taken}</span></td>
            `;
            lBody.appendChild(tr);
          });
        }

        // 6. Blacklisted tags
        const bDiv = document.getElementById('blacklisted-tags');
        bDiv.innerHTML = '';
        if (d.blacklisted.length === 0) {
          bDiv.innerHTML = '<span style="color: #8b949e; font-size: 12px;">No concepts blacklisted yet.</span>';
        } else {
          d.blacklisted.forEach(b => {
            const span = document.createElement('span');
            span.className = 'tag';
            span.style.borderColor = 'rgba(248, 81, 73, 0.4)';
            span.textContent = b;
            bDiv.appendChild(span);
          });
        }

        // 7. Update Chart
        renderChart(d.metrics.accepted_count, d.metrics.rejected_count, d.metrics.pending_review);

      } catch (err) {
        console.error('Error fetching dashboard data:', err);
      }
    }

    function renderChart(accepted, rejected, pending) {
      const ctx = document.getElementById('reviewChart').getContext('2d');
      if (reviewChartInstance) reviewChartInstance.destroy();
      reviewChartInstance = new Chart(ctx, {
        type: 'doughnut',
        data: {
          labels: ['Accepted', 'Rejected', 'Awaiting Submit'],
          datasets: [{
            data: [accepted || 1, rejected || 0, pending || 1],
            backgroundColor: ['#2ea043', '#f85149', '#58a6ff'],
            borderWidth: 0
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: 'right', labels: { color: '#c9d1d9', font: { family: 'Inter' } } }
          }
        }
      });
    }

    async function triggerBackup() {
      const btn = event.target;
      btn.textContent = '⏳ Backing up...';
      try {
        const res = await fetch('/api/backup', { method: 'POST' });
        const d = await res.json();
        alert('✅ Snapshot backed up to Google Drive successfully!\\nPath: ' + d.path);
      } catch (e) {
        alert('Backup error: ' + e);
      } finally {
        btn.textContent = '☁️ Google Drive Backup';
      }
    }

    async function runPipeline() {
      const btn = event.target;
      btn.textContent = '⏳ Running...';
      try {
        await fetch('/api/run_step', { method: 'POST' });
        alert('✅ Pipeline Step completed! Folders updated.');
        loadData();
      } catch (e) {
        alert('Pipeline error: ' + e);
      } finally {
        btn.textContent = '▶ Run Pipeline Step';
      }
    }

    // Auto-refresh every 10 seconds
    loadData();
    setInterval(loadData, 10000);
  </script>
</body>
</html>
"""


class DashboardRequestHandler(http.server.BaseHTTPRequestHandler):
    """Custom HTTP handler serving dashboard and REST API."""

    def do_GET(self) -> None:
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode("utf-8"))
        elif self.path == "/api/data":
            data = get_dashboard_data()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        if self.path == "/api/backup":
            backup = CloudBackupEngine()
            snap = backup.create_snapshot()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "success", "path": str(snap)}).encode("utf-8"))
        elif self.path == "/api/run_step":
            from stockpilot.app import run_pipeline_step
            run_pipeline_step()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "completed"}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy standard HTTP access logs
        pass


def start_server(port: int = PORT) -> None:
    """Launches the local dashboard server."""
    with socketserver.TCPServer(("", port), DashboardRequestHandler) as httpd:
        print(f"[*] StockNova Web Dashboard running at http://localhost:{port}")
        httpd.serve_forever()


if __name__ == "__main__":
    start_server()
