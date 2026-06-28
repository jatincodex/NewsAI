import os
import redis
import hashlib
import json
import logging

logger = logging.getLogger(__name__)

# Load Redis configurations
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Setup connection (lazy init/defensive try-except)
_redis_client = None

def get_redis_client():
    global _redis_client
    if _redis_client is None:
        try:
            # Only connect if REDIS_URL or host is available, allow tests to skip
            _redis_client = redis.Redis.from_url(redis_url, socket_timeout=2, decode_responses=True)
            _redis_client.ping()
        except Exception as e:
            logger.warning(f"Could not connect to Redis. Caching is disabled. Error: {e}")
            _redis_client = False
    return _redis_client if _redis_client is not False else None

def get_cached_fact_check(claim_content: str) -> dict | None:
    client = get_redis_client()
    if not client:
        return None
    try:
        # Create SHA256 hash of the claim
        claim_hash = hashlib.sha256(claim_content.strip().encode("utf-8")).hexdigest()
        key = f"factcheck:{claim_hash}"
        data = client.get(key)
        if data:
            logger.info(f"[Cache] Hit for fact check: {key}")
            return json.loads(data)
    except Exception as e:
        logger.error(f"[Cache] Error reading fact check cache: {e}")
    return None

def set_cached_fact_check(claim_content: str, result: dict, expire_seconds: int = 86400):
    client = get_redis_client()
    if not client:
        return
    try:
        claim_hash = hashlib.sha256(claim_content.strip().encode("utf-8")).hexdigest()
        key = f"factcheck:{claim_hash}"
        client.setex(key, expire_seconds, json.dumps(result))
        logger.info(f"[Cache] Saved fact check cache: {key}")
    except Exception as e:
        logger.error(f"[Cache] Error writing fact check cache: {e}")

def get_cached_posts() -> list | None:
    client = get_redis_client()
    if not client:
        return None
    try:
        data = client.get("api:posts")
        if data:
            logger.info("[Cache] Hit for /posts feed")
            return json.loads(data)
    except Exception as e:
        logger.error(f"[Cache] Error reading posts cache: {e}")
    return None

def set_cached_posts(posts: list, expire_seconds: int = 30):
    client = get_redis_client()
    if not client:
        return
    try:
        client.setex("api:posts", expire_seconds, json.dumps(posts))
        logger.info("[Cache] Saved /posts cache for 30s")
    except Exception as e:
        logger.error(f"[Cache] Error writing posts cache: {e}")

def invalidate_posts_cache():
    client = get_redis_client()
    if not client:
        return
    try:
        client.delete("api:posts")
        logger.info("[Cache] Invalidated /posts cache")
    except Exception as e:
        logger.error(f"[Cache] Error invalidating posts cache: {e}")
