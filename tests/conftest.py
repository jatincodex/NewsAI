import pytest
import sqlite3
from app.firebase_config import get_db_client

@pytest.fixture(autouse=True)
def flush_firestore_collections():
    """Autouse fixture to flush all Mock Firestore collections between test runs."""
    db = get_db_client()
    if hasattr(db, "db_path"):
        # Local SQLite-backed Mock Firestore
        conn = sqlite3.connect(db.db_path)
        c = conn.cursor()
        c.execute("DELETE FROM collections")
        conn.commit()
        conn.close()
    else:
        # Real Cloud Firestore (if environment credentials are set)
        for col in ["users", "posts", "comments", "saves", "follows", "messages", "trusted_docs"]:
            for doc in db.collection(col).stream():
                doc.reference.delete()
    yield
