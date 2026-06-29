"""
NewsAI Platform — Backend
Autonomous Social Media Verification & Reel Aggregator.

Architecture
------------
- FastAPI + Motor (async MongoDB)
- Async ingestion loop simulates public X / Instagram / TikTok JSON streams
- In-memory TTL cache (Redis stand-in) keyed by SHA256(post_content)
- Gemini 2.5 Flash fact-checking via emergentintegrations
- Programmatic safety gate (>=0.95 -> auto-render reel | <0.95 -> human review)
- Background "FFmpeg" render worker (simulated 9:16)
"""

from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
from pathlib import Path
from datetime import datetime, timezone
import os
import json
import time
import uuid
import random
import asyncio
import hashlib
import logging

# ----- env / db -----
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("newsai")

# ----- app -----
app = FastAPI(title="NewsAI Platform")
api_router = APIRouter(prefix="/api")


# Root-level health endpoints (k8s liveness/readiness probes hit "/")
@app.get("/")
async def root_health():
    return {"status": "ok", "service": "newsai", "time": utc_now_iso()}


@app.get("/health")
async def health():
    return {"status": "ok"}

# ============================================================
# In-memory TTL cache (Redis stand-in)
# ============================================================
class TTLCache:
    def __init__(self):
        self._store: Dict[str, tuple] = {}  # key -> (expires_at, value)
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            expires_at, value = entry
            if expires_at < time.time():
                self._store.pop(key, None)
                return None
            return value

    async def set(self, key: str, value: Any, ttl_seconds: int):
        async with self._lock:
            self._store[key] = (time.time() + ttl_seconds, value)

    async def stats(self) -> Dict[str, Any]:
        async with self._lock:
            now = time.time()
            live = [k for k, (exp, _) in self._store.items() if exp >= now]
            return {"total_keys": len(self._store), "live_keys": len(live)}


cache = TTLCache()
FEED_CACHE_TTL = 30           # /api/posts list cache
FACT_CACHE_TTL = 60 * 60 * 6  # 6h per-content fact-check cache
GEMINI_SEM = asyncio.Semaphore(2)  # avoid LLM concurrency rate limit


def content_hash(content: str) -> str:
    return hashlib.sha256(content.strip().lower().encode("utf-8")).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# Models
