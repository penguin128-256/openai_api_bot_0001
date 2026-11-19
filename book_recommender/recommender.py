"""LLMで新刊候補からおすすめを選び、理由を付ける。"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .genres import Genre
from .rakuten import Book

DEFAULT_MODEL = "gpt-4o-mini"
MAX_CANDIDATES = 60
CAPTION_CHARS = 180


@dataclass
class Recommendation:
    book: Book
    subgenre: str
    reason: str
    who_for: str


@dataclass
class GenreResult:
    genre: Genre
    summary: str
    recommendations: list[Recommendation]
    candidate_count: int


def select_candidates(books: list[Book], limit: int = MAX_CANDIDATES) -> list[Book]:
    """LLMに渡す候補を絞る。内容紹介がある本・レビューの多い本を優先する。"""
    def score(b: Book) -> tuple:
        return (bool(b.caption), b.review_count, b.review_average)

    return sorted(books, key=score, reverse=True)[:limit]


SYSTEM_PROMPT = """あなたは書店のベテラン書店員です。今月の新刊リストから、
読者の好みに合う本を選んで紹介します。

ルール:
- 必ず与えられた候補リストの中からのみ選び、候補の id で指定すること。
- リストにない本、内容を知らない本について事実を作らないこと。紹介文は候補の情報から言える範囲で書く。
- 同じシリーズや似た内容の本ばかりにならないよう、バラエティを持たせる。
- 新装版・重版・ムック・雑誌的なものより、新作を優先する。
- 出力は JSON のみ。"""


def build_user_prompt(
    genre: Genre, candidates: list[Book], preferences: str, top_n: int
) -> str:
    items = [
        {
            "id": i,
            "title": b.title,
            "author": b.author,
            "publisher": b.publisher,
            "sales_date": b.sales_date,
            "size": b.size,
            "caption": b.caption[:CAPTION_CHARS],
            "reviews": b.review_count,
        }
        for i, b in enumerate(candidates)
    ]
    return f"""ジャンル: {genre.label}
このジャンルの選び方: {genre.hint or "特になし"}

読者の好み:
{preferences.strip() or "特に指定なし（幅広い読者向けに選ぶ）"}

候補リスト（{len(items)}冊）:
{json.dumps(items, ensure_ascii=False)}

この中からおすすめを最大{top_n}冊、おすすめ度の高い順に選んでください。
次の形式の JSON で答えてください:
{{
  "summary": "今月のこのジャンルの傾向を1〜2文で",
  "recommendations": [
    {{"id": 候補のid, "subgenre": "ミステリー/経営戦略 など短いラベル",
      "reason": "おすすめ理由（2〜3文）", "who_for": "こんな人に（1文）"}}
  ]
}}"""


def parse_response(
    content: str, candidates: list[Book], top_n: int
) -> tuple[str, list[Recommendation]]:
    """LLMの応答を検証し、候補にない id や重複は捨てる。"""
    data = json.loads(content)
    recs: list[Recommendation] = []
    used: set[int] = set()
    for r in data.get("recommendations", []):
        try:
            idx = int(r.get("id"))
        except (TypeError, ValueError):
            continue
        if idx in used or not 0 <= idx < len(candidates):
            continue
        used.add(idx)
        recs.append(
            Recommendation(
                book=candidates[idx],
                subgenre=str(r.get("subgenre", "")),
                reason=str(r.get("reason", "")),
                who_for=str(r.get("who_for", "")),
            )
        )
        if len(recs) >= top_n:
            break
    return str(data.get("summary", "")), recs


class Recommender:
    def __init__(self, client, model: str = DEFAULT_MODEL):
        """client は openai.OpenAI のインスタンス。"""
        self.client = client
        self.model = model

    def recommend(
        self, genre: Genre, books: list[Book], preferences: str = "", top_n: int = 5
    ) -> GenreResult:
        candidates = select_candidates(books)
        if not candidates:
            return GenreResult(genre, "対象月の新刊が見つかりませんでした。", [], 0)

        response = self.client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_user_prompt(genre, candidates, preferences, top_n),
                },
            ],
        )
        content = response.choices[0].message.content or "{}"
        summary, recs = parse_response(content, candidates, top_n)
        return GenreResult(genre, summary, recs, len(books))
