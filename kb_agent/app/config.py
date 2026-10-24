"""全局配置。所有密钥只允许从环境变量 / .env 读取，代码内不出现硬编码密钥。"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    APP_NAME: str = "知识库 Agent"
    API_PREFIX: str = "/api"

    DATABASE_URL: str = f"sqlite:///{BASE_DIR / 'data' / 'kb_agent.db'}"
    REDIS_URL: str = "redis://localhost:6379/0"

    JWT_SECRET: str = "dev-only-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 720

    LLM_BASE_URL: str = "https://api.deepseek.com/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "deepseek-flash"
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 2048

    EMBEDDING_PROVIDER: str = "auto"
    EMBEDDING_MODEL: str = "BAAI/bge-small-zh-v1.5"
    EMBEDDING_DIM: int = 512
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50
    RETRIEVE_TOP_K: int = 5
    # 召回相关度门槛：绝对分 + 相对最高分比例，避免把无关文档当作"无权访问"提示
    MIN_RELEVANCE: float = 0.18
    MIN_RELATIVE_SCORE: float = 0.75

    FAQ_HIT_THRESHOLD: int = 5
    FAQ_SEMANTIC_THRESHOLD: float = 0.85
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    AUTO_CREATE_TABLES: bool = True

    @property
    def data_dir(self) -> Path:
        return BASE_DIR / "data"

    @property
    def upload_dir(self) -> Path:
        return BASE_DIR / "uploads"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "index"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.upload_dir, self.index_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


settings = get_settings()