# ============================================================
class Post(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str
    platform: str  # x | instagram | tiktok
    raw_payload: Dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"  # pending | verifying | verified | debunked | human_review_required | video_generation_pending
    confidence_score: Optional[float] = None
    verdict: Optional[str] = None  # verified | debunked | uncertain
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class FactReport(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    post_id: str
    logic_breakdown: str
    confidence_score: float
    verdict: str
    sources: List[str] = Field(default_factory=list)
    cached: bool = False
    verified_at: str = Field(default_factory=utc_now_iso)


class RenderJob(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    post_id: str
    video_url: Optional[str] = None
    status: str = "queued"  # queued | rendering | completed | failed
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class IngestRequest(BaseModel):
    count: int = 1


# ============================================================
# Mock trusted context DB (used to seed the LLM)
# ============================================================
TRUSTED_CONTEXT = [
    "NASA confirmed the Artemis II crewed lunar flyby mission is scheduled for 2026.",
    "The WHO reports global flu vaccination coverage rose 3% in 2025 vs 2024.",
    "FIFA officially confirmed the 2026 World Cup will be hosted by USA, Canada, and Mexico.",
    "Apple's M5 chip was announced in late 2025 with 28% better single-core performance over M4.",
    "ECB held its main refinancing rate at 2.25% in the April 2026 meeting.",
    "SpaceX's Starship completed its 11th integrated test flight successfully in March 2026.",
]

MOCK_POSTS_POOL = [
    ("x", "BREAKING: NASA cancels Artemis II — astronauts refusing to fly."),
    ("instagram", "Artemis II lunar flyby still on track for 2026 per NASA briefing."),
    ("tiktok", "WHO says flu vaccine coverage DROPPED 30% globally last year #vaccines"),
    ("x", "FIFA moves 2026 World Cup to Saudi Arabia — leaked memo."),
    ("instagram", "Apple M5 chip benchmarks show 28% faster single-core vs M4."),
    ("tiktok", "ECB just slashed rates to 0% — emergency move overnight."),
    ("x", "SpaceX Starship test flight #11 lands cleanly, propellant transfer demo done."),
    ("instagram", "Eating raw garlic cures all viral infections, scientists confirm."),
    ("tiktok", "USA confirmed as 2026 World Cup co-host alongside Canada and Mexico."),
    ("x", "BREAKING: Artemis II crewed flyby of the Moon planned for 2026."),
]


# ============================================================
# Gemini fact-check (with cache)
# ============================================================
async def gemini_fact_check(content: str) -> Dict[str, Any]:
    """
    Returns a dict: { confidence_score, verdict, logic_breakdown, sources, cached }
    """
    key = f"fact:{content_hash(content)}"
    cached_val = await cache.get(key)
    if cached_val:
        cached_val = dict(cached_val)
        cached_val["cached"] = True
        return cached_val

    system_msg = (
        "You are NewsAI, an autonomous fact-checking analyst. "
        "Cross-reference the user's social media claim against the TRUSTED CONTEXT "
        "and return STRICT JSON ONLY with this exact schema:\n"
        '{"verdict": "verified" | "debunked" | "uncertain", '
        '"confidence_score": <float 0.00-1.00>, '
        '"logic_breakdown": "<2-4 sentence reasoning>", '
        '"sources": ["<source 1>", "<source 2>"]}\n'
        "Rules:\n"
        "- confidence_score must be a number between 0 and 1.\n"
        "- High confidence (>=0.95) only when a trusted source directly supports/refutes the claim.\n"
        "- No markdown fences. No extra commentary. JSON only."
    )

    trusted_ctx = "\n".join(f"- {s}" for s in TRUSTED_CONTEXT)
    prompt = (
        f"TRUSTED CONTEXT:\n{trusted_ctx}\n\n"
        f"SOCIAL MEDIA CLAIM:\n{content}\n\n"
        "Return JSON now."
    )

    result: Dict[str, Any]
    try:
        # Lazy import so server boots even if lib missing
        from emergentintegrations.llm.chat import LlmChat, UserMessage  # type: ignore

        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"newsai-{uuid.uuid4()}",
            system_message=system_msg,
        ).with_model("gemini", "gemini-2.5-flash")

        async with GEMINI_SEM:
            raw = await chat.send_message(UserMessage(text=prompt))
        text = raw if isinstance(raw, str) else str(raw)
        # strip code fences if any
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        parsed = json.loads(text)
        result = {
            "verdict": str(parsed.get("verdict", "uncertain")).lower(),
            "confidence_score": float(parsed.get("confidence_score", 0.0)),
            "logic_breakdown": str(parsed.get("logic_breakdown", "")),
            "sources": list(parsed.get("sources", []))[:5],
            "cached": False,
        }
    except Exception as e:
        logger.warning("Gemini fact-check failed, using heuristic fallback: %s", e)
        result = _heuristic_fact_check(content)

    # clamp
    result["confidence_score"] = max(0.0, min(1.0, float(result["confidence_score"])))
    await cache.set(key, {k: v for k, v in result.items() if k != "cached"}, FACT_CACHE_TTL)
    return result


def _heuristic_fact_check(content: str) -> Dict[str, Any]:
    """Deterministic fallback when LLM is unavailable."""
    c = content.lower()
    score = 0.5
    verdict = "uncertain"
    logic = "Heuristic fallback (LLM unreachable). Compared claim keywords against trusted context."
    sources = ["NewsAI internal heuristic"]
    for trusted in TRUSTED_CONTEXT:
        t = trusted.lower()
        # crude overlap
        common = set(c.split()) & set(t.split())
        if len(common) >= 4:
            score = 0.97
            verdict = "verified"
            logic = f"Claim shares substantial overlap with trusted record: '{trusted}'."
            sources = [trusted]
            break
    if "cancel" in c or "leaked" in c or "cure" in c or "0%" in c or "dropped 30%" in c:
        score = 0.15
        verdict = "debunked"
        logic = "Claim uses sensational framing that contradicts trusted-context records."
        sources = ["NewsAI internal heuristic"]
    return {
        "verdict": verdict,
        "confidence_score": score,
        "logic_breakdown": logic,
        "sources": sources,
        "cached": False,
    }


# ============================================================
# Pipeline: process a single post
# ============================================================
async def process_post(post_id: str):
    """Run fact-check, store report, apply safety gate, enqueue render if eligible."""
    await db.posts.update_one(
        {"id": post_id},
        {"$set": {"status": "verifying", "updated_at": utc_now_iso()}},
    )
    post = await db.posts.find_one({"id": post_id}, {"_id": 0})
    if not post:
        return

    result = await gemini_fact_check(post["content"])

    report = FactReport(
        post_id=post_id,
        logic_breakdown=result["logic_breakdown"],
        confidence_score=result["confidence_score"],
        verdict=result["verdict"],
        sources=result["sources"],
        cached=bool(result.get("cached")),
    )
    await db.fact_reports.insert_one(report.model_dump())

    # Programmatic safety gate
    score = result["confidence_score"]
    verdict = result["verdict"]

    if score >= 0.95 and verdict == "verified":
        new_status = "video_generation_pending"
        # enqueue render job
        job = RenderJob(post_id=post_id, status="queued")
        await db.render_jobs.insert_one(job.model_dump())
        asyncio.create_task(simulate_render(job.id))
    elif score >= 0.95 and verdict == "debunked":
        # High-confidence debunked: terminal, no render
        new_status = "debunked"
    else:
        new_status = "human_review_required"

    await db.posts.update_one(
        {"id": post_id},
        {
            "$set": {
                "status": new_status,
                "confidence_score": score,
                "verdict": verdict,
                "updated_at": utc_now_iso(),
            }
        },
    )
    # invalidate feed cache
    await cache.set("feed:list", None, 1)


# ============================================================
# Simulated FFmpeg 9:16 render worker
# ============================================================
async def simulate_render(job_id: str):
    await asyncio.sleep(random.uniform(1.5, 3.0))
    await db.render_jobs.update_one(
        {"id": job_id},
        {"$set": {"status": "rendering", "updated_at": utc_now_iso()}},
    )
    await asyncio.sleep(random.uniform(2.5, 5.0))
    fake_url = f"https://cdn.newsai.local/reels/{job_id}.mp4"
    await db.render_jobs.update_one(
        {"id": job_id},
        {
            "$set": {
                "status": "completed",
                "video_url": fake_url,
                "updated_at": utc_now_iso(),
            }
        },
    )
    job = await db.render_jobs.find_one({"id": job_id}, {"_id": 0})
    if job:
        # Promote post status to 'verified' (final state) since render done
        await db.posts.update_one(
            {"id": job["post_id"]},
            {"$set": {"status": "verified", "updated_at": utc_now_iso()}},
        )


# ============================================================
# Async ingestion loop (simulates public stream)
# ============================================================
ingestion_task: Optional[asyncio.Task] = None


async def _ingest_one() -> Post:
    platform, content = random.choice(MOCK_POSTS_POOL)
    raw_payload = {
        "source": platform,
        "ingested_at": utc_now_iso(),
        "engagement": {
            "likes": random.randint(120, 50000),
            "shares": random.randint(20, 9000),
            "comments": random.randint(5, 3000),
        },
        "author": f"@user_{random.randint(100, 9999)}",
        "post_id_external": str(uuid.uuid4()),
    }
    post = Post(content=content, platform=platform, raw_payload=raw_payload)
    await db.posts.insert_one(post.model_dump())
    asyncio.create_task(process_post(post.id))
    return post


async def ingestion_loop():
    logger.info("Ingestion loop started")
    try:
        while True:
            try:
                await _ingest_one()
            except Exception as e:
                logger.error("ingest error: %s", e)
            await asyncio.sleep(random.uniform(6.0, 12.0))
    except asyncio.CancelledError:
        logger.info("Ingestion loop cancelled")
        raise


# ============================================================
# API routes
# ============================================================
@api_router.get("/")
async def root():
    return {"service": "NewsAI", "status": "online", "time": utc_now_iso()}


@api_router.get("/stats")
async def stats():
    total = await db.posts.count_documents({})
    verified = await db.posts.count_documents({"status": "verified"})
    debunked = await db.posts.count_documents({"verdict": "debunked"})
    pending_review = await db.posts.count_documents({"status": "human_review_required"})
    rendering = await db.posts.count_documents({"status": "video_generation_pending"})
    cache_stats = await cache.stats()
    return {
        "total_posts": total,
        "verified": verified,
        "debunked": debunked,
        "pending_review": pending_review,
        "rendering": rendering,
        "cache": cache_stats,
    }


@api_router.get("/posts")
async def list_posts(status: Optional[str] = None, limit: int = 50):
    """Cached for 30s when no filter is applied (per spec)."""
    if not status:
        cached = await cache.get("feed:list")
        if cached:
            return cached
    query = {"status": status} if status else {}
    cursor = db.posts.find(query, {"_id": 0}).sort("created_at", -1).limit(limit)
    posts = await cursor.to_list(length=limit)
    if not status:
        await cache.set("feed:list", posts, FEED_CACHE_TTL)
    return posts


@api_router.get("/posts/enriched")
async def list_posts_enriched(statuses: str = "verified,debunked", limit: int = 50):
    """Bulk variant: returns posts with their latest fact_report + render_job in one call.
    Avoids frontend N+1 on the Verified screen."""
    status_list = [s.strip() for s in statuses.split(",") if s.strip()]
    query = {"status": {"$in": status_list}} if status_list else {}
    posts = await db.posts.find(query, {"_id": 0}).sort("updated_at", -1).limit(limit).to_list(length=limit)
    if not posts:
        return []
    ids = [p["id"] for p in posts]
    reports = await db.fact_reports.find({"post_id": {"$in": ids}}, {"_id": 0}).sort("verified_at", -1).to_list(length=2000)
    rep_map: Dict[str, Any] = {}
    for r in reports:
        rep_map.setdefault(r["post_id"], r)
    jobs = await db.render_jobs.find({"post_id": {"$in": ids}}, {"_id": 0}).sort("created_at", -1).to_list(length=2000)
    job_map: Dict[str, Any] = {}
    for j in jobs:
        job_map.setdefault(j["post_id"], j)
    return [
        {"post": p, "report": rep_map.get(p["id"]), "render_job": job_map.get(p["id"])}
        for p in posts
    ]


@api_router.get("/posts/{post_id}")
async def get_post(post_id: str):
    post = await db.posts.find_one({"id": post_id}, {"_id": 0})
    if not post:
        raise HTTPException(404, "post not found")
    report = await db.fact_reports.find_one(
        {"post_id": post_id}, {"_id": 0}, sort=[("verified_at", -1)]
    )
    render = await db.render_jobs.find_one(
        {"post_id": post_id}, {"_id": 0}, sort=[("created_at", -1)]
    )
    return {"post": post, "report": report, "render_job": render}


@api_router.get("/admin/queue")
async def admin_queue():
    cursor = db.posts.find(
        {"status": "human_review_required"}, {"_id": 0}
    ).sort("created_at", -1)
    posts = await cursor.to_list(length=200)
    if not posts:
        return []
    post_ids = [p["id"] for p in posts]
    reports = await db.fact_reports.find(
        {"post_id": {"$in": post_ids}}, {"_id": 0}
    ).sort("verified_at", -1).to_list(length=2000)
    # latest report per post_id (cursor is sorted desc by verified_at)
    rep_map: Dict[str, Any] = {}
    for r in reports:
        rep_map.setdefault(r["post_id"], r)
    return [{"post": p, "report": rep_map.get(p["id"])} for p in posts]


class ModerationDecision(BaseModel):
    note: Optional[str] = None


@api_router.post("/admin/posts/{post_id}/approve")
async def admin_approve(post_id: str, decision: ModerationDecision):
    post = await db.posts.find_one({"id": post_id}, {"_id": 0})
    if not post:
        raise HTTPException(404, "post not found")
    job = RenderJob(post_id=post_id, status="queued")
    await db.render_jobs.insert_one(job.model_dump())
    await db.posts.update_one(
        {"id": post_id},
        {
            "$set": {
                "status": "video_generation_pending",
                "verdict": "verified",
                "updated_at": utc_now_iso(),
            }
        },
    )
    asyncio.create_task(simulate_render(job.id))
    await cache.set("feed:list", None, 1)
    return {"ok": True, "render_job_id": job.id}


@api_router.post("/admin/posts/{post_id}/reject")
async def admin_reject(post_id: str, decision: ModerationDecision):
    post = await db.posts.find_one({"id": post_id}, {"_id": 0})
    if not post:
        raise HTTPException(404, "post not found")
    await db.posts.update_one(
        {"id": post_id},
        {
            "$set": {
                "status": "debunked",
                "verdict": "debunked",
                "updated_at": utc_now_iso(),
            }
        },
    )
    await cache.set("feed:list", None, 1)
    return {"ok": True}


@api_router.get("/render-jobs")
async def list_render_jobs(limit: int = 50):
    cursor = db.render_jobs.find({}, {"_id": 0}).sort("created_at", -1).limit(limit)
    return await cursor.to_list(length=limit)


@api_router.post("/ingest")
async def trigger_ingest(req: IngestRequest):
    """Manual ingest trigger for testing."""
    n = max(1, min(req.count, 20))
    created = []
    for _ in range(n):
        p = await _ingest_one()
        created.append(p.model_dump())
    return {"created": created}


# include router
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Lifecycle
# ============================================================
@app.on_event("startup")
async def on_startup():
    # indexes
    await db.posts.create_index("id", unique=True)
    await db.posts.create_index("status")
    await db.posts.create_index("created_at")
    await db.fact_reports.create_index("post_id")
    await db.render_jobs.create_index("post_id")

    # Auto-ingestion (continuous mock streams + initial seed) is OPT-IN.
    # In production this would otherwise hammer the LLM and grow the DB
    # unboundedly. Set NEWSAI_AUTO_INGEST=1 in /app/backend/.env to enable.
    auto_ingest = os.environ.get("NEWSAI_AUTO_INGEST", "0") == "1"
    if not auto_ingest:
        logger.info("NEWSAI_AUTO_INGEST disabled; skipping seed + ingestion loop")
        return

    # seed if empty
    if await db.posts.count_documents({}) == 0:
        logger.info("Seeding initial posts")
        for _ in range(6):
            await _ingest_one()
    global ingestion_task
    if ingestion_task is None or ingestion_task.done():
        ingestion_task = asyncio.create_task(ingestion_loop())


@app.on_event("shutdown")
async def on_shutdown():
    global ingestion_task
    if ingestion_task and not ingestion_task.done():
        ingestion_task.cancel()
        try:
            await ingestion_task
        except asyncio.CancelledError:
            pass
    client.close()
