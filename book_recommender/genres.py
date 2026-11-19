"""対象ジャンルの定義。

booksGenreId は楽天ブックスのジャンルIDです。
ほかのジャンルを追加したい場合は、楽天ブックスジャンル検索API
(BooksGenre/Search) で ID を調べてここに追記してください。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Genre:
    key: str
    label: str
    rakuten_genre_id: str
    # LLMへ伝える補足（このジャンルで重視してほしい観点）
    hint: str = ""


GENRES: list[Genre] = [
    Genre(
        key="business",
        label="ビジネス・経済",
        rakuten_genre_id="001006",
        hint="実務に活かせるか、新しい視点が得られるかを重視。",
    ),
    Genre(
        key="novel",
        label="小説・エッセイ",
        rakuten_genre_id="001004",
        hint="ミステリー/SF/純文学/歴史などサブジャンルが偏らないように。",
    ),
    Genre(
        key="humanities",
        label="人文・思想・社会",
        rakuten_genre_id="001008",
        hint="教養として読み応えがあるものを重視。",
    ),
    Genre(
        key="science",
        label="科学・技術",
        rakuten_genre_id="001012",
        hint="専門書より一般読者向けの読み物を優先。",
    ),
]

GENRES_BY_KEY = {g.key: g for g in GENRES}
