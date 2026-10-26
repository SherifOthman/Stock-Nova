# 03 — Complete AI Agent Architecture, Credit Engine, Smart QC & Cross-Platform Logic

> **This document is the exact specification for how the AI Agent operates on your PC.** Every rule you specified is written here in full detail so nothing is forgotten during coding.

---

## 1. Multi-Account Gemini / Argon Brain & Zero-Loss History Failover

### How It Works:
1. **Multiple Accounts Registered:**
   - You can add as many Google / Gemini / Argon accounts as you want.
   - You designate **Account #1** as your **Primary Master Argon Account** (`is_primary_argon = 1` in SQLite).
2. **Staying on Account #1 to Preserve Chat History:**
   - For all daily trend research, strategy planning, rejection analysis, and prompt writing, the agent always connects to **Account #1** first so Argon retains its continuous conversation history.
3. **Local Database Memory Snapshot (`agent_memory_snapshots` table):**
   - Every time Argon produces a strategy plan, niche list, or prompt batch, or learns from Adobe/Freepik rejections, Python immediately saves a structured summary in your local SQLite database:
     - *Active winning niches & banned subjects*
     - *Best-performing video model & prompt rules*
     - *Current day's shift progress (how many prompts written, how many left)*
     - *Recent Adobe Stock / Freepik acceptance & rejection stats*
4. **Automatic Failover to Account #2 with Instant Handoff Report:**
   - If Account #1 hits a usage limit in the middle of working, the agent **automatically switches to Account #2** and sends a **Compact Handoff Report** at the top of the message:
     > *"System Handoff Context: Continuing today's shift from Primary Account. Winning categories: [X, Y]. Avoided rejection triggers: [Z]. Winning video model: [M]. Already completed today: 6/12 video prompts. Resume from Video Prompt #7..."*
   - That way, **Account #2 continues seamlessly from the exact spot where Account #1 stopped without losing any history or repeating work!**

---

## 2. Smart Credit Pool Engine (Free 50 $\rightarrow$ Plus 200 $\rightarrow$ Pro 1000)

### 1. Automatic Account Tier & Balance Detection
- You can add a mix of **Free accounts (50 daily credits)**, **Plus accounts (200 monthly credits)**, and **Pro accounts (1000 monthly credits)**.
- When the agent checks your accounts each day, it detects and updates:
  - What tier each account is (`Free`, `Plus`, or `Pro`).
  - How many credits are currently left (`remaining_credits`).
  - Whether today's **50 daily free credits** on each account have been used yet (`daily_free_used = True/False`).

