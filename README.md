# Telegram YouTube Summarizer and Q&A Bot

Business-focused assistant for YouTube:
- Accepts a YouTube link
- Fetches transcript
- Generates structured summary
- Answers follow-up questions grounded in transcript
- Supports multilingual output

## Assignment Fit

- End-to-end flow: implemented
- Structured summary: implemented
- Transcript-grounded Q&A: implemented
- English + Indian language support: implemented
- Error handling for invalid links, missing transcripts, long content: implemented

## Evaluation Criteria Coverage

### 1) End-to-end functionality (30%)

- Implemented:
  - User sends YouTube link
  - Transcript fetched
  - Structured summary returned
  - Follow-up Q&A supported
  - OpenClaw runtime path available (`openclaw_runtime.py`)

### 2) Summary quality (20%)

- Implemented:
  - Enforced structured summary format:
    - `Video Title`
    - `5 Key Points`
    - `Important Timestamps`
    - `Core Takeaway`
  - Long transcript chunking/compression before final summary generation
  - Auto-repair/fallback if output format drifts

### 3) Q&A accuracy (20%)

- Implemented:
  - Transcript-grounded retrieval for relevant context
  - Follow-up question resolution using recent context
  - Strict fallback when evidence is missing:
    - `This topic is not covered in the video.`
  - Timestamp citation validation to reduce hallucinations

### 4) Multi-language support (15%)

- Implemented:
  - English default
  - Indian languages including Hindi, Tamil, Telugu, Kannada
  - Flexible `/setlang <language>` for other languages/scripts
  - Language-aware summary and Q&A responses

### 5) Code quality and structure (10%)

- Implemented:
  - Service-layer separation (`transcript`, `summarizer`, `qa`)
  - Utility modules for language and URL parsing
  - Dedicated OpenClaw runtime bridge
  - Explicit session persistence layer (SQLite)

### 6) Error handling (5%)

- Implemented:
  - Invalid URL handling
  - Missing transcript handling
  - API key and quota/rate-limit style errors (401/429) with graceful messages
  - Long-content safeguards and truncation notices
  - Telegram polling conflict handling

## Project Structure

- `bot.py`: standalone Telegram polling runner (fallback/dev)
- `openclaw_runtime.py`: OpenClaw-first runtime bridge
- `config.py`: provider configuration
- `services/transcript.py`: transcript + title + fallback
- `services/summarizer.py`: summary/deepdive/actionpoints
- `services/qa.py`: transcript-grounded Q&A
- `utils/helpers.py`: YouTube URL parsing
- `utils/language.py`: language extraction/normalization
- `openclaw-skills/youtube-telegram-assistant/SKILL.md`: OpenClaw skill contract

## Architectural Decisions

### 1) How transcript is stored

- Transcript retrieval source:
  - Primary: `youtube-transcript-api`
  - Fallback: `yt-dlp` based fallback transcription path when captions are unavailable
- Per-message transcript payload kept in session state:
  - `transcript` (plain text)
  - `transcript_lines` (line-by-line with `[mm:ss]` timestamps)
  - `timeline_markers`
  - `source_language`, `source_type`, `video_title`
- Long transcript protection:
  - Transcript text is capped (`MAX_TRANSCRIPT_CHARS`) to avoid overflow and unstable prompts.

### 2) How context is managed

- Session store: SQLite database `data/openclaw_sessions.db` in `openclaw_runtime.py`
- Concurrency:
  - WAL mode enabled
  - per-user row keyed by `user_id`
  - UPSERT on every request to avoid JSON file race conditions
- Context fields maintained per user:
  - selected language
  - current video transcript payload
  - `qa_history` (last turns)
  - `last_summary`

### 3) How questions are answered

- Query rewrite step for follow-up questions:
  - Pronouns/references are resolved into a self-contained question.
- Retrieval step:
  - Relevant transcript lines are selected by lexical overlap against the resolved query.
- Strict grounded answering:
  - If no evidence match, bot returns exact fallback:
    - `This topic is not covered in the video.`
  - Answer must include timestamp citations like `[03:15]`.
  - If citation is missing or not in retrieved evidence, response is forced to fallback.

### 4) Chunking / embeddings / caching decisions

- Chunking:
  - Summarizer splits long transcripts into chunks, compresses chunk notes, then produces final output.
  - Telegram long responses are chunked to avoid message length limits.
