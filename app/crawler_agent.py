import os
import time
import random
import logging
import threading
from datetime import datetime, timezone
from app.database import SessionLocal
from app.models import SocialPost, TrustedDocument
from app.gemini_service import GeminiFactChecker

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

class SocialMediaCrawlerAgent(threading.Thread):
    def __init__(self, check_interval_seconds: int = 15):
        super().__init__()
        self.check_interval = check_interval_seconds
        self.daemon = True
        self.running = False

    def start_agent(self):
        self.running = True
        self.start()
        logger.info("[SocialMediaCrawlerAgent] Background crawler thread started.")

    def stop_agent(self):
        self.running = False
        logger.info("[SocialMediaCrawlerAgent] Background crawler thread stopping.")

    def run(self):
        # Allow server to bind and start up
        time.sleep(5)
        
        while self.running:
            db = SessionLocal()
            try:
                # 1. Select a candidate
                candidate = random.choice(VIRAL_CANDIDATES)
                
                # 2. Check if already ingested
                existing = db.query(SocialPost).filter(SocialPost.post_id == candidate["post_id"]).first()
                if not existing:
                    msg = f"[SocialMediaCrawlerAgent] Discovered new viral post: {candidate['post_id']} by @{candidate['username']}"
                    logger.info(msg)
                    print(msg, flush=True)
                    
                    # 3. Pull trusted reference docs to construct prompt context
                    docs = db.query(TrustedDocument).all()
                    reference_context = ""
                    if docs:
                        reference_context = "\n".join([f"Document Title: {d.title}\nContent: {d.content}\n---" for d in docs])
                    
                    # 4. Invoke Gemini Fact Checking Agent
                    fact_check_result = GeminiFactChecker.verify_claim(candidate["content"], reference_context)
                    
                    # 5. Insert published verified post into DB
                    new_post = SocialPost(
                        post_id=candidate["post_id"],
                        source=candidate["source"],
                        username=candidate["username"],
                        content=candidate["content"],
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        likes=candidate["likes"],
                        retweets=candidate["retweets"],
                        confidence_score=fact_check_result["accuracy_percentage"] / 100.0,
                        accuracy_percentage=fact_check_result["accuracy_percentage"],
                        fact_check_report=fact_check_result["analysis_report"],
                        status="published"
                    )
                    db.add(new_post)
                    db.commit()
                    msg_success = f"[SocialMediaCrawlerAgent] Successfully fact checked and posted {candidate['post_id']}. Verdict: {fact_check_result['verdict']} ({fact_check_result['accuracy_percentage']}%)."
                    logger.info(msg_success)
                    print(msg_success, flush=True)
                    
            except Exception as e:
                logger.error(f"[SocialMediaCrawlerAgent] Error in background execution loop: {e}")
            finally:
                db.close()
                
            time.sleep(self.check_interval)

# Singleton Instance
crawler_agent_instance = SocialMediaCrawlerAgent()
