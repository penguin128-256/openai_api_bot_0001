import json
from types import SimpleNamespace

from book_recommender.genres import GENRES_BY_KEY
from book_recommender.rakuten import RakutenBooksClient, parse_year_month
from book_recommender.recommender import Recommender, parse_response, select_candidates
from book_recommender.report import to_markdown


def item(title, sales_date, caption="内容紹介", reviews=0):
    return {
        "isbn": f"isbn-{title}", "title": title, "author": "著者", "publisherName": "出版社",
        "salesDate": sales_date, "itemCaption": caption, "itemUrl": f"https://example/{title}",
        "largeImageUrl": "", "itemPrice": 1980, "reviewCount": reviews, "reviewAverage": "4.0",
        "size": "単行本",
    }


class FakeResponse:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append(params)
        return FakeResponse(self.pages[params["page"] - 1])


def test_parse_year_month():
    assert parse_year_month("2026年11月19日") == (2026, 11)
    assert parse_year_month("2026年11月下旬") == (2026, 11)
    assert parse_year_month("2027年 1月") == (2027, 1)
    assert parse_year_month("未定") is None


def test_fetch_new_releases_skips_future_and_stops_at_older_month():
    pages = [
        {"pageCount": 5, "Items": [item("予約本", "2026年12月05日"), item("A", "2026年11月30日")]},
        {"pageCount": 5, "Items": [item("B", "2026年11月下旬"), item("A", "2026年11月30日"),
                                    item("旧刊", "2026年10月31日")]},
        {"pageCount": 5, "Items": [item("呼ばれないはず", "2026年11月01日")]},
    ]
    session = FakeSession(pages)
    client = RakutenBooksClient("app-id", session=session, sleep=lambda s: None)
    books = client.fetch_new_releases("001006", 2026, 11)

    assert [b.title for b in books] == ["A", "B"]  # 予約本・旧刊・重複を除外
    assert len(session.calls) == 2  # 10月の本が出たページで打ち切り
    assert session.calls[0]["sort"] == "-releaseDate"
    assert session.calls[0]["booksGenreId"] == "001006"


def test_select_candidates_prefers_caption_and_reviews():
    client = RakutenBooksClient("x", session=FakeSession([{"Items": [
        item("説明なし", "2026年11月", caption=""),
        item("レビュー多", "2026年11月", reviews=10),
        item("普通", "2026年11月"),
    ]}]), sleep=lambda s: None)
    books = client.fetch_new_releases("g", 2026, 11, max_pages=1)
    assert [b.title for b in select_candidates(books, limit=2)] == ["レビュー多", "普通"]


def test_parse_response_drops_unknown_and_duplicate_ids():
    books = RakutenBooksClient("x", session=FakeSession([{"Items": [
        item("一", "2026年11月"), item("二", "2026年11月")]}]),
        sleep=lambda s: None).fetch_new_releases("g", 2026, 11, max_pages=1)
    content = json.dumps({"summary": "傾向", "recommendations": [
        {"id": 1, "subgenre": "経営", "reason": "理由", "who_for": "管理職"},
        {"id": 1, "reason": "重複"},
        {"id": 99, "reason": "存在しない本"},
        {"id": "abc"},
        {"id": 0, "reason": "理由2"},
    ]})
    summary, recs = parse_response(content, books, top_n=5)
    assert summary == "傾向"
    assert [r.book.title for r in recs] == ["二", "一"]
    assert recs[0].subgenre == "経営"


def test_recommender_end_to_end_with_fake_llm():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        msg = SimpleNamespace(content=json.dumps(
            {"summary": "s", "recommendations": [{"id": 0, "reason": "r", "who_for": "w"}]}))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    llm = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    books = RakutenBooksClient("x", session=FakeSession([{"Items": [item("本", "2026年11月")]}]),
                               sleep=lambda s: None).fetch_new_releases("g", 2026, 11, max_pages=1)
    genre = GENRES_BY_KEY["business"]
    result = Recommender(llm, model="m").recommend(genre, books, preferences="マーケティング", top_n=3)

    assert captured["model"] == "m"
    assert "マーケティング" in captured["messages"][1]["content"]
    assert result.recommendations[0].book.title == "本"

    md = to_markdown(2026, 11, [result])
    assert "# 📚 2026年11月の新刊おすすめ" in md
    assert "[本](https://example/本)" in md


def test_recommender_without_books_skips_llm():
    llm = SimpleNamespace()  # 呼ばれたら AttributeError
    result = Recommender(llm).recommend(GENRES_BY_KEY["novel"], [], "", 5)
    assert result.recommendations == []
