"""APIキーなどの設定を Streamlit の Secrets または環境変数から読む。"""

from __future__ import annotations

import os

from .rakuten import DEFAULT_ENDPOINT
from .recommender import DEFAULT_MODEL


def _from_streamlit(section: str, key: str) -> str | None:
    try:
        import streamlit as st

        return st.secrets[section][key]
    except Exception:
        return None


def get_setting(section: str, key: str, env: str, default: str | None = None) -> str | None:
    return os.environ.get(env) or _from_streamlit(section, key) or default


def openai_api_key() -> str | None:
    return get_setting("OpenAIAPI", "openai_api_key", "OPENAI_API_KEY")


def openai_model() -> str:
    return get_setting("OpenAIAPI", "model", "OPENAI_MODEL", DEFAULT_MODEL)


def rakuten_application_id() -> str | None:
    return get_setting("RakutenAPI", "application_id", "RAKUTEN_APP_ID")


def rakuten_endpoint() -> str:
    return get_setting("RakutenAPI", "endpoint", "RAKUTEN_ENDPOINT", DEFAULT_ENDPOINT)
