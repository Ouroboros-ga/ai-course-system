"""StructuredLLM provider directory.

Phase 2a introduces the ``StructuredLLMPort`` abstraction (see
``contracts/llm.py``). This package holds provider implementations
that adapt existing LLM clients to the structured port.

The first implementation (``OpenAICompatibleStructuredLLM``) wraps the
existing ``OpenAICompatibleTeachingLLM`` HTTP client pattern and adds:
    - Pydantic schema validation
    - One repair retry on validation failure
    - Token/cost tracking
    - Prompt version tagging
"""
