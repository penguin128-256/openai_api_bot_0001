"""取得 → おすすめ生成までをまとめた処理（画面・月次バッチ共通）。"""

from __future__ import annotations

from datetime import date

from . import config
from .genres import Genre
from .ndl import NDLSearchClient
from .rakuten import RakutenBooksClient
from .recommender import GenreResult, Recommender


def shift_month(d: date, months: int) -> tuple[int, int]:
    total = d.year * 12 + (d.month - 1) + months
    return total // 12, total % 12 + 1


def make_sources(source: str | None = None) -> list:
    """使うデータ取得元を優先順に返す。"""
    source = source or config.book_source()
    rakuten_id = config.rakuten_application_id()
    ndl = NDLSearchClient()

    if source == "ndl":
        return [ndl]
    if source == "rakuten":
        if not rakuten_id:
            raise RuntimeError("楽天アプリケーションIDが設定されていません。")
        return [_rakuten(rakuten_id)]
    # auto: 楽天が設定されていれば楽天を優先し、失敗したら NDL
    return ([_rakuten(rakuten_id)] if rakuten_id else []) + [ndl]


def _rakuten(app_id: str) -> RakutenBooksClient:
    return RakutenBooksClient(
        app_id, access_key=config.rakuten_access_key() or "", endpoint=config.rakuten_endpoint()
    )


def make_recommender() -> Recommender:
    from openai import OpenAI

    key = config.openai_api_key()
    if not key:
        raise RuntimeError("OpenAI APIキーが設定されていません。")
    return Recommender(OpenAI(api_key=key), model=config.openai_model())


def make_clients(source: str | None = None):
    return make_sources(source), make_recommender()


def fetch_with_fallback(sources: list, genre: Genre, year: int, month: int):
    errors = []
    for src in sources:
        try:
            return src.fetch(genre, year, month), src.name, errors
        except Exception as e:
            errors.append(f"{src.name}: {e}")
    raise RuntimeError("新刊を取得できませんでした。 " + " / ".join(errors))


def recommend_for_genres(
    sources: list,
    recommender: Recommender,
    genres: list[Genre],
    year: int,
    month: int,
    preferences: str = "",
    top_n: int = 5,
    on_progress=None,
) -> list[GenreResult]:
    results = []
    for genre in genres:
        if on_progress:
            on_progress(f"{genre.label} の新刊を取得中…")
        books, source_name, errors = fetch_with_fallback(sources, genre, year, month)
        if on_progress:
            on_progress(f"{genre.label}: {len(books)}冊からおすすめを選定中…")
        res = recommender.recommend(genre, books, preferences, top_n)
        res.source = source_name
        if errors:
            res.notice = "（取得に失敗したため切り替えました: " + " / ".join(errors) + "）"
        results.append(res)
    return results
