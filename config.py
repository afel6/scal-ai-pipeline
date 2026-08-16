from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List, Optional
import secrets
import os

class Settings(BaseSettings):
    GEMINI_API_KEY: Optional[str] = Field(None, description="Comma-separated API keys")
    DATABASE_URL: str = Field("", description="Neon PostgreSQL connection URL")
    DB_DIR: str = Field(".", description="SQLite DB directory path")
    PRC_AI_VAULT: str = Field("C:/Users/Asus/Downloads/PRC_AI_Vault", description="Shared Vault Export Directory")
    ALLOWED_ORIGINS: str = Field("http://localhost:5173,http://127.0.0.1:5173", description="Comma-separated allowed origins")
    ADMIN_PIN: str = Field(default_factory=lambda: secrets.token_hex(32), description="Admin secure PIN")
    USER_PIN: str = Field(default="", description="User access PIN; falls back to ADMIN_PIN when unset — set a distinct value in production")
    KB_INGEST_SECRET: str = Field(default_factory=lambda: secrets.token_hex(32), description="KB Ingestion Secret")
    SCAL_MAX_UPLOAD_MB: int = Field(75, description="Max upload size in MB")
    TESTING: bool = Field(False, description="Pytest mode")
    PYTHON_EXE: str = Field("python", description="Python path")
    CHROMA_DIR: str = Field("./chroma_db", description="ChromaDB path")
    GRAPH_DB_PATH: Optional[str] = Field(
        None,
        description="SQLite path for the Geological Knowledge Graph. Defaults to "
        "<DB_DIR>/geological_graph.sqlite when unset.",
    )
    SANDBOX_MAX_ITERATIONS: int = Field(
        12, description="Max auto-correction refit loops in the physics sandbox"
    )
    SANDBOX_SW_TOLERANCE: float = Field(
        1e-6, description="Absolute slack on the [0, 1] water-saturation bound check"
    )
    DEBUG: bool = Field(False, description="Debug mode")
    REDIS_URL: Optional[str] = Field(None, description="Redis URL")
    ALERT_SMTP_HOST: Optional[str] = Field(None, description="SMTP server for alerting")
    ALERT_SMTP_PORT: int = Field(587, description="SMTP port")
    ALERT_SMTP_USER: Optional[str] = Field(None, description="SMTP user")
    ALERT_SMTP_PASSWORD: Optional[str] = Field(None, description="SMTP password")
    ALERT_EMAIL_TO: Optional[str] = Field(None, description="Email address to send alerts to")
    ALERT_WEBHOOK_URL: Optional[str] = Field(None, description="Webhook URL for alerting")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @property
    def gemini_keys(self) -> List[str]:
        keys = []
        if self.GEMINI_API_KEY:
            keys.extend([k.strip(' \n\r\t"\'') for k in self.GEMINI_API_KEY.split(",") if k.strip(' \n\r\t"\'')])
        # Load additional GEMINI_API_KEY1, GEMINI_API_KEY2... from env/dotenv
        for k, v in os.environ.items():
            if k.startswith("GEMINI_API_KEY") and k != "GEMINI_API_KEY":
                keys.extend([x.strip(' \n\r\t"\'') for x in v.split(",") if x.strip(' \n\r\t"\'')])
        keys = list(dict.fromkeys(keys))
        if not keys:
            return ["DUMMY_KEY"]
        return keys

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def graph_db_path(self) -> str:
        """Resolved on-disk location for the Geological Knowledge Graph SQLite store.

        Honours an explicit GRAPH_DB_PATH; otherwise lands alongside the other
        persistent assets under DB_DIR so the graph survives Render redeploys.
        """
        if self.GRAPH_DB_PATH:
            return self.GRAPH_DB_PATH
        return os.path.join(self.DB_DIR or ".", "geological_graph.sqlite")

settings = Settings()
