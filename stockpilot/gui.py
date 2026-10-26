"""
StockNova AI — Autonomous Desktop Agent Cockpit.
Key Capabilities:
1. Single Unified Vault for all assets (Nano Banana Pro + 10-20 pt Video Models).
2. Dual-Platform Life-Cycle Tracking (Adobe active now, Freepik auto-indexed).
3. Incremental Freepik 150-200 Golden Curator:
   - Evaluates technical specs (>= 4MP, min 2000px, 100% crop texture).
   - Locks picked assets (is_freepik_150_golden = 1) so they are NEVER re-scanned.
   - Ignores failed assets so they are NEVER re-tested.
   - Disabled while background pipeline is active to prevent incomplete file curation.
4. Commercial Model Safety Validator:
   - Locks 'high-fidelity-4x' (BSD/Permissive Commercial).
   - Hard-blocks non-commercial community models (UltraSharp, Remacri).
5. 1-Click Google Drive Cloud Sync & Portable Distribution Exporter.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

from stockpilot.core.config import Config
from stockpilot.core.database import Database
from stockpilot.core.dynamic_controller import DynamicController
from stockpilot.core.cloud_backup import CloudBackupEngine
from stockpilot.core.unified_vault import UnifiedVaultManager
from stockpilot.platforms.freepik_curator import FreepikOnboardingCurator
from stockpilot.quality.model_license_validator import validate_upscale_model
from stockpilot.app import GoogleDotsPipeline


class StockNovaAgentCockpit:
    """The master single-window autonomous desktop agent for StockNova."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("StockNova AI — Autonomous Stock Photography & Video Studio")
        self.root.geometry("1000x720")
        self.root.minsize(940, 640)

        self.db = Database()
        self.pipeline = GoogleDotsPipeline()
        self.dynamic = DynamicController()
        self.vault = UnifiedVaultManager()
        self.curator = FreepikOnboardingCurator()
        self.cloud = CloudBackupEngine()
        self.is_running = False

        self._build_ui()
        self._refresh_metrics()

    def _build_ui(self) -> None:
        # Header / Status Bar
        header = ttk.Frame(self.root, padding=14)
        header.pack(fill=tk.X)

        title_box = ttk.Frame(header)
        title_box.pack(side=tk.LEFT)
        ttk.Label(title_box, text="⚡ StockNova AI Studio", font=("Segoe UI", 18, "bold")).pack(anchor=tk.W)
        ttk.Label(
            title_box,
            text="Autonomous Stock Engine • Adobe Stock Active • Freepik 150-200 Incremental Gate",
            font=("Segoe UI", 9),
            foreground="#555"
        ).pack(anchor=tk.W)

        self.status_badge = ttk.Label(header, text="● IDLE", foreground="gray", font=("Segoe UI", 12, "bold"))
        self.status_badge.pack(side=tk.RIGHT)

        # Action Toolbar
        f_controls = ttk.LabelFrame(self.root, text="Master Agent Actions", padding=12)
        f_controls.pack(fill=tk.X, padx=14, pady=6)

        self.btn_run_cycle = ttk.Button(f_controls, text="▶ Run Autonomous Pipeline Cycle", command=self._run_cycle_async)
        self.btn_run_cycle.pack(side=tk.LEFT, padx=5)

        self.btn_curate_fp = ttk.Button(
            f_controls,
            text="💎 Curate Freepik 150-200 Golden Batch",
            command=self._curate_freepik_batch_async
        )
        self.btn_curate_fp.pack(side=tk.LEFT, padx=5)

        ttk.Button(f_controls, text="🌐 Open Web Analytics", command=self._open_web_dashboard).pack(side=tk.LEFT, padx=5)
        ttk.Button(f_controls, text="📦 Export Portable Zip", command=self._export_portable_pkg).pack(side=tk.RIGHT, padx=5)
        ttk.Button(f_controls, text="☁️ Google Drive Backup", command=self._trigger_cloud_backup).pack(side=tk.RIGHT, padx=5)

        # Center Notebook
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=14, pady=6)

        self.tab_vault = ttk.Frame(notebook, padding=12)
        self.tab_freepik = ttk.Frame(notebook, padding=12)
        self.tab_accounts = ttk.Frame(notebook, padding=12)
        self.tab_models = ttk.Frame(notebook, padding=12)

        notebook.add(self.tab_vault, text="📂 Central Asset Vault & Adobe")
        notebook.add(self.tab_freepik, text="🎯 Freepik 150-200 Golden Gate")
        notebook.add(self.tab_accounts, text="💳 Accounts & Points (50 Pts / Pro / Plus)")
        notebook.add(self.tab_models, text="🔬 Video Models A/B & Licenses")

        # --- TAB 1: Central Vault ---
        self.txt_vault = tk.Text(self.tab_vault, font=("Consolas", 10), state=tk.DISABLED, bg="#fafafa")
        self.txt_vault.pack(fill=tk.BOTH, expand=True)

        # --- TAB 2: Freepik 150-200 Gate ---
        f_fp_top = ttk.Frame(self.tab_freepik)
        f_fp_top.pack(fill=tk.X, pady=6)
        self.lbl_fp_gate = ttk.Label(f_fp_top, text="Freepik Onboarding Progress: 0 / 150-200 Golden Assets", font=("Segoe UI", 11, "bold"))
        self.lbl_fp_gate.pack(anchor=tk.W)

        self.fp_prog = ttk.Progressbar(f_fp_top, maximum=150, value=0)
        self.fp_prog.pack(fill=tk.X, pady=6)

        self.txt_freepik = tk.Text(self.tab_freepik, font=("Consolas", 10), state=tk.DISABLED, bg="#fafafa")
        self.txt_freepik.pack(fill=tk.BOTH, expand=True, pady=6)

        # --- TAB 3: Accounts ---
        self.txt_accounts = tk.Text(self.tab_accounts, font=("Consolas", 10), state=tk.DISABLED, bg="#fafafa")
        self.txt_accounts.pack(fill=tk.BOTH, expand=True)

        # --- TAB 4: Models & Licenses ---
        self.txt_models = tk.Text(self.tab_models, font=("Consolas", 10), state=tk.DISABLED, bg="#1e1e1e", fg="#dcdcdc")
        self.txt_models.pack(fill=tk.BOTH, expand=True)

    def _refresh_metrics(self) -> None:
        ws = self.pipeline
        raw_c = len(list(ws.raw_dir.glob("*.jpg")) + list(ws.raw_dir.glob("*.png")))
        qc1_c = len(list(ws.qc1_pass_dir.glob("*.jpg")) + list(ws.qc1_pass_dir.glob("*.png")))
        approved_c = len(list(ws.qc2_pass_dir.glob("*.jpg")) + list(ws.qc2_pass_dir.glob("*.png")))
        batched_c = len(list(ws.batched_dir.glob("Batch_*")))
        uploaded_c = len(list(ws.uploaded_dir.glob("Batch_*")))

        metrics = self.dynamic.get_metrics()
        pro_burn = self.dynamic.calculate_dynamic_daily_burn("pro_pool")
        plus_burn = self.dynamic.calculate_dynamic_daily_burn("plus_pool")

        fp_status = self.curator.get_status()
        self.lbl_fp_gate.config(
            text=f"Freepik Onboarding Pool: {fp_status.curated_count} / {fp_status.total_target} Golden Assets "
                 f"({'READY FOR SUBMIT!' if fp_status.is_ready_for_submission else f'Needs {fp_status.needed_count} more'})"
        )
        self.fp_prog["value"] = fp_status.curated_count

        # Tab 1: Vault Text
        vault_text = (
            "=================== CENTRAL ASSET VAULT (ONE ENGINE) ===================\n\n"
            f"📥 0_Raw_Downloads:            {raw_c} assets (auto-sanitized, no timestamps/2k)\n"
            f"✅ 1_QC1_Approved:             {qc1_c} assets (passed concept/anatomy filter)\n"
            f"🎯 2_QC2_Approved:             {approved_c} assets (passed 100% crop & IPTC/CSV generated)\n"
            f"📦 3_Batched_Ready:            {batched_c} diverse anti-similarity batches\n"
            f"🚀 4_Uploaded_Awaiting_Submit: {uploaded_c} batches on Adobe Stock (Mode A 0% Risk)\n"
            "------------------------------------------------------------------------\n"
            f"📈 Live Adobe Acceptance Rate: {metrics['acceptance_rate']*100:.1f}%\n"
            f"🎨 Images Engine:              {Config.get('models.image', 'nano banana pro')} (100% Realism or Vector)\n"
            f"🎬 Video Engine:               10-20 Points Budget (Omni Flash / Veo Fast - No Audio)\n"
            f"🛠 Production Upscaler Model:  {validate_upscale_model(Config.get('upscayl.default_model', 'high-fidelity-4x'))} [Commercial BSD/Permissive]\n"
            "========================================================================\n"
        )
        self.txt_vault.config(state=tk.NORMAL)
        self.txt_vault.delete("1.0", tk.END)
        self.txt_vault.insert(tk.END, vault_text)
        self.txt_vault.config(state=tk.DISABLED)

        # Tab 2: Freepik Gate Text
        fp_text = (
            "=================== FREEPIK 150-200 GOLDEN ONBOARDING GATE ===================\n\n"
            f"Curated In Golden Pool: {fp_status.curated_count} / {fp_status.total_target} Minimum\n"
            f"• Isolated White-BG Mockups: {fp_status.isolated_mockup_count}\n"
            f"• Full-Bleed Backgrounds:   {fp_status.full_bleed_bg_count}\n"
            f"• Still Needed:              {fp_status.needed_count} assets\n\n"
            "STRICT TECHNICAL AUDIT RULES (AUTOMATICALLY ENFORCED):\n"
            "1. Resolution: Strictly >= 4.0 Megapixels (>= 2000px on shortest side).\n"
            "2. Texture Sharpness: Laplacian variance >= 115.0 (Passed 100% zoom reviewer test).\n"
            "3. Anti-Similarity: 100% distinct across all 150-200 images using pHash distance.\n"
            "4. Incremental Locking: Already picked or rejected assets are permanently locked in SQLite.\n"
            f"\nGolden Pool Folder: {self.curator.golden_folder}\n"
        )
        if fp_status.is_ready_for_submission:
            fp_text += "\n🎉🎉 MILESTONE REACHED! 150 Golden Assets ready for Freepik Initial Submission! 🎉🎉\n"
        self.txt_freepik.config(state=tk.NORMAL)
        self.txt_freepik.delete("1.0", tk.END)
        self.txt_freepik.insert(tk.END, fp_text)
        self.txt_freepik.config(state=tk.DISABLED)

        # Tab 3: Accounts Text
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT profile_name, tier, daily_video_credits_used, pool_id, status FROM accounts")
            accs = cursor.fetchall()
            cursor.execute("SELECT pool_id, tier, total_credits, remaining_credits, used_today FROM credit_pools")
            pools = cursor.fetchall()

        acc_text = "======================== ACCOUNTS & DAILY POINTS ========================\n\n"
        acc_text += "• FREE ACCOUNTS (50 Daily Points -> 2 to 3 Videos Max Daily):\n"
        for a in accs:
            if a["tier"] == "free":
                acc_text += f"   - {a['profile_name']}: Points Used Today: {a['daily_video_credits_used']}/50 | Status: {a['status']}\n"

        acc_text += "\n• SHARED POOLS (FLEXIBLE 10-15 DAYS PACING):\n"
        for p in pools:
            acc_text += f"   - {p['pool_id'].upper()}: Remaining: {p['remaining_credits']}/{p['total_credits']} | Burned Today: {p['used_today']}\n"

        acc_text += f"\n• DYNAMIC BURN RECOMMENDATION: Pro={pro_burn} credits/day | Plus={plus_burn} credits/day\n"
        self.txt_accounts.config(state=tk.NORMAL)
        self.txt_accounts.delete("1.0", tk.END)
        self.txt_accounts.insert(tk.END, acc_text)
        self.txt_accounts.config(state=tk.DISABLED)

        # Tab 4: Models & Licenses
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT model_name, asset_type, total_generated, qc_passed, qc_failed, status FROM model_performance")
            models = cursor.fetchall()

        mod_text = "=== AI MODELS EVALUATION & COMMERCIAL LICENSE POLICIES ===\n\n"
        mod_text += "1. UPSCALING COMMERCIAL COMPLIANCE:\n"
        mod_text += "   [VERIFIED COMMERCIAL] high-fidelity-4x (4xHFA2k - Real-ESRGAN Compact): ACTIVE PRODUCTION\n"
        mod_text += "   [VERIFIED COMMERCIAL] upscayl-standard-4x (BSD 3-Clause): BACKUP\n"
        mod_text += "   [LEGAL BLOCK - BANNED] ultrasharp-4x (CC-BY-NC Non-Commercial by Kim2091)\n"
        mod_text += "   [LEGAL BLOCK - BANNED] remacri-4x (Restricted Non-Commercial by Foolhardy)\n\n"
        mod_text += "2. VIDEO MODELS (10-20 POINTS) A/B TESTING STATS:\n"
        if models:
            for m in models:
                status_icon = "❌ [BLACKLISTED]" if m["status"] == "blacklisted" else "✅ [ACTIVE]"
                pass_rate = (m["qc_passed"] / m["total_generated"] * 100) if m["total_generated"] > 0 else 100
                mod_text += f"   • {m['model_name']:<16}: Pass Rate={pass_rate:.0f}% (Passed: {m['qc_passed']}, Failed: {m['qc_failed']}) {status_icon}\n"
        else:
            mod_text += "   Testing candidates: Omni Flash (15 pts), Veo Fast (10 pts), Viewpoint (12 pts).\n"

        self.txt_models.config(state=tk.NORMAL)
        self.txt_models.delete("1.0", tk.END)
        self.txt_models.insert(tk.END, mod_text)
        self.txt_models.config(state=tk.DISABLED)

    def _run_cycle_async(self) -> None:
        if self.is_running:
            return

        def _worker():
            self.is_running = True
            self.status_badge.config(text="● RUNNING AGENT CYCLE", foreground="green")
            self.btn_run_cycle.config(state=tk.DISABLED)
            self.btn_curate_fp.config(state=tk.DISABLED)
            try:
                self.pipeline.process_raw_images()
                self.pipeline.assemble_batches_and_upload()
            except Exception as e:
                messagebox.showerror("Agent Error", str(e))
            finally:
                self.is_running = False
                self.status_badge.config(text="● IDLE", foreground="gray")
                self.btn_run_cycle.config(state=tk.NORMAL)
                self.btn_curate_fp.config(state=tk.NORMAL)
                self.root.after(0, self._refresh_metrics)

        threading.Thread(target=_worker, daemon=True).start()

    def _curate_freepik_batch_async(self) -> None:
        if self.is_running:
            messagebox.showwarning("Busy", "Pipeline cycle is currently running. Please wait until finished.")
            return

        def _worker():
            self.status_badge.config(text="● CURATING FREEPIK BATCH", foreground="orange")
            self.btn_curate_fp.config(state=tk.DISABLED)
            try:
                res = self.curator.run_incremental_curation()
                messagebox.showinfo(
                    "Freepik 150-200 Curator",
                    f"✨ Incremental Curation Complete!\n\n"
                    f"Newly Added: {res['added']} golden assets\n"
                    f"Failed Freepik Specs: {res['rejected']} assets\n"
                    f"Current Total in Golden Pool: {res['total_curated']} / 150-200\n\n"
                    f"Location: workspace/freepik_golden_150"
                )
            except Exception as e:
                messagebox.showerror("Curator Error", str(e))
            finally:
                self.status_badge.config(text="● IDLE", foreground="gray")
                self.btn_curate_fp.config(state=tk.NORMAL)
                self.root.after(0, self._refresh_metrics)

        threading.Thread(target=_worker, daemon=True).start()

    def _open_web_dashboard(self) -> None:
        import webbrowser
        import subprocess
        # Start web dashboard background process if not already running
        def _run_server():
            from stockpilot.web_dashboard import start_server
            try:
                start_server()
            except Exception:
                pass
        threading.Thread(target=_run_server, daemon=True).start()
        webbrowser.open("http://localhost:8585")

    def _trigger_cloud_backup(self) -> None:
        snap = self.cloud.create_snapshot()
        messagebox.showinfo("Google Drive Backup", f"State backed up to Google Drive successfully:\n{snap.name}")

    def _export_portable_pkg(self) -> None:
        from stockpilot.core.distribute import export_clean_distribution_package
        zip_path = export_clean_distribution_package()
        messagebox.showinfo(
            "Export Portable Package",
            f"🎉 Clean Distribution Package Created!\n\n"
            f"Path: {zip_path}\n\n"
            "This package contains the full engine with zero personal accounts, zero API keys, and clean template databases—safe to share or install on another PC."
        )


def launch_cockpit() -> None:
    root = tk.Tk()
    app = StockNovaAgentCockpit(root)
    root.mainloop()


if __name__ == "__main__":
    launch_cockpit()
