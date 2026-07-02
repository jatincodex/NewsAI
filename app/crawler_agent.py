import uuid
import asyncio
import random
import logging
from datetime import datetime, timezone
from app.services.gemini_service import GeminiFactChecker
from app.core.cache import invalidate_posts_cache
from app.core.firebase_config import get_db_client

logger = logging.getLogger(__name__)

VIRAL_CANDIDATES = [
    {
        "post_id": "viral_x_101",
        "source": "X",
        "username": "science_insider",
        "content": "Alert: NASA Kepler telescope discovered a new Earth-sized planet orbiting in the habitable zone of a distant star. It might contain liquid water!",
        "likes": 12500,
        "retweets": 4300
    },
    {
        "post_id": "viral_fb_202",
        "source": "Facebook",
        "username": "health_watch",
        "content": "Medical alert: Drinking celery juice every morning completely cures type-2 diabetes in two weeks according to a viral healthcare study.",
        "likes": 8400,
        "retweets": 0
    },
    {
        "post_id": "viral_insta_303",
        "source": "Instagram",
        "username": "space_weather",
        "content": "Emergency! A massive solar storm is heading towards Earth, expected to cause a global internet blackout tomorrow that will last for 3 months.",
        "likes": 45000,
        "retweets": 0
    },
    {
        "post_id": "viral_x_404",
        "source": "X",
        "username": "future_tech",
        "content": "Breaking: OpenAI releases GPT-6 model that passes the Bar Exam with a perfect score and gets hired by a major law firm as a legal counsel.",
        "likes": 32000,
        "retweets": 9800
    },
    {
        "post_id": "viral_fb_505",
        "source": "Facebook",
        "username": "work_life",
        "content": "Breaking news: Congress just passed a new federal labor bill establishing a mandatory three-day weekend (Friday-Sunday) starting next month.",
        "likes": 65000,
        "retweets": 0
    }
]

# Track crawler cancellation / status
crawler_running = False


async def run_crawler_task(check_interval_seconds: int = 15):
    """Async task loop that simulates discovering viral social media posts
    and fact-checks them via Gemini, storing results in Firestore."""
    global crawler_running
    crawler_running = True
    logger.info("[SocialMediaCrawlerAgent] Async crawler loop started.")
    print("[SocialMediaCrawlerAgent] Async crawler loop started.", flush=True)

    # Allow application server to bind first
    await asyncio.sleep(5)

    while crawler_running:
        try:
            db = get_db_client()

            # 1. Choose a random candidate
            candidate = random.choice(VIRAL_CANDIDATES)

            # 2. Check if already ingested (Firestore document lookup)
            existing_snap = db.collection("posts").document(candidate["post_id"]).get()
            if not existing_snap.exists:
                msg_discover = (
                    f"[SocialMediaCrawlerAgent] Discovered new viral post: "
                    f"{candidate['post_id']} by @{candidate['username']}"
                )
                logger.info(msg_discover)
                print(msg_discover, flush=True)

                # 3. Pull reference docs to construct context
                doc_snaps = db.collection("trusted_docs").get()
                reference_context = ""
                if doc_snaps:
                    reference_context = "\n".join([
                        f"Document Title: {d.to_dict().get('title', '')}\n"
                        f"Content: {d.to_dict().get('content', '')}\n---"
                        for d in doc_snaps
                    ])

                # 4. Invoke Gemini fact-checker asynchronously
                fact_check_result = await GeminiFactChecker.verify_claim(
                    candidate["content"], reference_context
                )

                accuracy = fact_check_result["accuracy_percentage"]
                confidence_score = accuracy / 100.0

                # Determine status based on confidence score
                if confidence_score >= 0.75:
                    post_status = "published"
                elif confidence_score <= 0.30:
                    post_status = "rejected"
                else:
                    post_status = "human_review_required"

                # 5. Insert post into Firestore
                now = datetime.now(timezone.utc).isoformat()
                post_doc = {
                    "id": candidate["post_id"],
                    "post_id": candidate["post_id"],
                    "source": candidate["source"],
                    "username": candidate["username"],
                    "content": candidate["content"],
                    "timestamp": candidate.get("timestamp", now),
                    "likes": candidate["likes"],
                    "retweets": candidate["retweets"],
                    "confidence_score": confidence_score,
                    "accuracy_percentage": accuracy,
                    "fact_check_report": fact_check_result["analysis_report"],
                    "status": post_status,
                    "image_path": None,
                    "video_path": None,
                    "likes_count": 0,
                    "created_at": now,
                    "user_id": None,
                }
                db.collection("posts").document(candidate["post_id"]).set(post_doc)

                # Invalidate posts cache so new items appear immediately
                invalidate_posts_cache()

                msg_success = (
                    f"[SocialMediaCrawlerAgent] Successfully fact checked and posted "
                    f"{candidate['post_id']}. Verdict: {fact_check_result['verdict']} "
                    f"({accuracy}%)."
                )
                logger.info(msg_success)
                print(msg_success, flush=True)

        except asyncio.CancelledError:
            logger.info("[SocialMediaCrawlerAgent] Async crawler loop task cancelled.")
            break
        except Exception as e:
            logger.error(f"[SocialMediaCrawlerAgent] Error in async execution loop: {e}")

        await asyncio.sleep(check_interval_seconds)


def stop_crawler():
    global crawler_running
    crawler_running = False
    logger.info("[SocialMediaCrawlerAgent] Async crawler task loop stopping flag set.")
