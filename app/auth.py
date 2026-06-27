import hashlib
from typing import Optional

class AuthHandler:
    SALT = "news_ai_super_secure_salt_999"

    @classmethod
    def hash_password(cls, password: str) -> str:
        """Hashes the password with SHA-256 and a constant salt."""
        salted = password + cls.SALT
        return hashlib.sha256(salted.encode('utf-8')).hexdigest()

    @classmethod
    def verify_password(cls, plain_password: str, hashed_password: str) -> bool:
        """Verifies if the plain password matches the hashed password."""
        return cls.hash_password(plain_password) == hashed_password
        
    @classmethod
    def generate_token(cls, user_id: int, username: str) -> str:
        """Generates a simple, signed session token."""
        # Token format: user_id:username:signature
        payload = f"{user_id}:{username}"
        signature = hashlib.sha256((payload + cls.SALT).encode('utf-8')).hexdigest()[:16]
        return f"{payload}:{signature}"

    @classmethod
    def verify_token(cls, token: Optional[str]) -> Optional[int]:
        """
        Verifies a session token and returns the user_id if valid.
        Returns None if invalid or missing.
        """
        if not token:
            return None
        try:
            parts = token.split(":")
            if len(parts) != 3:
                return None
            user_id_str, username, signature = parts
            payload = f"{user_id_str}:{username}"
            expected_signature = hashlib.sha256((payload + cls.SALT).encode('utf-8')).hexdigest()[:16]
            if signature == expected_signature:
                return int(user_id_str)
        except Exception:
            pass
        return None
