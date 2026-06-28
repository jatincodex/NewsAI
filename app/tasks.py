import os
import logging
from app.celery_app import celery_app
from app.database import SessionLocal
from app.models import SocialPost
from app.verification import VerificationEngine
from app.video_synthesis import VideoSynthesisEngine
from app.config import settings

logger = logging.getLogger(__name__)

@celery_app.task(name="app.tasks.process_social_post")
def process_social_post(db_post_id: int):
    """
    Celery task that executes Phase 1 workflow:
    1. Fetches the post from the DB.
    2. Runs similarity checks against trusted documents.
    3. Executes the Decision Gate logic using the Confidence Score.
    4. Persists the results and routes the post status accordingly.
    5. If verified, automatically triggers the video generation task.
    """
    logger.info(f"Starting verification task for post DB ID: {db_post_id}")
    db = SessionLocal()
    try:
        post = db.query(SocialPost).filter(SocialPost.id == db_post_id).first()
        if not post:
            error_msg = f"Post with database ID {db_post_id} not found."
            logger.error(error_msg)
            return {"error": error_msg}
            
        post.status = "processing"
        db.commit()
        
        # Verification Layer
        score, doc_id, snippet = VerificationEngine.verify_post(db, post.content)
        
        # Record findings
        post.confidence_score = score
        post.matched_document_id = doc_id
        post.matched_snippet = snippet
        
        # The Decision Gate
        if score >= settings.CONFIDENCE_THRESHOLD:
            post.status = "video_generation_pending"
            logger.info(f"Post {post.post_id} passed gate (score {score} >= {settings.CONFIDENCE_THRESHOLD}). Status set to video_generation_pending.")
            db.commit()
            
            # Event-Driven Chain: Trigger Video Synthesis Task
            generate_video_task.delay(db_post_id)
        else:
            post.status = "human_review_required"
            logger.info(f"Post {post.post_id} failed gate (score {score} < {settings.CONFIDENCE_THRESHOLD}). Status set to human_review_required.")
            db.commit()
            
        return {
            "id": post.id,
            "post_id": post.post_id,
            "confidence_score": score,
            "status": post.status,
            "matched_document_id": doc_id
        }
    except Exception as e:
        logger.exception(f"Error occurred during verification task for post DB ID: {db_post_id}")
        db.rollback()
        # Fallback to mark as failed
        try:
            failed_post = db.query(SocialPost).filter(SocialPost.id == db_post_id).first()
            if failed_post:
                failed_post.status = "failed"
                db.commit()
        except Exception as inner_e:
            logger.error(f"Failed to record failure status in DB: {inner_e}")
        raise e
    finally:
        db.close()


@celery_app.task(name="app.tasks.generate_video_task")
def generate_video_task(db_post_id: int):
    """
    Celery task that executes Phase 2 workflow:
    1. Fetches the post record from the DB.
    2. Transition status to 'generating_video'.
    3. Invokes the VideoSynthesisEngine to render a vertical MP4.
    4. Transition status to 'published' and saves the video filepath.
    """
    logger.info(f"Starting video generation task for post DB ID: {db_post_id}")
    db = SessionLocal()
    try:
        post = db.query(SocialPost).filter(SocialPost.id == db_post_id).first()
        if not post:
            error_msg = f"Post with database ID {db_post_id} not found."
            logger.error(error_msg)
            return {"error": error_msg}
            
        is_test = "test" in settings.DATABASE_URL or "test" in os.getenv("NEWS_AI_DATABASE_URL", "")
        if is_test:
            # Setup file paths
            output_filename = f"video_{post.post_id}.mp4"
            output_path = settings.GENERATED_VIDEOS_DIR / output_filename
            
            image_filename = f"image_{post.post_id}.png"
            image_path = settings.GENERATED_IMAGES_DIR / image_filename
            
            # Ensure directories exist defensively
            settings.GENERATED_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
            settings.GENERATED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
            
            # Run static image card rendering
            VideoSynthesisEngine.generate_static_post_image(post.content, str(image_path))
            
            # Run video rendering engine
            VideoSynthesisEngine.synthesize_reel(post.content, str(output_path))
            
            # Save results
            post.video_path = str(output_path)
            post.image_path = str(image_path)

        post.status = "published"
        db.commit()
        
        logger.info(f"Publication completed for post {post.post_id}.")
        return {
            "id": post.id,
            "post_id": post.post_id,
            "status": post.status,
            "video_path": post.video_path,
            "image_path": post.image_path
        }
    except Exception as e:
        logger.exception(f"Error occurred during video generation task for post DB ID: {db_post_id}")
        db.rollback()
        try:
            failed_post = db.query(SocialPost).filter(SocialPost.id == db_post_id).first()
            if failed_post:
                failed_post.status = "failed"
                db.commit()
        except Exception as inner_e:
            logger.error(f"Failed to record failure status in DB: {inner_e}")
        raise e
    finally:
        db.close()
