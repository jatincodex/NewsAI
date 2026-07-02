import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.security import require_user
from app.core.firebase_config import get_db_client
from app.models.schemas import MessageCreate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Messaging"])

# --- E2EE KEY MANAGEMENT ---

@router.post("/keys/publish")
def publish_public_key(payload: dict, user: dict = Depends(require_user)):
    """Store the user's RSA public key (JWK format) on the server."""
    public_key_jwk = payload.get("public_key_jwk")
    if not public_key_jwk:
        raise HTTPException(status_code=400, detail="Missing public_key_jwk field.")
    db = get_db_client()
    db.collection("users").document(user["id"]).update({"public_key_jwk": public_key_jwk})
    return {"status": "ok"}

@router.get("/keys/{username}")
def get_public_key(username: str):
    """Fetch a user's RSA public key by username."""
    db = get_db_client()
    snaps = db.collection("users").where("username", "==", username).get()
    if not snaps:
        raise HTTPException(status_code=404, detail="User not found.")
    user_data = snaps[0].to_dict()
    key = user_data.get("public_key_jwk")
    if not key:
        raise HTTPException(status_code=404, detail="User has not published a public key yet.")
    return {"username": username, "public_key_jwk": key}


# --- DIRECT MESSAGING (DMs) — E2EE UPGRADED ---

@router.get("/messages")
def get_messages(with_user: str, user: dict = Depends(require_user)):
    db = get_db_client()
    snaps = db.collection("users").where("username", "==", with_user).get()
    if not snaps:
        raise HTTPException(status_code=404, detail="Target user not found.")
    other_user = snaps[0].to_dict()

    # O(N) database check query fix: query only current user's sent or received messages
    sent_msgs = db.collection("messages").where("sender_id", "==", user["id"]).get()
    recv_msgs = db.collection("messages").where("recipient_id", "==", user["id"]).get()
    
    combined = []
    seen_ids = set()
    for m in (sent_msgs + recv_msgs):
        if m.id in seen_ids:
            continue
        seen_ids.add(m.id)
        data = m.to_dict()
        s_id = data.get("sender_id")
        r_id = data.get("recipient_id")
        
        # Filter for messages strictly between the two users
        if (s_id == user["id"] and r_id == other_user["id"]) or \
           (s_id == other_user["id"] and r_id == user["id"]):
            combined.append({
                "id": data["id"],
                "sender_id": s_id,
                "recipient_id": r_id,
                "encrypted_text": data.get("encrypted_text"),
                "encrypted_key_for_sender": data.get("encrypted_key_for_sender"),
                "encrypted_key_for_recipient": data.get("encrypted_key_for_recipient"),
                "text": data.get("text", ""),
                "is_encrypted": data.get("is_encrypted", False),
                "sender_username": user["username"] if s_id == user["id"] else other_user["username"],
                "recipient_username": other_user["username"] if s_id == user["id"] else user["username"],
                "created_at": data.get("created_at")
            })

    combined.sort(key=lambda x: x.get("created_at", ""))
    return combined

@router.post("/messages")
def send_message(payload: MessageCreate, user: dict = Depends(require_user)):
    recipient_username = payload.recipient_username.strip()

    db = get_db_client()
    snaps = db.collection("users").where("username", "==", recipient_username).get()
    if not snaps:
        raise HTTPException(status_code=404, detail="Recipient user not found.")
    recipient = snaps[0].to_dict()

    msg_id = f"msg_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    msg_data = {
        "id": msg_id,
        "sender_id": user["id"],
        "recipient_id": recipient["id"],
        "created_at": now,
    }

    # E2EE path — store only ciphertext
    if payload.encrypted_text:
        msg_data.update({
            "encrypted_text": payload.encrypted_text,
            "encrypted_key_for_sender": payload.encrypted_key_for_sender,
            "encrypted_key_for_recipient": payload.encrypted_key_for_recipient,
            "text": "",
            "is_encrypted": True,
        })
    else:
        # Legacy plaintext fallback
        msg_data.update({"text": payload.text or "", "is_encrypted": False})

    db.collection("messages").document(msg_id).set(msg_data)
    return {**msg_data, "sender_username": user["username"], "recipient_username": recipient["username"]}


# --- GROUP CHATS — E2EE ---

