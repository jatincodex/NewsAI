import os
import logging
from app.core.celery_app import celery_app
from app.core.firebase_config import get_db_client
from app.services.gemini_service import GeminiFactChecker
from app.services.video_synthesis import VideoSynthesisEngine
from app.core.config import settings

logger = logging.getLogger(__name__)

@celery_app.task(name="app.tasks.process_social_post")
def process_social_post(post_id: str):
    """
    Celery task that executes Phase 1 verification workflow inside Firestore:
    1. Fetches post document from Firestore.
    2. Runs similarity checks against trusted documents.
    3. Evaluates Decision Gate and launches video synthesis if verified.
    """
    import asyncio
    logger.info(f"Starting verification task for post ID: {post_id}")
    db_client = get_db_client()
    try:
        post_ref = db_client.collection("posts").document(post_id)
        post_snap = post_ref.get()
        if not post_snap.exists:
            error_msg = f"Post with ID '{post_id}' not found in Firestore."
            logger.error(error_msg)
            return {"error": error_msg}
            
        post_data = post_snap.to_dict()
        post_ref.update({"status": "processing"})
        
        # Verification Layer using Gemini
        content = post_data.get("content", "")
        # Get trusted docs context
        trusted_snaps = db_client.collection("trusted_docs").get()
        trusted_ctx = "\n".join([snap.to_dict().get("content", "") for snap in trusted_snaps])
        
        # Run async Gemini call using asyncio.run
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(GeminiFactChecker.verify_claim(content, trusted_ctx))
        
        score = result.get("confidence_score", 0.0)
        verdict = result.get("verdict", "uncertain")
        
        updates = {
            "confidence_score": score,
            "verdict": verdict,
            "logic_breakdown": result.get("logic_breakdown", ""),
            "sources": result.get("sources", [])
        }
        
        # Decision Gate
        if score >= settings.CONFIDENCE_THRESHOLD and verdict == "verified":
            updates["status"] = "video_generation_pending"
            post_ref.update(updates)
            logger.info(f"Post {post_id} passed gate (score {score} >= {settings.CONFIDENCE_THRESHOLD}).")
            # Trigger video task
            generate_video_task.delay(post_id)
        else:
            updates["status"] = "human_review_required"
            post_ref.update(updates)
            logger.info(f"Post {post_id} flagged for human review (score {score} < {settings.CONFIDENCE_THRESHOLD}).")
            
        return {
            "post_id": post_id,
            "confidence_score": score,
            "status": updates["status"]
        }
    except Exception as e:
        logger.exception(f"Error occurred during verification task for post ID: {post_id}")
        try:
            db_client.collection("posts").document(post_id).update({"status": "failed"})
        except Exception:
            pass
        raise e

@celery_app.task(name="app.tasks.generate_video_task")
def generate_video_task(post_id: str):
    """
    Celery task that executes Phase 2 video generation workflow inside Firestore.
    """
    logger.info(f"Starting video generation task for post ID: {post_id}")
    db_client = get_db_client()
    try:
        post_ref = db_client.collection("posts").document(post_id)
        post_snap = post_ref.get()
        if not post_snap.exists:
            error_msg = f"Post with ID '{post_id}' not found in Firestore."
            logger.error(error_msg)
            return {"error": error_msg}
            
        post_data = post_snap.to_dict()
        post_ref.update({"status": "generating_video"})
        
        updates = {"status": "published"}
        
        # Setup file paths
        output_filename = f"video_{post_id}.mp4"
        output_path = settings.GENERATED_VIDEOS_DIR / output_filename
        
        image_filename = f"image_{post_id}.png"
        image_path = settings.GENERATED_IMAGES_DIR / image_filename
        
        # Ensure directories exist defensively
        settings.GENERATED_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        settings.GENERATED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        
        # Run static image card rendering
        VideoSynthesisEngine.generate_static_post_image(post_data.get("content", ""), str(image_path))
        
        # Run video rendering engine (if MoviePy is installed, otherwise fallback/skip gracefully)
        try:
            VideoSynthesisEngine.synthesize_reel(post_data.get("content", ""), str(output_path))
            updates["video_path"] = str(output_path)
        except Exception as video_err:
            logger.error(f"Failed to synthesize video reel for {post_id}: {video_err}")
            
        # Save results
        updates["image_path"] = str(image_path)

        post_ref.update(updates)
        logger.info(f"Publication completed for post {post_id}.")
        return {
            "post_id": post_id,
            "status": "published",
            "video_path": updates.get("video_path"),
            "image_path": updates.get("image_path")
        }
    except Exception as e:
        logger.exception(f"Error occurred during video generation task for post ID: {post_id}")
        try:
            db_client.collection("posts").document(post_id).update({"status": "failed"})
        except Exception:
            pass
        raise e