- Embeddings:
  - Not used in current version (lighter setup, zero vector DB dependency).
  - Retrieval uses lexical overlap on timestamped transcript lines.
- Caching:
  - Session-level caching is active (latest transcript, summary, and Q&A context per user).
  - No cross-video/global cache yet (can be added later with transcript hash keys).

### 5) Accuracy choices

- Prompt-only grounding was not considered sufficient.
- Added hard post-validation in Q&A:
  - evidence gate before answer generation
  - citation validation after answer generation
- Summary output is format-validated and auto-repaired to always include:
  - `Video Title`
  - `5 Key Points`
  - `Important Timestamps`
  - `Core Takeaway`

## Design Trade-offs

- Retrieval quality vs operational simplicity:
  - Current system uses lexical overlap retrieval on timestamped transcript lines.
  - This avoids vector DB setup complexity but may miss semantically similar wording.
- Cost vs depth:
  - Transcript is capped and chunk-compressed for token efficiency.
  - This improves reliability/cost but can reduce very fine-grained detail for extremely long videos.
- Strict grounding vs answer recall:
  - Hard fallback and citation checks reduce hallucinations.
  - Some borderline questions may return fallback instead of speculative answers.
- Session robustness vs portability:
  - SQLite with WAL gives safe concurrent access and clean session management.
  - Adds local DB dependency compared to plain JSON file.

## Environment

Create `.env`:

```env
TELEGRAM_TOKEN=your_telegram_bot_token
OPENAI_API_KEY=your_api_key
```

OpenRouter example:

```env
TELEGRAM_TOKEN=your_telegram_bot_token
OPENROUTER_API_KEY=sk-or-v1-xxxx
OPENAI_BASE_URL=https://openrouter.ai/api/v1
CHAT_MODEL=openai/gpt-4o-mini
OPENROUTER_SITE_URL=https://your-site.example
OPENROUTER_APP_NAME=yt-telegram-bot
```

Optional:

```env
OPENROUTER_SITE_URL=https://your-site.example
OPENROUTER_APP_NAME=yt-telegram-bot
```

## Install

```powershell
cd c:\Users\avish\Yt-Telegram_bot
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Optional transcript fallback dependency:

```powershell
pip install yt-dlp
```
## OpenClaw Primary Runtime

Use OpenClaw as the primary Telegram runtime for submission.

### 1) Onboard OpenClaw

```powershell
openclaw onboard --non-interactive --accept-risk --mode local --workspace c:\Users\avish\Yt-Telegram_bot --auth-choice openrouter-api-key --openrouter-api-key <YOUR_KEY> --skip-channels --skip-ui --skip-daemon --skip-health
```
### 2) Enable Telegram plugin and add channel token

```powershell
openclaw plugins enable telegram
openclaw channels add --channel telegram --token <BOTFATHER_TOKEN> --account default --name ytbot
```

### 3) Install custom skill

```powershell
mkdir %USERPROFILE%\.openclaw\skills\youtube-telegram-assistant
copy openclaw-skills\youtube-telegram-assistant\SKILL.md %USERPROFILE%\.openclaw\skills\youtube-telegram-assistant\SKILL.md
openclaw skills check
```

Expected ready skill:
- `youtube-telegram-assistant`
### 4) Verify bridge logic locally

```powershell
python openclaw_runtime.py --user "demo-user" --text "https://youtube.com/watch?v=dQw4w9WgXcQ"
python openclaw_runtime.py --user "demo-user" --text "What is the core takeaway?"
python openclaw_runtime.py --user "demo-user" --text "/actionpoints"
```
### 5) Start gateway and check health

```powershell
openclaw gateway run
```

Or background:

```powershell
Start-Process -WindowStyle Hidden -FilePath openclaw -ArgumentList 'gateway','run'
```

Health:

```powershell
openclaw gateway health
openclaw channels status
```

Expected:
- Gateway Health OK
- Telegram running

### 6) Pair your Telegram user (if access not configured)

If bot replies with pairing code, approve it from owner machine:

```powershell
openclaw pairing approve telegram <PAIRING_CODE>
openclaw pairing list
```

Example bot link:
- `https://t.me/yotubSummarybot`

## Runtime Rule (Important)

- For strict OpenClaw compliance: run only OpenClaw Telegram polling.
- Do not run `python bot.py` at the same time (prevents `getUpdates` conflict).
- Keep `bot.py` for fallback/dev only.

