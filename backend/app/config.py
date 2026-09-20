from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    database_url: str = "sqlite:///./data/atlas.db"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_reasoning_effort: str = "auto"
    github_token: str = ""
    github_clone_proxy: str = "https://gh-proxy.org"
    upload_dir: str = "./data/uploads"
    workspace_dir: str = ""
    repository_dir: str = "./data/repositories"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
Path(settings.workspace_dir or settings.repository_dir).mkdir(parents=True, exist_ok=True)

