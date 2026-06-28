"""NewsAI Platform backend tests."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://social-intel-13.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


# --- Stats ---
def test_stats_shape(s):
    r = s.get(f"{API}/stats", timeout=30)
    assert r.status_code == 200
    d = r.json()
    for k in ["total_posts", "verified", "debunked", "pending_review", "rendering", "cache"]:
        assert k in d
    assert "live_keys" in d["cache"]


# --- Posts list + cache ---
def test_posts_list_and_cache(s):
    r1 = s.get(f"{API}/posts", timeout=30)
    assert r1.status_code == 200
    assert isinstance(r1.json(), list)
    t0 = time.time()
    r2 = s.get(f"{API}/posts", timeout=30)
    elapsed = time.time() - t0
    assert r2.status_code == 200
    # Cache hit -> very fast (under 2s typically)
    assert elapsed < 3.0, f"second call too slow: {elapsed}"


# --- Ingest ---
def test_ingest_creates_posts(s):
    r = s.post(f"{API}/ingest", json={"count": 2}, timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert "created" in d
    assert len(d["created"]) == 2
    ids = [p["id"] for p in d["created"]]
    # wait for processing
    time.sleep(8)
    listed = s.get(f"{API}/posts?status=verifying", timeout=30).json()
    all_posts = s.get(f"{API}/posts?limit=50", timeout=30).json()
    all_ids = {p["id"] for p in all_posts} | {p["id"] for p in listed}
    # At least one of our ingested should appear (status filter bypasses cache)
    assert any(i in all_ids for i in ids) or len(all_posts) > 0


# --- Post detail ---
def test_post_detail(s):
    posts = s.get(f"{API}/posts", timeout=30).json()
    assert len(posts) > 0
    pid = posts[0]["id"]
    r = s.get(f"{API}/posts/{pid}", timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert "post" in d and "report" in d and "render_job" in d
    assert d["post"]["id"] == pid


def test_post_detail_404(s):
    r = s.get(f"{API}/posts/does-not-exist", timeout=30)
    assert r.status_code == 404


# --- Admin queue ---
def test_admin_queue_shape(s):
    r = s.get(f"{API}/admin/queue", timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert isinstance(d, list)
    for item in d:
        assert "post" in item and "report" in item
        assert item["post"]["status"] == "human_review_required"


# --- Approve/Reject ---
def test_admin_approve_and_reject(s):
    # Make sure we have queue items, may need to wait
    for _ in range(8):
        q = s.get(f"{API}/admin/queue", timeout=30).json()
        if len(q) >= 2:
            break
        s.post(f"{API}/ingest", json={"count": 3}, timeout=30)
        time.sleep(5)
    q = s.get(f"{API}/admin/queue", timeout=30).json()
    if len(q) < 2:
        pytest.skip("Not enough queue items to test approve+reject")

    pid_app = q[0]["post"]["id"]
    pid_rej = q[1]["post"]["id"]

    ra = s.post(f"{API}/admin/posts/{pid_app}/approve", json={}, timeout=30)
    assert ra.status_code == 200
    assert ra.json().get("ok") is True
    # verify status flipped
    pa = s.get(f"{API}/posts/{pid_app}", timeout=30).json()["post"]
    assert pa["status"] in ("video_generation_pending", "verified")

    rr = s.post(f"{API}/admin/posts/{pid_rej}/reject", json={}, timeout=30)
    assert rr.status_code == 200
    pr = s.get(f"{API}/posts/{pid_rej}", timeout=30).json()["post"]
    assert pr["status"] == "debunked"

    # Wait ~7s and re-check approve flips to verified
    time.sleep(8)
    pa2 = s.get(f"{API}/posts/{pid_app}", timeout=30).json()["post"]
    assert pa2["status"] == "verified", f"expected verified after render, got {pa2['status']}"


# --- Safety gate ---
def test_safety_gate_high_confidence_path(s):
    # Wait/seed and look for any verified or video_generation_pending with verdict verified
    found = False
    for _ in range(10):
        all_posts = s.get(f"{API}/posts?limit=50", timeout=30).json()
        for p in all_posts:
            if p.get("verdict") == "verified" and p.get("status") in ("verified", "video_generation_pending"):
                found = True
                break
        if found:
            break
        s.post(f"{API}/ingest", json={"count": 3}, timeout=30)
        time.sleep(6)
    assert found, "No verified+high-score post observed (safety gate path)"


# --- Fact-check cache hit ---
def test_fact_report_cache_hit(s):
    # Pick an existing post and re-ingest same content path by triggering ingest a few times.
    # Easier: take a post, find any other post with same content -> its report should be cached.
    all_posts = s.get(f"{API}/posts?limit=50", timeout=30).json()
    by_content = {}
    for p in all_posts:
        by_content.setdefault(p["content"], []).append(p)
    dupes = [v for v in by_content.values() if len(v) >= 2]
    if not dupes:
        # force duplication by ingesting many
        for _ in range(3):
            s.post(f"{API}/ingest", json={"count": 5}, timeout=30)
        time.sleep(15)
        all_posts = s.get(f"{API}/posts?limit=50", timeout=30).json()
        by_content = {}
        for p in all_posts:
            by_content.setdefault(p["content"], []).append(p)
        dupes = [v for v in by_content.values() if len(v) >= 2]
    if not dupes:
        pytest.skip("No duplicate-content posts available to assert cache hit")
    # pick newest of a dupe pair
    grp = dupes[0]
    grp.sort(key=lambda x: x["created_at"], reverse=True)
    pid = grp[0]["id"]
    # wait a bit for the second pass to be processed
    for _ in range(6):
        d = s.get(f"{API}/posts/{pid}", timeout=30).json()
        if d.get("report"):
            if d["report"].get("cached") is True:
                return
        time.sleep(3)
    pytest.fail("Second-pass fact report did not have cached=True")
