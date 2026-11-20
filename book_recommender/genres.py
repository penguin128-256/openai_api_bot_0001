"""対象ジャンルの定義。

- rakuten_genre_id: 楽天ブックスのジャンルID（楽天ブックスジャンル検索APIで確認可能）
- ndc_prefixes: 国立国会図書館サーチで使う日本十進分類法(NDC)の先頭番号
  例: 33=経済, 336=経営, 913=日本の小説, 4=自然科学
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Genre:
    key: str
    label: str
    rakuten_genre_id: str
    ndc_prefixes: tuple[str, ...] = ()
    # LLMへ伝える補足（このジャンルで重視してほしい観点）
    hint: str = ""


GENRES: list[Genre] = [
    Genre(
        key="business",
        label="ビジネス・経済",
        rakuten_genre_id="001006",
        ndc_prefixes=("33", "67"),  # 経済・経営 / 商業・マーケティング
        hint="実務に活かせるか、新しい視点が得られるかを重視。",
    ),
    Genre(
        key="novel",
        label="小説・エッセイ",
        rakuten_genre_id="001004",
        ndc_prefixes=("913", "914", "933"),  # 日本の小説 / 日本のエッセイ / 英米の小説
        hint="ミステリー/SF/純文学/歴史などサブジャンルが偏らないように。",
    ),
    Genre(
        key="humanities",
        label="人文・思想・社会",
        rakuten_genre_id="001008",
        ndc_prefixes=("1", "2", "36"),  # 哲学・心理 / 歴史 / 社会
        hint="教養として読み応えがあるものを重視。",
    ),
    Genre(
        key="science",
        label="科学・技術",
        rakuten_genre_id="001012",
        ndc_prefixes=("4",),  # 自然科学
        hint="専門書より一般読者向けの読み物を優先。",
    ),
]

GENRES_BY_KEY = {g.key: g for g in GENRES}
