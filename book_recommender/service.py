"""取得 → おすすめ生成までをまとめた処理（画面・月次バッチ共通）。"""

from __future__ import annotations

from datetime import date

from . import config
from .genres import Genre
from .rakuten import Book, RakutenBooksClient
from .recommender import GenreResult, Recommender


def shift_month(d: date, months: int) -> tuple[int, int]:
    total = d.year * 12 + (d.month - 1) + months
    return total // 12, total % 12 + 1


def make_clients():
    from openai import OpenAI

    rakuten_id = config.rakuten_application_id()
    openai_key = config.openai_api_key()
    missing = [
        name
        for name, v in [("楽天アプリケーションID", rakuten_id), ("OpenAI APIキー", openai_key)]
        if not v
    ]
    if missing:
        raise RuntimeError("設定が不足しています: " + "、".join(missing))
    rakuten = RakutenBooksClient(rakuten_id, endpoint=config.rakuten_endpoint())
    recommender = Recommender(OpenAI(api_key=openai_key), model=config.openai_model())
    return rakuten, recommender


def recommend_for_genres(
    rakuten: RakutenBooksClient,
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
        books: list[Book] = rakuten.fetch_new_releases(genre.rakuten_genre_id, year, month)
        if on_progress:
            on_progress(f"{genre.label}: {len(books)}冊からおすすめを選定中…")
        results.append(recommender.recommend(genre, books, preferences, top_n))
    return results
