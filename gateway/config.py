"""Environment-driven configuration. Values come only from the process env /
server-side .env; nothing here ever echoes a secret back to a client."""
import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

PROJECTS = {"copackers", "bypete", "offduty", "bunting", "n0v8v", "platform"}


class Settings:
    def __init__(self) -> None:
        self.database_url: str = os.environ.get("DATABASE_URL", "")
        self.public_url: str = os.environ.get("GATEWAY_PUBLIC_URL", "http://localhost:8080")
        self.env: str = os.environ.get("GATEWAY_ENV", "development")
        self.log_level: str = os.environ.get("GATEWAY_LOG_LEVEL", "INFO")

    @staticmethod
    def env_name(*parts: str) -> str:
        return "_".join(p.upper().replace("-", "_") for p in parts)

    @staticmethod
    def secret(name: str) -> str | None:
        """Fetch a secret by env var name. Returns None when unconfigured so
        adapters can report an honest 'unconfigured' state."""
        val = os.environ.get(name, "").strip()
        return val or None


@lru_cache
def settings() -> Settings:
    return Settings()
