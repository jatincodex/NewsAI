import math
import string
import re
from typing import Dict, List, Tuple, Optional
from sqlalchemy.orm import Session
from app.models import TrustedDocument

class VerificationEngine:
    @staticmethod
    def _clean_and_tokenize(text: str) -> List[str]:
        """Cleans text by removing punctuation and lowercasing, returning a list of tokens."""
        text = text.lower()
        # Remove punctuation
        text = text.translate(str.maketrans("", "", string.punctuation))
        # Split on whitespace
        return [word for word in text.split() if len(word) > 1]

    @staticmethod
    def _calculate_cosine_similarity(text_a: str, text_b: str) -> float:
        """Calculates the mathematical cosine similarity between two text snippets."""
        tokens_a = VerificationEngine._clean_and_tokenize(text_a)
        tokens_b = VerificationEngine._clean_and_tokenize(text_b)
        
        if not tokens_a or not tokens_b:
            return 0.0
            
        # Build frequency dictionaries
        freq_a: Dict[str, int] = {}
        for token in tokens_a:
            freq_a[token] = freq_a.get(token, 0) + 1
            
        freq_b: Dict[str, int] = {}
        for token in tokens_b:
            freq_b[token] = freq_b.get(token, 0) + 1
            
        # Get unique tokens
        unique_tokens = set(freq_a.keys()).union(set(freq_b.keys()))
        
        dot_product = 0.0
        sum_sq_a = 0.0
        sum_sq_b = 0.0
        
        for token in unique_tokens:
            val_a = freq_a.get(token, 0)
            val_b = freq_b.get(token, 0)
            dot_product += val_a * val_b
            sum_sq_a += val_a ** 2
            sum_sq_b += val_b ** 2
            
        magnitude = math.sqrt(sum_sq_a) * math.sqrt(sum_sq_b)
        if magnitude == 0:
            return 0.0
            
        return dot_product / magnitude

    @staticmethod
    def _chunk_document(content: str, max_chunk_size: int = 200) -> List[str]:
        """Chunks a document into sentences to simulate a RAG document chunking strategy."""
        # Simple sentence splitter
        sentences = re.split(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?)\s', content)
        chunks = []
        current_chunk = []
        current_len = 0
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            words = sentence.split()
            if current_len + len(words) > max_chunk_size:
                chunks.append(" ".join(current_chunk))
                current_chunk = [sentence]
                current_len = len(words)
            else:
                current_chunk.append(sentence)
                current_len += len(words)
                
        if current_chunk:
            chunks.append(" ".join(current_chunk))
            
        return chunks

    @classmethod
    def verify_post(cls, db, post_content: str) -> Tuple[float, Optional[str], Optional[str]]:
        """
        Cross-references the post content against all trusted news documents in the database.
        Returns a tuple: (highest_confidence_score, matched_document_id, matched_snippet)
        """
        if hasattr(db, "query"):
            # SQLAlchemy Session
            trusted_docs = db.query(TrustedDocument).all()
            docs = [{"id": str(doc.id), "content": doc.content} for doc in trusted_docs]
        else:
            # Firestore Client
            snaps = db.collection("trusted_docs").get()
            docs = [{"id": snap.id, "content": snap.to_dict().get("content", "")} for snap in snaps]

        if not docs:
            return 0.0, None, "No trusted documents in the database to verify against."
            
        best_score = 0.0
        best_doc_id = None
        best_snippet = None
        
        for doc in docs:
            # Chunk the document to match locally against specific snippets (simulating vector retrieval)
            chunks = cls._chunk_document(doc["content"])
            
            # Also include the document as a whole
            chunks.append(doc["content"])
            
            for chunk in chunks:
                score = cls._calculate_cosine_similarity(post_content, chunk)
                if score > best_score:
                    best_score = score
                    best_doc_id = doc["id"]
                    # Keep a snippet of up to 150 characters
                    best_snippet = chunk[:150] + "..." if len(chunk) > 150 else chunk
                    
        return round(best_score, 4), best_doc_id, best_snippet