## Step-by-Step Run (Daily Use)

### Quick start (manual)

```powershell
cd c:\Users\avish\Yt-Telegram_bot
openclaw gateway run
```

In another terminal:

```powershell
openclaw health
openclaw channels status
```

Open bot chat directly:

```powershell
start https://t.me/yotubSummarybot
```

### 24x7 without admin (recommended on restricted Windows)

Use included script:
- `run_openclaw_24x7.ps1`

Start it:

```powershell
cd c:\Users\avish\Yt-Telegram_bot
powershell -ExecutionPolicy Bypass -File .\run_openclaw_24x7.ps1
```

Script behavior:
- runs `openclaw gateway run`
- auto-restarts gateway if it exits
- logs to `data/openclaw_gateway.log`

Auto-start at login (no admin):

```powershell
$startup = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
$cmd = 'powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File "c:\Users\avish\Yt-Telegram_bot\run_openclaw_24x7.ps1"'
Set-Content -Path (Join-Path $startup "OpenClawGateway.cmd") -Value $cmd
```

### 24x7 with admin (optional service/task mode)

```powershell
openclaw gateway install
openclaw gateway start
openclaw gateway status
```

If install shows `Access is denied`, use the non-admin method above.

## Troubleshooting

### 1) Polling conflict (`terminated by other getUpdates request`)

Cause:
- both `openclaw gateway run` and `python bot.py` are running.

Fix:
- stop one runtime and keep only OpenClaw as primary.

### 2) Gateway not reachable / 1006 abnormal closure

Run:

```powershell
openclaw gateway run
openclaw health
openclaw channels status
```

If still failing:
- ensure no duplicate OpenClaw runtime in another terminal/session
- verify Node version (`node -v`) is 22+
- re-run `openclaw configure`

### 3) Pairing required (`OpenClaw: access not configured`)

Approve code from owner side:

```powershell
openclaw pairing approve telegram <PAIRING_CODE>
```

### 4) Transcript unavailable

- try another public video
- install fallback:

```powershell
pip install yt-dlp
```

### 5) API 401 / 429 errors

- `401`: invalid provider key or base URL
- `429`: quota/rate-limit exceeded
- verify `.env` values and billing/quota

## Security Notes

- Never commit real tokens/API keys to git.
- If keys were exposed in logs/screenshots, rotate immediately:
  - Telegram bot token (BotFather)
  - OpenRouter/OpenAI API key

## Output Contract

Summary sections:
- Video Title
- 5 Key Points
- Important Timestamps
- Core Takeaway

Q&A fallback when answer not in transcript:

`This topic is not covered in the video.`

## Commands Supported in Flow

- `/setlang <language>`
- `/summary`
- `/research`
- `/fulltranscript`
- `/deepdive`
- `/actionpoints`

## Bonus Coverage

- Smart caching of transcripts:
  - Session-level caching is implemented (per-user transcript and summary context).
- Cost optimization (token efficiency):
  - Transcript chunking/compression and capped context windows are implemented.
- Clean session management:
  - Implemented using SQLite (`openclaw_sessions.db`) with WAL mode and per-user UPSERT.
- Bonus commands:
  - `/summary` implemented
  - `/deepdive` implemented
  - `/actionpoints` implemented

## Edge Cases

- Invalid YouTube URL: handled
- No transcript available: handled (caption failure + fallback path + graceful message)
- Non-English transcript: handled (source language tracked and multilingual output supported)
- Very long video / transcript: handled (transcript capping + summarization chunking)
- Rate limiting / quota constraints: handled with graceful user-facing errors
- Network/provider errors: handled with graceful user-facing errors

## Example Screenshots

Add your screenshots to `screenshots/` with these names:
- `screenshots/summary.png`
- `screenshots/qa.png`

README image blocks:

![Summary Flow](screenshots/summary.png)
![Q&A Flow](screenshots/qa.png)

## Demo Video

Place your recorded video in:
- `assets/videos/`

Suggested filename:
- `assets/videos/demo.mp4`

If file size is too large for GitHub, upload video externally (Google Drive/YouTube) and add the link here:
- Demo link: `https://drive.google.com/drive/folders/1CnNoSFZgCptxyFv1eyFn7E9AcHzw2djE?usp=drive_link`
