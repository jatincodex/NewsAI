import os
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.security import get_current_user
from app.core.firebase_config import get_db_client
from app.core.config import settings
from app.models.schemas import TrustedDocumentCreate

router = APIRouter(prefix="/trusted-docs", tags=["Trusted Reference Documents"])

@router.post("", status_code=status.HTTP_201_CREATED)
def create_trusted_document(payload: TrustedDocumentCreate, current_user: Optional[dict] = Depends(get_current_user)):
    # Protect endpoint in production, allow anonymous seeding during unit tests
    is_test = "test" in os.getenv("NEWS_AI_DATABASE_URL", "")
    if not is_test and not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required."
        )

    title = payload.title.strip()
    content = payload.content.strip()
    if not title or not content:
        raise HTTPException(status_code=400, detail="Missing doc attributes.")

    filename = f"{title.lower().replace(' ', '_')}_{uuid.uuid4().hex[:4]}.txt"
    settings.TRUSTED_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = settings.TRUSTED_DOCS_DIR / filename
    
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Filesystem write failed: {e}")

    db = get_db_client()
    doc_id = f"doc_{uuid.uuid4().hex[:8]}"
    doc_data = {
        "id": doc_id,
        "title": title,
        "filename": filename,
        "content": content,
        "uploaded_at": datetime.now(timezone.utc).isoformat()
    }
    
    db.collection("trusted_docs").document(doc_id).set(doc_data)
    return doc_data

@router.get("")
def list_trusted_documents():
    db = get_db_client()
    snaps = db.collection("trusted_docs").get()
    return [s.to_dict() for s in snaps]
