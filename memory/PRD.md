# NewsAI Platform — PRD

## What it is
NewsAI is an autonomous social-media verification & reel-aggregator dashboard built as an Expo (React Native) mobile app + FastAPI/MongoDB backend.

## Core flow
1. **Ingestion loop** (`asyncio`) continuously mock-streams posts from X / Instagram / TikTok into MongoDB.
2. Each post is fed to a **Gemini 2.5 Flash** fact-checker (`emergentintegrations`, Universal LLM key).
3. **Hash-keyed TTL cache** (Redis stand-in) skips Gemini if `sha256(content)` was checked recently. Public `/api/posts` list is cached for 30 s.
4. **Safety gate**: `confidence_score >= 0.95` AND `verdict == "verified"` → status `video_generation_pending` + simulated FFmpeg 9:16 render job; otherwise → `human_review_required` (Admin Queue).
5. **Render worker** (`asyncio.create_task`) transitions render_jobs `queued → rendering → completed` and finalises the post status to `verified`.

## API surface (`/api`)
- `GET /stats` — totals + cache stats
- `GET /posts?status=` — list (30 s cache when unfiltered)
- `GET /posts/{id}` — post + latest fact_report + latest render_job
- `GET /admin/queue` — human_review_required posts (enriched with reports)
- `POST /admin/posts/{id}/approve|reject` — moderation
- `GET /render-jobs`
- `POST /ingest` — manual ingest trigger (count 1–20)

## MongoDB collections
- `posts` (id, content, platform, raw_payload, status, confidence_score, verdict, created_at, updated_at)
- `fact_reports` (id, post_id, logic_breakdown, confidence_score, verdict, sources, cached, verified_at)
- `render_jobs` (id, post_id, video_url, status, created_at, updated_at)

## Frontend
Bottom tabs: **Feed / Verified / Admin** + post detail screen.
- Brutalist Mobile LIGHT design (0 radius, 2pt borders, mono stats).
- Confidence bar coloured red <0.5 / amber 0.5–0.95 / green ≥0.95.
- Raw payload inspector in mono on dark for Admin cards.
- Render-job progress tracker (queued → rendering → completed) on detail.
