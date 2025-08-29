# config.py
import os
from typing import Optional
from dataclasses import dataclass
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

def _get(key: str, default: Optional[str] = None) -> Optional[str]:
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)

@dataclass(frozen=True)
class AppConfig:
    OPENAI_API_KEY: str
    OPENAI_MODEL: str
    # Snowflake
    SF_ACCOUNT: str
    SF_USER: str
    SF_PASSWORD: str
    SF_WAREHOUSE: str
    SF_DATABASE: str
    SF_SCHEMA: str

    @property
    def snowflake_all_present(self) -> bool:
        vals = [self.SF_ACCOUNT, self.SF_USER, self.SF_PASSWORD, self.SF_WAREHOUSE, self.SF_DATABASE, self.SF_SCHEMA]
        return all(bool(v) for v in vals)

def get_config() -> "AppConfig":
    return AppConfig(
        OPENAI_API_KEY=_get("OPENAI_API_KEY", ""),
        OPENAI_MODEL=_get("OPENAI_MODEL", "gpt-4o-mini"),
        SF_ACCOUNT=_get("SNOWFLAKE_ACCOUNT", ""),
        SF_USER=_get("SNOWFLAKE_USER", ""),
        SF_PASSWORD=_get("SNOWFLAKE_PASSWORD", ""),
        SF_WAREHOUSE=_get("SNOWFLAKE_WAREHOUSE", ""),
        SF_DATABASE=_get("SNOWFLAKE_DATABASE", ""),
        SF_SCHEMA=_get("SNOWFLAKE_SCHEMA", ""),
    )
