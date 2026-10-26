# 02 — Professional UI/UX Redesign, Color System & 5-Tab Architecture

> **Design Goal:** A clean, fast, modern, jargon-free desktop interface with **working Dark Mode and Light Mode**, a **real Spotlight Tour**, **visual thumbnails**, a **live Credit Pool tracker (Free 50 / Plus 200 / Pro 1000)**, and a **dedicated separate tab for the Freepik 150 Gate**.

---

## 1. Professional Color System (Dark Mode & Light Mode Fixed)

In your current screenshots (`04_asset_vault.png` to `08_ai_models_guide.png`), Light Mode is broken because the `<main>` background stays dark slate (`#1e293b`) and buttons stay dark grey (`#334155`) with dark unreadable text.

We will implement a strict, high-contrast CSS Variable Theme System in `stockpilot/ui/app.html`:

### Dark Theme (Default — Sleek Studio Slate)
- **App Background (`--bg-app`):** `#0B0F17` (Deep Obsidian Slate)
- **Sidebar & Surface Cards (`--bg-surface`):** `#131B2E` (Elevated Midnight Card)
- **Secondary / Hover Surface (`--bg-elevated`):** `#1E293B` (Interactive Slate)
- **Primary Text (`--text-primary`):** `#F8FAFC` (Crisp White)
- **Secondary Text (`--text-secondary`):** `#94A3B8` (Muted Cool Grey)
- **Border Color (`--border-subtle`):** `#1E293B`
- **Primary Brand Accent (`--accent-primary`):** `#3B82F6` (Electric Royal Blue)
- **Status Badges:**
  - **Success / Approved:** `#10B981` (Emerald Green)
  - **Warning / Needs Quick Look:** `#F59E0B` (Amber Gold)
  - **Danger / Rejected:** `#EF4444` (Coral Red)

### Light Theme (Fixed 100% — Crisp Daylight Studio)
- **App Background (`--bg-app`):** `#F1F5F9` (Soft Alabaster Grey — replaces the broken `#1e293b` dark background!)
- **Sidebar & Surface Cards (`--bg-surface`):** `#FFFFFF` (Pure Crisp White)
- **Secondary / Button Surface (`--bg-elevated`):** `#E2E8F0` (Light Cool Grey — replaces the broken dark `#334155` buttons!)
- **Primary Text (`--text-primary`):** `#0F172A` (Deep Ink Navy)
- **Secondary Text (`--text-secondary`):** `#475569` (Readable Slate)
- **Border Color (`--border-subtle`):** `#CBD5E1`
- **Primary Brand Accent (`--accent-primary`):** `#2563EB` (Deep Royal Blue)

---

## 2. Clean 5-Page Navigation Structure

To keep daily production effortless while keeping your **Freepik 150 Initial Onboarding** completely separate from normal daily batches, the sidebar will have **5 clear, well-organized pages**:

### Page 1: Home — Daily Auto-Pilot & Credit Pools (`الرئيسية والموظف اليومي`)
1. **Top Status Bar (Your Digital Employee):**
   - Shows in plain words what the agent is doing right now:
     - Example: *"Auto-Pilot Active: Consuming Free 50 Credits on Account #2 (Generating Video 4 of 12 — Model: Kling Standard)..."*
   - Includes a 1-click **[Auto-Pilot: ON / Pause]** toggle and a quick command input if you want to give it a special instruction today.
