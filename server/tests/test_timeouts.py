"""Timeouts and retries of provider calls: the models get them from config.py, and a timeout (after all retries)
becomes a 504 the UI can offer to retry, while other failures stay 502. No API calls are made."""

import httpx
import openai
import pytest

from app.core import config, llm
from app.rag import qa, vectorstore


def _timeout() -> openai.APITimeoutError:
    return openai.APITimeoutError(request=httpx.Request("POST", "https://example.invalid/chat/completions"))


def test_chat_model_has_timeout_and_retries(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "test-key")
    llm.chat_model.cache_clear()
    try:
        model = llm.chat_model(0.1)
        assert model.request_timeout == config.LLM_TIMEOUT_SECONDS
        assert model.max_retries == config.LLM_MAX_RETRIES
    finally:
        llm.chat_model.cache_clear()


def test_embeddings_have_timeout_and_retries(monkeypatch):
    monkeypatch.setattr(vectorstore, "API_KEY", "test-key")
    vectorstore._embeddings.cache_clear()
    try:
        embeddings = vectorstore._embeddings()
        assert embeddings.request_timeout == config.EMBEDDING_TIMEOUT_SECONDS
        assert embeddings.max_retries == config.LLM_MAX_RETRIES
    finally:
        vectorstore._embeddings.cache_clear()


def test_timeout_is_found_behind_a_wrapping_error():
    try:
        try:
            raise _timeout()
        except openai.APITimeoutError as e:
            raise vectorstore.VectorStoreError(f"Vector search failed: {e}") from e
    except vectorstore.VectorStoreError as wrapped:
        failure = llm.model_failure(wrapped, None)
    assert failure.status_code == 504
    assert "try again" in str(failure)


def test_other_failures_stay_502():
    failure = llm.model_failure(ValueError("bad JSON"))
    assert failure.status_code == 502
    assert str(failure) == "The language model call failed: bad JSON"


def test_answer_question_turns_a_timeout_into_504(monkeypatch):
    class TimingOutGraph:
        def invoke(self, *args, **kwargs):
            raise _timeout()

    monkeypatch.setattr(qa, "is_configured", lambda: True)
    monkeypatch.setattr(qa, "_graph", lambda: TimingOutGraph())
    with pytest.raises(llm.GenerationError) as caught:
        qa.answer_question("demo-campaign", "What is a bucket shop?", k=5)
    assert caught.value.status_code == 504
