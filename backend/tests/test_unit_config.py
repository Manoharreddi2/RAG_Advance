import pytest

from app.config import Settings


def test_managed_database_url_gets_async_driver():
    assert Settings(database_url="postgres://u:p@h/db").database_url == "postgresql+asyncpg://u:p@h/db"
    assert Settings(database_url="postgresql://u:p@h/db").database_url == "postgresql+asyncpg://u:p@h/db"


def test_qdrant_host_and_cors_parsing():
    assert Settings(qdrant_host="qdrant:6333").qdrant_url == "http://qdrant:6333"
    assert Settings(cors_origins="https://a.com, https://b.com").cors_origins == ["https://a.com", "https://b.com"]
    assert Settings(cors_origins='["https://x.com"]').cors_origins == ["https://x.com"]


def test_production_requires_strong_secret():
    with pytest.raises(RuntimeError):
        Settings(environment="production").validate_for_production()
    Settings(environment="production", jwt_secret="x" * 40).validate_for_production()


def test_llm_provider_resolution():
    assert Settings(llm_provider="auto", openai_api_key="sk-x").resolved_llm_provider == "openai"
    assert Settings(llm_provider="auto", openai_api_key=None, openai_base_url="http://o:11434/v1").resolved_llm_provider == "openai_compatible"
    assert Settings(llm_provider="auto", openai_api_key=None, openai_base_url=None).resolved_llm_provider == "local"