2. **Live Credit Pools & Accounts Card (متابعة الكريديت لحظة بلحظة):**
   - **Free Daily Pool (50 Credits / Account — Priority #1):** Shows how many Free accounts finished their 50 credits today vs. how many are left (e.g., *"3 of 4 Free Accounts Completed Today — 50 Free Credits Remaining"*).
   - **Plus Pool (200 Monthly Credits — Priority #2):** Progress bar showing Used vs. Remaining out of 200 (e.g., *"140 / 200 Used — 60 Left"*).
   - **Pro Pool (1000 Monthly Credits — Priority #3, 10–20 Day Dynamic Pace):** Progress bar showing Used vs. Remaining out of 1000 (e.g., *"420 / 1000 Used — 580 Left — On track to finish in 12 active days"*).
3. **Platform Buffer & Readiness Summary (مخزون الصور والفيديوهات لـ Adobe و Freepik):**
   - **Videos Ready:** Count of finished, audio-stripped, QC-passed videos ready for upload.
   - **Adobe Stock Image Buffer:** Shows how many ready images are waiting in your buffer vs. predicted weekly window (e.g., *"115 / 120 Ready in Buffer — Upload Window: Waiting / Open"*).
   - **Freepik Ready Queue:** Shows how many ready assets are queued for Freepik (even while your Freepik account is waiting for onboarding approval, it tracks which files are ready for Freepik later).
4. **Collapsible Activity Drawer (at the bottom):**
   - Keeps the screen clean while letting you click to expand recent step-by-step history whenever you want.

---

### Page 2: Review Queue — Visual Gallery & Separate CSV Exports (`طابور المراجعة والـ CSV`)
1. **Visual Photo & Video Thumbnail Grid:**
   - Displays real image thumbnails and video preview cards (never a blind text table!).
   - Each card shows:
     - **Media Type Badge:** `VIDEO` (with model name) or `IMAGE (2x 4K)`
     - **Quality Status:** `Approved` (Green), `Needs Quick Look` (Amber — borderline cases so good files are never thrown away by mistake!), or `Rejected` (Red — with exact reason).
     - **Platform Badges:** Shows independently whether this file is `Ready for Adobe`, `Uploaded to Adobe`, `Ready for Freepik`, or `Uploaded to Freepik`.
2. **Slide-Out Preview & Quick Edit Panel:**
   - Click any thumbnail to view the full image or play the video, read or edit its English Title and 49 Keywords, or click **Approve** / **Reject**.
3. **Separate Clean CSV Export Bar (No Keywords Embedded Inside Files!):**
   - Buttons at top right:
     - **"Export Adobe Stock CSV"** (creates Adobe's exact CSV format for the batch without modifying the image/video binaries).
     - **"Export Freepik CSV"** (creates Freepik's exact CSV format for the same clean files).
     - **"Mark Selected as Uploaded to Adobe / Freepik"** (updates the database so the agent knows which platform received which files!).

---

### Page 3: Freepik 150 Gate — Dedicated Onboarding Curator (`بوابة الـ 150 صورة لفري بيك`)
*Kept 100% separate from the daily loop as you requested, specifically designed to pass Freepik's strict manual human review.*
1. **Progress Header:**
   - Shows **`Approved Golden Images: X / 150`**, **`Already Inspected & Skipped: Y`**, and **`Rejected by Strict Filter: Z`**.
2. **How It Works (Stateful & Incremental):**
   - **Folder Selector + "Scan & Pick Best Candidates" Button:** Point it to your work folder and click the button.
   - **Strict Manual-Review Rules:** Checks Freepik's known manual rejection rules (zero micro-artifacts, zero hand/finger errors, zero background blur glitches, strong commercial subject, and strict visual diversity so no two images look similar).
   - **Remembers Every File Across Runs:** Every image it inspects is saved by file hash in SQLite (`freepik_150_ledger`). If you only had 100 good images today and 20 rejected, it saves those 120 records. Next week when you add 80 new images to the folder and click the button again, **it automatically skips the 120 images it already checked** and only reviews the new ones until you complete the full **150 / 150**!
   - **Visual Grid of the 150 Golden Picks:** Lets you see all selected images and remove/swap any image with 1 click.

---

### Page 4: Portfolio Intelligence & Learning (`تحليل الحسابات والقبول والرفض`)
1. **Adobe Stock & Freepik Account Analyzer:**
   - Button + automatic daily sync to inspect your **Accepted** vs. **Not Accepted (Rejected)** pages on Adobe Stock (and Freepik once active).
   - Shows:
     - **Total Accepted vs. Rejected** this week and this month.
     - **Why Files Were Rejected:** Breakdown of rejection reasons (*Technical Issues*, *Similars*, *Quality/Artifacts*) and which prompt styles caused them.
     - **Winning Video Models & Image Styles:** Shows which video generator model (excluding 100-credit Quality) and which image categories have the highest acceptance rate.
     - **What the AI Changed Automatically:** Plain-language list of adjustments the agent made to its prompts and quality filter based on your real account results.

---

### Page 5: Settings, Accounts & API Keys (`الإعدادات والحسابات`)
1. **Gemini / Argon Accounts Manager:**
   - Add multiple accounts, mark your **#1 Primary Master Argon Account** (to preserve chat history), and view/set each account's tier (**Free 50/day**, **Plus 200/mo**, **Pro 1000/mo**).
2. **Google AI Studio API Keys:**
   - Add multiple free AI Studio keys for fast background inspection & keyword writing, with a working **"Test Key"** button and automatic rotation.
3. **Stock Platform Accounts (Adobe Stock & Freepik):**
   - Enable/disable each platform independently (e.g., Adobe Stock = *Active*, Freepik = *In 150 Onboarding Mode* or *Active*), plus optional FTP credentials.
4. **Upscaler & Video Rules:**
   - Locked to **2x Upscaling (`scale=2`)**, commercial-safe **High Fidelity** model selector + **"Run 3-Image Model Comparison Test"** button.
5. **Telegram Notifications & Workspace Folder:**
   - Configure Bot Token, Chat ID, Test Message button, and your local Workspace path.