@router.post("/groups", status_code=201)
def create_group(payload: dict, user: dict = Depends(require_user)):
    """Create a new encrypted group chat."""
    name = payload.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Group name is required.")
    member_usernames = payload.get("members", [])  # list of usernames to invite

    db = get_db_client()
    group_id = f"grp_{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc).isoformat()

    # Resolve member user IDs
    member_ids = [user["id"]]  # creator is always first member
    for uname in member_usernames:
        uname = uname.strip()
        if not uname or uname == user["username"]:
            continue
        snaps = db.collection("users").where("username", "==", uname).get()
        if snaps:
            uid = snaps[0].to_dict()["id"]
            if uid not in member_ids:
                member_ids.append(uid)

    if len(member_ids) > 50:
        raise HTTPException(status_code=400, detail="Groups are limited to 50 members.")

    group_data = {
        "id": group_id,
        "name": name,
        "creator_id": user["id"],
        "member_ids": member_ids,
        "created_at": now,
    }
    db.collection("groups").document(group_id).set(group_data)
    return group_data

@router.get("/groups")
def list_groups(user: dict = Depends(require_user)):
    """List all groups the current user is a member of."""
    db = get_db_client()
    all_groups = db.collection("groups").get()
    result = []
    for g in all_groups:
        data = g.to_dict()
        if user["id"] in data.get("member_ids", []):
            result.append(data)
    result.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return result

@router.get("/groups/{group_id}")
def get_group(group_id: str, user: dict = Depends(require_user)):
    """Get group details including all member public keys for E2EE."""
    db = get_db_client()
    snap = db.collection("groups").document(group_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Group not found.")
    group_data = snap.to_dict()
    if user["id"] not in group_data.get("member_ids", []):
        raise HTTPException(status_code=403, detail="You are not a member of this group.")

    # Fetch all member profiles + public keys
    members = []
    for uid in group_data.get("member_ids", []):
        u_snap = db.collection("users").document(uid).get()
        if u_snap.exists:
            u = u_snap.to_dict()
            members.append({
                "id": u["id"],
                "username": u["username"],
                "display_name": u.get("display_name"),
                "avatar_index": u.get("avatar_index", 1),
                "public_key_jwk": u.get("public_key_jwk"),
            })
    return {**group_data, "members": members}

@router.post("/groups/{group_id}/members")
def add_group_member(group_id: str, payload: dict, user: dict = Depends(require_user)):
    """Add a new member to a group."""
    db = get_db_client()
    snap = db.collection("groups").document(group_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Group not found.")
    group_data = snap.to_dict()
    if group_data["creator_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Only the group creator can add members.")

    username = payload.get("username", "").strip()
    u_snaps = db.collection("users").where("username", "==", username).get()
    if not u_snaps:
        raise HTTPException(status_code=404, detail="User not found.")
    new_uid = u_snaps[0].to_dict()["id"]

    member_ids = group_data.get("member_ids", [])
    if new_uid in member_ids:
        return {"status": "already_member"}
    if len(member_ids) >= 50:
        raise HTTPException(status_code=400, detail="Group is full (max 50 members).")

    member_ids.append(new_uid)
    db.collection("groups").document(group_id).update({"member_ids": member_ids})
    return {"status": "added", "member_ids": member_ids}

@router.post("/groups/{group_id}/messages")
def send_group_message(group_id: str, payload: dict, user: dict = Depends(require_user)):
    """Send an E2EE message to a group."""
    db = get_db_client()
    snap = db.collection("groups").document(group_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Group not found.")
    group_data = snap.to_dict()
    if user["id"] not in group_data.get("member_ids", []):
        raise HTTPException(status_code=403, detail="You are not a member of this group.")

    msg_id = f"gmsg_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    # encrypted_keys is a dict: { user_id: encrypted_aes_key_for_that_user }
    msg_data = {
        "id": msg_id,
        "group_id": group_id,
        "sender_id": user["id"],
        "sender_username": user["username"],
        "encrypted_text": payload.get("encrypted_text", ""),
        "encrypted_keys": payload.get("encrypted_keys", {}),  # {uid: encrypted_key}
        "is_encrypted": True,
        "created_at": now,
    }
    db.collection("group_messages").document(msg_id).set(msg_data)
    return msg_data

@router.get("/groups/{group_id}/messages")
def get_group_messages(group_id: str, user: dict = Depends(require_user)):
    """Fetch all E2EE messages for a group."""
    db = get_db_client()
    snap = db.collection("groups").document(group_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Group not found.")
    group_data = snap.to_dict()
    if user["id"] not in group_data.get("member_ids", []):
        raise HTTPException(status_code=403, detail="You are not a member of this group.")

    # O(N) database query fix: filter by group_id at the DB layer
    all_msgs = db.collection("group_messages").where("group_id", "==", group_id).get()
    result = []
    for m in all_msgs:
        result.append(m.to_dict())

    result.sort(key=lambda x: x.get("created_at", ""))
    return result
