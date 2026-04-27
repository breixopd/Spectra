import os

import pytest

from app.services.ai.llm import get_llm_client


@pytest.mark.skipif(
    os.environ.get("SKIP_LLM_LIVE") == "1"
    or (not os.environ.get("OPENAI_API_KEY") and not os.environ.get("OPENROUTER_API_KEY")),
    reason="LLM connectivity test requires OPENAI_API_KEY or OPENROUTER_API_KEY (set SKIP_LLM_LIVE=1 to skip)",
)
@pytest.mark.asyncio
async def test_llm_connectivity():
    """Verify we can talk to the LLM."""
    print("\n[IT] Initializing LLM...")
    client = get_llm_client()
    print(f"[IT] Provider: {client.provider}")

    try:
        response = await client.generate("Hello, are you there?", max_tokens=10)
        print(f"[IT] Response: {response}")
        assert response
        assert len(response) > 0
    except Exception as e:
        pytest.fail(f"LLM Connection failed: {e}")
