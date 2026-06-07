from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ollama_base_url: str = "http://host.docker.internal:11434"
    openviking_url: str = "http://openviking:1933"
    openviking_api_key: str | None = None
    openviking_account: str = "default"
    openviking_user: str = "api"
    marker_url: str = "http://marker:8001"
    qdrant_url: str = "http://qdrant:6333"
    pdf_path: str = "/data/BCTN_MSB_2024.pdf"
    processed_docs_path: str = "/processed_docs"
    chat_model: str = "qwen3:14b"
    google_api_key: str | None = None

    model_config = {"env_prefix": ""}


settings = Settings()
