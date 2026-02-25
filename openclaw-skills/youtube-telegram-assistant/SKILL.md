---
name: youtube-telegram-assistant
description: Use this skill for YouTube link summarization and transcript-grounded Q&A in multilingual output. OpenClaw should call the local runtime bridge in this repo.
---

# YouTube Telegram Assistant (OpenClaw Primary)

## Runtime contract
Use the local bridge runtime for each incoming user message:

`python openclaw_runtime.py --user "<stable_user_id>" --text "<incoming_message>"`

Return stdout to the user as the final reply.

## What this skill does
- Accept YouTube links
- Fetch transcript data
- Generate structured summary:
  - Video Title
  - 5 Key Points
  - Important Timestamps
  - Core Takeaway
- Answer follow-up questions from transcript only
- Support multilingual output (English default + Indian languages + requested language names)

## Supported commands in message text
- `/setlang <language>`
- `/summary`
- `/deepdive`
- `/actionpoints`

## Grounding rule
If answer is missing from transcript, output exactly:
`This topic is not covered in the video.`
