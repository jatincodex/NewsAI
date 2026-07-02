import os
import json
import logging
import httpx
from app.core.config import settings
from app.core.cache import get_cached_fact_check, set_cached_fact_check

logger = logging.getLogger(__name__)

class GeminiFactChecker:
    @staticmethod
    async def verify_claim(claim_content: str, reference_context: str = "") -> dict:
        """
        Invokes Gemini 2.5 Flash asynchronously to fact check a claim.
        Utilizes Redis caching to prevent redundant LLM invocations.
        """
        # 1. Check Redis Cache
        cached = get_cached_fact_check(claim_content)
        if cached:
            return cached

        # 2. Key Check & Mock Fallback
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.info("GEMINI_API_KEY environment variable not set. Using local mock AI fact checker.")
            result = GeminiFactChecker._mock_verify_claim(claim_content, reference_context)
            set_cached_fact_check(claim_content, result)
            return result

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        
        system_instruction = (
            "You are NewsAI, an autonomous fact-checking analyst. "
            "Cross-reference the user's social media claim against the TRUSTED CONTEXT "
            "and return STRICT JSON ONLY with this exact schema:\n"
            '{"verdict": "verified" | "debunked" | "uncertain", '
            '"confidence_score": <float 0.00-1.00>, '
            '"logic_breakdown": "<2-4 sentence reasoning>", '
            '"sources": ["<source 1>", "<source 2>"]}\n'
            "Rules:\n"
            "- confidence_score must be a number between 0 and 1.\n"
            "- High confidence (>=0.95) only when a trusted source directly supports/refutes the claim.\n"
            "- No markdown fences. No extra commentary. JSON only."
        )

        prompt = f"Fact-check this post content: '{claim_content}'."
        if reference_context:
            prompt += f"\nCompare against this trusted source database documents:\n{reference_context}"

        payload = {
            "contents": [{
                "parts": [
                    {"text": system_instruction},
                    {"text": prompt}
                ]
            }],
            "generationConfig": {
                "responseMimeType": "application/json"
            }
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
                if response.status_code == 200:
                    res_data = response.json()
                    text_response = res_data["candidates"][0]["content"]["parts"][0]["text"]
                    result = json.loads(text_response.strip())
                    set_cached_fact_check(claim_content, result)
                    return result
                else:
                    logger.error(f"Gemini API returned error code {response.status_code}: {response.text}")
        except Exception as e:
            logger.exception(f"Exception during Gemini API request: {e}")

        logger.warning("Gemini API call failed. Falling back to local mock AI fact checker.")
        result = GeminiFactChecker._mock_verify_claim(claim_content, reference_context)
        set_cached_fact_check(claim_content, result)
        return result

    @staticmethod
    def _mock_verify_claim(claim_content: str, reference_context: str = "") -> dict:
        """Local mock AI fact checker logic."""
        claim_lower = claim_content.lower()
        
        # Default mock responses based on claim keywords
        if "solar storm" in claim_lower or "blackout" in claim_lower or "solar flare" in claim_lower:
            accuracy = 95.0
            verdict = "Mostly Correct"
            report = (
                "# 🛡️ AI Verification Report: Solar Blackout Claim\n\n"
                "### Verdict: Mostly Correct (95% Accuracy)\n\n"
                "**Analysis Summary:**\n"
                "Space weather forecasting agencies confirm a severe coronal mass ejection (CME) occurred, "
                "leading to geomagnetic storms. The risk of local power grid instability or satellite disruption "
                "is real, but a 'global internet blackout for 3 months' is slightly exaggerated.\n\n"
                "**Key Findings:**\n"
                "- **Evidence Source:** NASA Space Weather Prediction Center.\n"
                "- **Accuracy Rating:** 95.0%\n"
                "- **Recommendations:** Local grids should monitor load fluctuation."
            )
        elif "celery juice" in claim_lower or "diabetes" in claim_lower:
            accuracy = 25.0
            verdict = "Misleading / Unproven"
            report = (
                "# 🛡️ AI Verification Report: Celery Juice Remedy\n\n"
                "### Verdict: Misleading (25% Accuracy)\n\n"
                "**Analysis Summary:**\n"
                "Viral social media claims that drinking celery juice daily can 'completely cure diabetes in two weeks' "
                "lack medical evidence and are rejected by clinical experts.\n\n"
                "**Key Findings:**\n"
                "- **Medical consensus:** Celery has hydration and antioxidant benefits, but it does not reverse insulin resistance.\n"
                "- **Evidence Source:** World Health Organization / American Diabetes Association guidelines."
            )
        elif "moon mission" in claim_lower or "artemis" in claim_lower or "kepler" in claim_lower:
            accuracy = 100.0
            verdict = "Verified Fact"
            report = (
                "# 🛡️ AI Verification Report: space Science Update\n\n"
                "### Verdict: Fully Verified (100% Accuracy)\n\n"
                "**Analysis Summary:**\n"
                "NASA's schedule for planetary discoveries and lunar exploration updates has been officially announced.\n\n"
                "**Key Findings:**\n"
                "- **Evidence Source:** NASA Kepler/Artemis Science updates."
            )
        else:
            # General fallback evaluation
            verdict = "uncertain"
        return {
            "confidence_score": score,
            "verdict": verdict,
            "logic_breakdown": "Mock logic breakdown. No API key provided.",
            "sources": ["Mock Source A", "Mock Source B"]
        }
