import os
import json
import logging
import sqlite3
from datetime import datetime, timezone
import firebase_admin
from firebase_admin import credentials, auth, firestore

logger = logging.getLogger(__name__)

# --- 1. MOCK FIRESTORE & FIREBASE AUTH IMPLEMENTATIONS (SQLite-backed) ---

class MockDocSnap:
    def __init__(self, db_path, collection, doc_id, data):
        self.id = doc_id
        self.exists = data is not None
        self._data = data
        self.reference = MockDocRef(db_path, collection, doc_id)

    def to_dict(self):
        return self._data

class MockDocRef:
    def __init__(self, db_path, collection, doc_id):
        self.db_path = db_path
        self.collection = collection
        self.id = doc_id

    def get(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT data FROM collections WHERE collection=? AND doc_id=?", (self.collection, self.id))
        row = c.fetchone()
        conn.close()
        if row:
            return MockDocSnap(self.db_path, self.collection, self.id, json.loads(row[0]))
        return MockDocSnap(self.db_path, self.collection, self.id, None)

    def set(self, data, merge=True):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        current = {}
        if merge:
            c.execute("SELECT data FROM collections WHERE collection=? AND doc_id=?", (self.collection, self.id))
            row = c.fetchone()
            if row:
                current = json.loads(row[0])
        
        current.update(data)
        serialized = json.dumps(current)
        
        c.execute(
            "INSERT OR REPLACE INTO collections (collection, doc_id, data) VALUES (?, ?, ?)",
            (self.collection, self.id, serialized)
        )
        conn.commit()
        conn.close()

    def update(self, data):
        self.set(data, merge=True)

    def delete(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT data FROM collections WHERE collection=? AND doc_id=?", (self.collection, self.id))
        row = c.fetchone()
        if row:
            doc_data = json.loads(row[0])
            # If deleting a post, we must also clear related comments
            if self.collection == "posts":
                post_int_id = doc_data.get("id")
                if post_int_id:
                    c.execute("DELETE FROM collections WHERE collection='comments' AND json_extract(data, '$.post_id')=?", (post_int_id,))
        c.execute("DELETE FROM collections WHERE collection=? AND doc_id=?", (self.collection, self.id))
        conn.commit()
        conn.close()

class MockQuery:
    def __init__(self, db_path, collection, filters=None, limit_val=None, order_by_field=None, order_by_dir="desc"):
        self.db_path = db_path
        self.collection = collection
        self.filters = filters or []
        self.limit_val = limit_val
        self.order_by_field = order_by_field
        self.order_by_dir = order_by_dir

    def where(self, field, op, value):
        new_filters = list(self.filters)
        new_filters.append((field, op, value))
        return MockQuery(self.db_path, self.collection, new_filters, self.limit_val, self.order_by_field, self.order_by_dir)

    def limit(self, n):
        return MockQuery(self.db_path, self.collection, self.filters, n, self.order_by_field, self.order_by_dir)

    def order_by(self, field, direction="desc"):
        return MockQuery(self.db_path, self.collection, self.filters, self.limit_val, field, direction)

    def get(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT doc_id, data FROM collections WHERE collection=?", (self.collection,))
        rows = c.fetchall()
        conn.close()

        results = []
        for doc_id, raw_data in rows:
            data = json.loads(raw_data)
            
            # Apply filters
            match = True
            for field, op, val in self.filters:
                item_val = data.get(field)
                if op == "==" and item_val != val:
                    match = False
                elif op == "!=" and item_val == val:
                    match = False
                elif op == "in" and item_val not in val:
                    match = False
            
            if match:
                results.append(MockDocSnap(self.db_path, self.collection, doc_id, data))

        # Apply ordering if specified
        if self.order_by_field:
            def sort_key(snap):
                val = snap.to_dict().get(self.order_by_field, "")
                return val
            results.sort(key=sort_key, reverse=(self.order_by_dir == "desc"))

        # Apply limit
        if self.limit_val:
            results = results[:self.limit_val]

        return results

    def stream(self):
        return self.get()

class MockCollectionRef(MockQuery):
    def __init__(self, db_path, name):
        super().__init__(db_path, name)

    def document(self, doc_id):
        return MockDocRef(self.db_path, self.collection, doc_id)

    def add(self, data):
        import uuid
        doc_id = f"doc_{uuid.uuid4().hex[:12]}"
        doc_ref = self.document(doc_id)
        doc_ref.set(data, merge=False)
        return doc_ref, doc_ref

class MockFirestoreClient:
    def __init__(self, db_path="mock_firestore.db"):
        self.db_path = db_path
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "CREATE TABLE IF NOT EXISTS collections ("
            "collection TEXT, doc_id TEXT, data TEXT, "
            "PRIMARY KEY(collection, doc_id))"
        )
        conn.commit()
        conn.close()

    def collection(self, name):
        return MockCollectionRef(self.db_path, name)


class MockFirebaseAuth:
    """Simulates Firebase Auth operations."""
    @staticmethod
    def verify_id_token(token: str) -> dict:
        # Mock token decoding. In mock mode, we expect JSON payload token
        try:
            return json.loads(token)
        except Exception:
            # Fallback for simple string tokens
            return {
                "uid": f"uid_{token}",
                "email": f"{token}@gmail.com",
                "name": token.capitalize(),
                "username": token
            }


# --- 2. FIREBASE SDK MAIN INITIALIZATION ---

_firebase_initialized = False
_db_client = None

def initialize_firebase():
    global _firebase_initialized, _db_client
    if _firebase_initialized:
        return _db_client

    cred_dict = None

    # Option A: Full JSON key as single env var (FIREBASE_CREDENTIALS_JSON)
    # Easiest — paste the entire service account JSON as one env var
    cred_json_str = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if cred_json_str:
        try:
            cred_dict = json.loads(cred_json_str)
            logger.info("Firebase: Using FIREBASE_CREDENTIALS_JSON env var.")
        except Exception as e:
            logger.error(f"Failed to parse FIREBASE_CREDENTIALS_JSON: {e}")

    # Option B: Individual env vars (FIREBASE_PROJECT_ID + CLIENT_EMAIL + PRIVATE_KEY)
    if not cred_dict:
        proj_id = os.getenv("FIREBASE_PROJECT_ID")
        client_email = os.getenv("FIREBASE_CLIENT_EMAIL")
        private_key = os.getenv("FIREBASE_PRIVATE_KEY")

        if proj_id and client_email and private_key:
            cred_dict = {
                "type": "service_account",
                "project_id": proj_id,
                "private_key": private_key.replace("\\n", "\n"),
                "client_email": client_email,
                "token_uri": "https://oauth2.googleapis.com/token",
            }
            logger.info("Firebase: Using individual FIREBASE_* env vars.")

    # Attempt real Firebase connection
    if cred_dict:
        try:
            logger.info(f"Connecting to Firebase Firestore project: {cred_dict.get('project_id')}")
            if not firebase_admin._apps:
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
            _db_client = firestore.client()
            _firebase_initialized = True
            logger.info("✅ Firebase Firestore connected — permanent cloud storage ACTIVE.")
            return _db_client
        except Exception as e:
            logger.exception(f"Firebase SDK init failed: {e}. Falling back to SQLite mock.")

    # Fallback: Local SQLite-backed mock Firestore
    logger.warning("⚠️  No Firebase credentials found. Using SQLite mock — data resets on restart!")
    logger.warning("   To use permanent storage, create a .env file with FIREBASE_CREDENTIALS_JSON")
    _db_client = MockFirestoreClient()
    _firebase_initialized = True
    return _db_client

def get_db_client():
    if not _firebase_initialized:
        initialize_firebase()
    return _db_client

def verify_token(token: str) -> dict:
    proj_id = os.getenv("FIREBASE_PROJECT_ID")
    if proj_id:
        try:
            return auth.verify_id_token(token)
        except Exception as e:
            logger.error(f"Firebase ID token verification failed: {e}")
            raise e
            
    # Bridge for locally generated signed session tokens
    from app.auth import AuthHandler
    verified_uid = AuthHandler.verify_token(token)
    if verified_uid:
        db = get_db_client()
        user_snap = db.collection("users").document(verified_uid).get()
        if user_snap.exists:
            user_data = user_snap.to_dict()
            return {
                "uid": verified_uid,
                "email": user_data.get("email"),
                "username": user_data.get("username"),
                "name": user_data.get("display_name")
            }
        return {
            "uid": verified_uid,
            "email": f"{verified_uid}@gmail.com",
            "username": verified_uid
        }

    return MockFirebaseAuth.verify_id_token(token)
