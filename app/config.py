"""Runtime settings loaded from the environment and an optional .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_prefix="SAAN_",
        extra="ignore",
    )

    secret_key: str = "dev-only-change-me"
    database_url: str = "sqlite:///./data/saan.db"
    upload_dir: str = "./data/uploads"
    max_upload_bytes: int = 12 * 1024 * 1024
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    tesseract_cmd: str = ""
    session_https_only: bool = False
    seed_demo: bool = False
    public_base_url: str = "http://127.0.0.1:8000"
    line_channel_id: str = ""
    line_channel_secret: str = ""
    facebook_app_id: str = ""
    facebook_app_secret: str = ""

    def resolved_database_url(self) -> str:
        url = self.database_url
        prefix = "sqlite:///"
        if not url.startswith(prefix):
            return url
        raw = url[len(prefix) :]
        if raw.startswith("./") or not Path(raw).is_absolute():
            path = (ROOT / raw.removeprefix("./")).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            return prefix + path.as_posix()
        return url

    def resolved_upload_dir(self) -> Path:
        path = Path(self.upload_dir)
        if not path.is_absolute():
            path = ROOT / path
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()
