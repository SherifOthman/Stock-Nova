# StockNova AI — Master Architecture, Production Logic & UI Redesign Plan

> **Every detail you specified is locked into this Master Plan and saved in `/docs/01` through `/docs/05`.**  
> Click **Proceed** on this card whenever you are ready for me to start building and restructuring the code according to this exact blueprint.

---

## 1. Multi-Account Gemini / Argon & Credit Pool Engine

### A. Primary Argon Email Priority + Zero-Loss Failover (`antigravity_bridge.py` & `memory_context.py`)
* **Multiple Accounts Supported:** You can add multiple Google Gemini / Argon accounts in Settings.
* **Master Argon Account (#1):** One account is marked as your **Primary Argon Brain** so all daily planning and trend analysis stay in one continuous chat history.
* **Local SQLite Memory & Instant Handoff Report:**
  * Every decision, winning niche, rejection lesson, and prompt batch is saved immediately in your local SQLite database (`agent_memory_snapshots`).
  * If Account #1 hits a limit mid-task, the agent **automatically switches to Account #2** and sends a structured **Handoff Report** from the local database so Account #2 continues from the exact point where Account #1 stopped—losing zero history!

### B. Automatic Account Detection & Credit Pool Dashboard (`credit_pool_manager.py`)
* The agent inspects your connected accounts to identify which are **Free (50 daily credits)**, **Plus (200 monthly credits)**, and **Pro (1000 monthly credits)**, and displays clear live counters on the Home dashboard:
  * **Free 50/Day Accounts:** Which accounts finished their 50 today and how many free credits remain today.
  * **Plus 200/Month Pool:** Used vs. Remaining out of 200.
  * **Pro 1000/Month Pool:** Used vs. Remaining out of 1000.

### C. Strict Credit Spending Order
1. **Priority #1 — All Free 50 Daily Credits First:** Opens every account with daily free 50 credits and consumes all 50 daily credits across all accounts first.
2. **Priority #2 — Plus (200 Monthly) Fast Burn:** Finishes the 200 Plus credits quickly next.
3. **Priority #3 — Pro (1000 Monthly) Over a Dynamic 10–20 Active-Day Window (Never 30 Days!):**
   * **Why 10–20 days instead of 30:** So if you don't open the PC on some days, the month never ends with unused wasted credits!
   * **Dynamic Speed Based on Acceptance Rate:** Paces slightly slower (~18–20 days) while testing new video styles so credits aren't wasted on a style that gets rejected, and **accelerates (~10–14 days)** once a video model and niche show high acceptance!

---

## 2. Video-First Daily Production, Model Testing & Smart Low-Token QC

1. **Videos Run Every Single Day (Priority #1):**
   * Even on days when Adobe Stock's upload/submit window is closed, the agent runs daily video production to utilize your daily credits.
2. **Permanent Ban on 100-Credit "Quality" Video Mode:**
   * Any video mode costing **100 credits (`Quality`)** is hard-blocked in the code.
3. **Automatic Video Model Testing & Winner Selection:**
   * Tests the allowed low-credit video models on small sample batches, tracks their QC pass rate and Adobe/Freepik acceptance rate in SQLite (`video_model_stats`), and automatically locks onto the highest-performing model.
4. **Smart "8-Frame Storyboard Grid" Video QC (Saves 95% of Google AI Studio Keys!):**
   * **Stage 1 (100% Free Local Check):** OpenCV/FFmpeg checks resolution, FPS, duration, frozen frames, and flicker locally on your PC using **zero API keys**.
   * **Stage 2 (1 Single Storyboard Image to AI Studio):** Instead of uploading a full video (which would burn your free API keys in seconds), Python extracts **8 key frames** across the video and stitches them into **one single 4×2 Storyboard Image**.
   * Google AI Studio (`gemini-2.5-flash`) inspects that **1 single image** to verify smooth motion progression, zero morphing objects, zero extra limbs, and zero watermarks!
5. **Mandatory Audio Stripping (`ffmpeg -an`):**
   * Every video is automatically stripped of audio tracks (`بدون صوت نهائياً`) because Adobe Stock rejects audio in AI videos.

---

## 3. Calibrated Image QC, `2x` Upscaling & Separate Clean CSVs

1. **Calibrated 3-Tier Quality Decision (لا يظلم ملف كويس ولا يعدي ملف وحش):**
   * **`Approved (80–100)`:** Proceeds automatically to 2x Upscale and CSV export.
   * **`Borderline / Needs Quick Look (60–79)`:** Placed in a *"Needs Quick Look"* tab in your Review Queue instead of deleting good work by mistake!
   * **`Rejected (<60 or Hard Defect)`:** Moved to `3_Rejected` with the exact reason saved for learning.
2. **Strictly `2x` Upscaling (`scale=2`) + Commercial License Check:**
   * Since source images are `2048×2048` or `~3000×1500`, `upscaler.py` runs strictly at **`2x` (`scale=2`)** to produce crisp 4K without pixelation.
   * Blocks non-commercial models, defaults to commercial-safe **High Fidelity**, and includes a 3–4 image sample comparison tester.
3. **NO Keywords Embedded Inside Image/Video Files — Separate Platform CSVs Only!**
   * Because the **exact same image/video** will be uploaded to **both Adobe Stock and Freepik** (which have different CSV formats), we **do NOT inject IPTC keywords inside the image or video files**.
   * Media files stay 100% clean, and the app generates separate **`Adobe_Stock_Batch.csv`** and **`Freepik_Batch.csv`** files.

---

## 4. Dynamic Rolling Image Buffer, Dual-Platform Tracking & Portfolio Intelligence

1. **Dynamic Image Buffer (Instead of Fixed Daily Numbers):**
   * Because Adobe Stock's upload/submit window opens and closes dynamically without a fixed counter, the agent analyzes last week's **Accepted vs. Rejected** numbers to predict the next window size (e.g., 100 accepted last week $\rightarrow$ prepare ~120–140 images in the Ready Buffer).
   * It keeps that **surplus Ready Buffer** sitting on disk so the moment Submit opens, your images are ready immediately—and once the buffer is full, it stops generating extra images until you submit them!
2. **Independent Dual-Platform Tracking (`adobe_status` & `freepik_status`):**
   * The database tracks each file separately for Adobe Stock and Freepik. If you have 200 images and Adobe takes 60 before closing while Freepik takes 200, the system knows 140 are still waiting for Adobe and generates new ones if Freepik needs more.
   * Works seamlessly today with **Adobe Stock active** while **Freepik is paused/in onboarding**, and supports both simultaneously whenever Freepik is active.
3. **Contributor Account Analyzer (Accepted vs. Not Accepted Pages):**
   * Inspects your Adobe Stock (and Freepik) **Not Accepted** and **Accepted** pages daily to record rejection reasons, compare accepted vs. rejected styles, and automatically adjust future prompts.
4. **Safe Telegram Alert:**
   * Sends a daily Telegram summary when work finishes. Includes the direct Submit link **only** if Submit is safely confirmed open; otherwise sends the text summary only so your account is never put at risk.

---

## 5. Dedicated "Freepik 150 Gate" Tab & Professional 5-Page UI Redesign

1. **Dedicated Separate Tab for `Freepik 150 Gate`:**
   * Completely separate from the daily loop.
   * Applies ultra-strict manual-review rules and stores every checked image hash in SQLite (`freepik_150_ledger`).
   * If it finds 100 good images and 20 rejected today, it remembers all 120—so when you add more images later and click the button, **it skips the 120 it already reviewed** and only checks the new ones until you complete **150 / 150**!
2. **Professional 5-Page Desktop UI (Dark Mode & Light Mode Fixed 100%):**
   * **Page 1 — Home:** Self-Driving Daily Employee status + Live Credit Pools (Free 50 / Plus 200 / Pro 1000) + Adobe/Freepik Buffer status.
   * **Page 2 — Review Queue:** Real visual image/video thumbnails + *Needs Quick Look* filter + Separate Adobe & Freepik CSV export buttons.
   * **Page 3 — Freepik 150 Gate:** Dedicated stateful 150-image curator.
   * **Page 4 — Portfolio Intelligence:** Accepted vs. Not Accepted account analysis & video model winner stats.
   * **Page 5 — Settings & Accounts:** Multi-account Gemini/Argon manager, AI Studio API keys, 2x High-Fidelity upscaler, Telegram, and per-user isolated workspace folders.