### 2. Strict Priority Order for Spending Credits
Every day, when generating **Videos (Priority #1)**, the agent consumes credits in this exact order:

1. **Stage A — Exhaust All Daily Free 50 Credits First:**
   - Loops through every account that has **50 daily free credits** available today.
   - Uses those 50 daily credits across all accounts first before touching a single monthly Plus or Pro credit!
2. **Stage B — Consume the 200 Monthly Plus Credits (Fast Burn):**
   - Once all daily Free 50s are finished for today, if more videos are scheduled, it pulls from the **Plus (200 monthly credits)** accounts at a fast pace so the 200 credits are finished early and cleanly.
3. **Stage C — Consume the 1000 Monthly Pro Credits Over a Dynamic 10–20 Active-Day Window:**
   - **Never stretch across 30 days:** Spreading 1000 credits across 30 full days is risky because if you don't open the PC for a few days or pause for maintenance, the billing month ends with unused credits wasted!
   - Instead, the engine targets finishing the 1000 Pro credits within **10 to 20 active workdays**.
   - **Dynamic Pace Based on Acceptance Rate (سرعة ديناميكية حسب القبول والرفض):**
     - *Exploration / High-Rejection Mode:* If a niche or video style is new or recently had rejections, the agent slows down daily Pro credit usage (e.g., pacing over ~18–20 days) so it never wastes a huge chunk of your 1000 credits on a style that might get rejected!
     - *High-Acceptance Winner Mode:* Once the portfolio analyzer sees high acceptance on Adobe Stock for the current video model and niche, the agent **accelerates** daily Pro credit usage (finishing within ~10–14 days) to lock in high-converting videos fast!

---

## 3. Video Generation Rules: Model Testing, 100-Credit Ban & Daily Priority

1. **Videos Run Every Single Day (حتى لو الرفع مقفول في أدوبي النهاردة):**
   - Unlike images, daily video credits must be used consistently. Therefore, the agent generates and prepares your daily videos **every day**, even if Adobe Stock's Submit window is closed today.
2. **Permanent Ban on 100-Credit "Quality" Mode (`يثتثني quality الي بياخد 100 كريديت`):**
   - Any video setting or model that costs **100 credits** is hard-blocked in the code (`BLOCKED_MODES = ["quality_100", "100_credit"]`, `max_credits_per_video < 100`).
3. **Automatic Video Model Benchmarking & Winner Selection:**
   - For the allowed low-credit video models, the agent runs small test batches (e.g., 3–5 videos per model) and tracks in SQLite (`video_model_stats` table):
     - Local QC Pass Rate (smooth motion, zero flicker, high sharpness)
     - AI Storyboard Inspection Score
     - Adobe Stock / Freepik Acceptance Rate
   - Once a model proves it produces the best results, the agent **automatically selects that winning model** as the default for daily production!

---

## 4. Smart, Low-Token Quality Control (أهم جزء في البرنامج — الفحص الذكي بدون حرق المفاتيح)

As you pointed out, **Quality Control (QC) is the most critical brain of the entire application**:
- If QC is too careless $\rightarrow$ bad files slip through and ruin your Adobe/Freepik acceptance rate.
- If QC is too dumb/aggressive $\rightarrow$ it throws away good files and wastes your credits and effort.
- If Video QC uploads full video files to Gemini $\rightarrow$ it burns all your Google AI Studio API keys in seconds!

### How We Solve Video QC: The "Smart Storyboard Contact Sheet" + Free Local Checks
1. **Pass 1 — 100% Free Local Technical & Motion Check (`video_qc.py` via OpenCV/FFmpeg):**
   - Runs locally on your PC using **zero API keys**:
     - Checks resolution (1080p / 4K), FPS (24–60), and duration (5–60s).
     - Compares consecutive frames locally to detect **frozen frames**, **black flashes**, **sudden exposure flicker**, or **corrupted encoding**.
2. **Pass 2 — Single-Image Storyboard Sheet Sent to Google AI Studio (`1 API Call per Video!`):**
   - Instead of uploading a 30MB video file to Gemini, Python extracts **8 key frames** evenly spaced across the video (plus any frame where motion peaked) and stitches them into **one single high-resolution 4x2 grid image (Storyboard Contact Sheet)** numbered `Frame 1` to `Frame 8`.
   - It sends that **1 single image** to `gemini-2.5-flash` via your rotating Google AI Studio API keys!
   - Gemini inspects the 8-frame storyboard in 2 seconds to verify:
     - *Do objects/people stay consistent from Frame 1 to Frame 8, or do they morph/melt?*
     - *Are there extra limbs, deformed hands, watermarks, or garbled text?*
     - *Is the scene commercially useful for stock buyers?*
   - **Result:** The AI sees the full story of the video while using **95% fewer tokens** so your free Google AI Studio API keys last all day!
3. **Pass 3 — Mandatory Audio Stripping (`ffmpeg -an`):**
   - Because Adobe Stock rejects AI videos with audio tracks, `video_processor.py` automatically runs `ffmpeg -i input.mp4 -c:v copy -an output.mp4` (or clean H.264 re-encode when needed) so **100% of prepared videos are completely silent (`بدون صوت نهائياً`)**.

### Calibrated 3-Tier Decision System (عشان ميظلمش ملف كويس ولا يعدي ملف وحش)
Every inspected image and video is given a score from `0` to `100` and placed into one of **3 buckets** (and **never permanently deleted from disk** without your permission):
1. **`Approved (80–100)`:** Crisp, clean, zero defects $\rightarrow$ Proceeds automatically to Upscale (for images) and CSV Generation.
2. **`Borderline / Needs Quick Look (60–79)`:** Good composition and sharpness, but the AI noticed a minor question mark $\rightarrow$ Placed in the **"Needs Quick Look"** filter in your Review Queue so you can approve or reject it in 1 second instead of the AI throwing away a potentially great file!
3. **`Rejected (<60 or Hard Defect)`:** Clear anatomy error, blurry, watermark, or broken video motion $\rightarrow$ Moved to `3_Rejected` with the exact reason logged so the agent learns from it.

---

## 5. Image Upscaling Rules: Strictly `2x` (`x2`) + Commercial License Safety

1. **Strictly `2x` Upscaling (`scale=2`):**
   - Since your generated images are already `2048×2048` or `~3000×1500`, `upscaler.py` will run at **strictly `2x` (`scale=2`)**, turning them into crisp **4K (`4096×4096` / `6000×3000`)** without the ugly pixelation or plastic over-smoothing caused by `4x`.
2. **Commercial License Safety + Model Sample Tester:**
   - `model_license_validator.py` blocks any upscaling model weights that have non-commercial restrictions so your stock accounts are 100% legally and technically safe.
   - Defaults to **High Fidelity (`ultramix_balanced` / `remacri` / `high_fidelity`)** and includes a **"Test Upscale Models on 3 Sample Images"** tool that compares sharpness and detail retention between the original image and the 2x upscaled output to lock onto the sharpest model.

---

## 6. Dynamic Image Buffer & Dual-Platform Tracking (Adobe Stock + Freepik)

### 1. Why Images Use a Dynamic Rolling Buffer (مش رقم يومي ثابت)
- On Adobe Stock, there is **no fixed visible counter** telling you how many uploads remain—some days Submit/Upload is completely closed, and on another day it opens suddenly or stops mid-batch after accepting 20 files.
- **How the Agent Handles This Dynamically:**
  1. It tracks your **Rolling 7-Day & 30-Day Acceptance History** in SQLite (`platform_history` table).
  2. Example: If last week Adobe Stock accepted 100 of your images with a high acceptance rate, the agent predicts the next opening window will accept around **120 images** (or ~80 if rejection rate rose).
  3. The agent maintains a **Ready Buffer (`مخزون جاهز بزيادة شوية`)** in `2_Ready_For_Upload` equal to **Predicted Next Window + 25% extra safety buffer** (e.g., ~150 ready images always sitting prepared on disk).
  4. **Daily Decision:**
     - If your Ready Buffer already has 150 images waiting because Adobe's Submit window was closed for the last 3 days $\rightarrow$ **the agent does NOT generate unnecessary extra images today** (it only runs your daily Videos!).
     - As soon as Adobe's window opens and you submit 100 images, the buffer drops to 50 $\rightarrow$ **the agent automatically generates 100 new images over the next shift(s) to refill the buffer back to 150!**

### 2. Shared Assets Across Adobe Stock & Freepik (`نفس الصور للموقعين بحالة مستقلة`)
- Every asset in SQLite has two independent status columns:
  - `adobe_status`: `ready` | `submitted` | `accepted` | `rejected`
  - `freepik_status`: `ready` | `submitted` | `accepted` | `rejected`
- **No Metadata Embedded Inside Files (`إلغاء حقن الكلمات جوه الصورة أو الفيديو`):**
  - Because the exact same image/video file is uploaded to **both Adobe Stock and Freepik**, and each site requires different metadata rules, **we do NOT inject IPTC tags into the image or video files**.
  - Instead, the image and video files stay **100% clean**, and `batch_exporter.py` generates **two separate, ready-to-use CSV files**:
    1. `Adobe_Stock_Ready_Batch.csv` (formatted for Adobe Stock)
    2. `Freepik_Ready_Batch.csv` (formatted for Freepik)
- **Independent Supply & Demand:**
  - If you have 200 ready images, and Adobe only accepted 60 before closing its upload window while Freepik took all 200:
    - The database marks 140 images as *still ready for Adobe*, and 0 remaining for Freepik.
    - If Freepik is active and needs more images while Adobe is still full, the agent generates new images for Freepik (and automatically marks them ready for Adobe's future buffer too).
  - Right now, while your Freepik account is not active yet, you can toggle `Freepik Daily Loop = Paused (Onboarding Mode)` in Settings so daily production focuses on Adobe Stock while keeping all files marked ready for Freepik when your account opens!

---

## 7. Dedicated "Freepik 150 Onboarding Gate" Engine (`freepik_curator.py`)

Because Freepik's initial 150-image test is reviewed manually by human inspectors:
1. **Separate Tab & Dedicated Button:** Lives in its own **Freepik 150 Gate** tab so it never mixes with daily batches.
2. **Ultra-Strict Manual Review Filter:**
   - Checks Freepik's manual rejection reasons and applies stricter rules than normal daily QC (higher sharpness floor, zero depth-of-field anomalies, zero symmetry/hand flaws, high commercial lighting, and strict visual diversity).
3. **Persistent Stateful Database (`freepik_150_ledger` table):**
   - Stores the `SHA-256` hash of every single image it checks (`status = 'approved_150'` or `'rejected_150'`).
   - If you run it today on a folder and it finds **100 approved images** and **20 rejected images**, it saves all 120 in the database.
   - When you download more images later and click the button again, **it automatically skips the 120 images it already reviewed** and only checks the new files until you reach **150 / 150**!

---

## 8. Portfolio Analyzer (Reading Accepted vs. Not Accepted from Your Accounts)

- Using your logged-in contributor session (`adobe_stock.py` / `freepik.py`), the agent inspects:
  1. **The "Not Accepted" (Rejected) Page:** Reads which files were rejected and the exact rejection reason (*Technical Issues*, *Similars*, *Quality*, *IP*), linking them back to the asset and prompt in your SQLite database.
  2. **The "Accepted" Page:** Counts how many files were accepted since the last check and which categories/styles succeeded.
- **Daily Strategy Update:**
  - Updates `prompt_outcomes` in SQLite so tomorrow's prompts automatically generate more of what got accepted and avoid styles/subjects that got rejected.

---

## 9. Safe Telegram Notification Rule (`رسالة التليجرام الآمنة`)

When the daily shift finishes:
- **Passive Upload Window Check:** Only checks whether Submit/Upload is open if it can be seen safely without triggering automated clicks or suspicious polling.
- **If Submit Is Safely Confirmed Open:** Sends your daily Telegram report **with the direct link** to open the Submit page.
- **If Submit Is Closed (or Unknown):** Sends **only the daily summary report** (how many videos and images were prepared, how many credits remain) **without sending a submit link**, keeping your account 100% safe.
