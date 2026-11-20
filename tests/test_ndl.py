from types import SimpleNamespace

import pytest

from book_recommender.genres import GENRES_BY_KEY
from book_recommender.ndl import NDLSearchClient, parse_issued, parse_items
from book_recommender.rakuten import RakutenAPIError, RakutenBooksClient
from book_recommender.service import fetch_with_fallback

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcndl="http://ndl.go.jp/dcndl/terms/"
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xmlns:openSearch="http://a9.com/-/spec/opensearchrss/1.0/">
<channel>
  <title>test</title>
  <openSearch:totalResults>3</openSearch:totalResults>
  <item>
    <title>霧の港の殺人</title>
    <link>https://ndlsearch.ndl.go.jp/books/R1</link>
    <dc:title>霧の港の殺人</dc:title>
    <dc:creator>鈴木一郎 著</dc:creator>
    <dc:publisher>架空出版</dc:publisher>
    <dcterms:issued xsi:type="dcterms:W3CDTF">2026.11</dcterms:issued>
    <dc:subject xsi:type="dcndl:NDC10">913.6</dc:subject>
    <dc:identifier xsi:type="dcndl:ISBN">978-4-00-000001-2</dc:identifier>
    <dcndl:price>1800円</dcndl:price>
    <dc:extent>320p ; 20cm</dc:extent>
  </item>
  <item>
    <title>ISBNなしの資料</title>
    <dcterms:issued>2026.11</dcterms:issued>
    <dc:subject xsi:type="dcndl:NDC10">913.6</dc:subject>
  </item>
  <item>
    <title>先月の本</title>
    <dcterms:issued>2026.10</dcterms:issued>
    <dc:identifier xsi:type="dcndl:ISBN">9784000000029</dc:identifier>
  </item>
</channel></rss>"""


class Session:
    def __init__(self, openbd=None):
        self.gets = []
        self.openbd = openbd

    def get(self, url, params, timeout):
        self.gets.append(params)
        return SimpleNamespace(status_code=200, text=RSS)

    def post(self, url, data, timeout):
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: self.openbd)


def test_parse_issued():
    assert parse_issued("2026.11") == (2026, 11)
    assert parse_issued("2026-11-19") == (2026, 11)
    assert parse_issued("2026年1月") == (2026, 1)
    assert parse_issued("") is None


def test_parse_items():
    total, items = parse_items(RSS)
    assert total == 3
    assert items[0]["isbn"] == "9784000000012"
    assert items[0]["ndc"] == "913.6"
    assert items[0]["author"] == "鈴木一郎 著"


def test_ndl_fetch_filters_and_enriches_with_openbd():
    openbd = [{
        "summary": {"cover": "https://cover.example/1.jpg"},
        "onix": {"CollateralDetail": {"TextContent": [{"TextType": "03", "Text": "港町の本格ミステリー"}]}},
    }]
    session = Session(openbd=openbd)
    client = NDLSearchClient(session=session, sleep=lambda s: None)
    genre = GENRES_BY_KEY["novel"]
    books = client.fetch(genre, 2026, 11)

    assert [b.title for b in books] == ["霧の港の殺人"]  # ISBNなし・先月・重複を除外
    b = books[0]
    assert b.caption == "港町の本格ミステリー"
    assert b.image_url == "https://cover.example/1.jpg"
    assert b.price == 1800
    assert session.gets[0]["from"] == "2026-11" and session.gets[0]["ndc"] == "913"
    assert len(session.gets) == len(genre.ndc_prefixes)


def test_ndl_openbd_failure_is_ignored():
    class Broken(Session):
        def post(self, *a, **k):
            raise ConnectionError("down")

    books = NDLSearchClient(session=Broken(), sleep=lambda s: None).fetch(
        GENRES_BY_KEY["novel"], 2026, 11)
    assert books[0].caption == ""
    assert books[0].image_url.endswith("/thumbnail/9784000000012.jpg")


def test_rakuten_sends_access_key_and_explains_503():
    calls = []

    class S:
        def get(self, url, params, timeout):
            calls.append((url, params))
            return SimpleNamespace(status_code=503, text="Authentication service error")

    client = RakutenBooksClient("uuid-app-id", access_key="ak", session=S(), sleep=lambda s: None)
    with pytest.raises(RakutenAPIError) as e:
        client.fetch(GENRES_BY_KEY["business"], 2026, 11)
    assert "バックエンドサービス" in str(e.value)
    url, params = calls[0]
    assert "openapi.rakuten.co.jp" in url
    assert params["accessKey"] == "ak" and params["applicationId"] == "uuid-app-id"


def test_fallback_to_next_source():
    class Failing:
        name = "楽天ブックス"

        def fetch(self, *a):
            raise RuntimeError("503")

    ndl = NDLSearchClient(session=Session(openbd=[None]), sleep=lambda s: None)
    books, name, errors = fetch_with_fallback([Failing(), ndl], GENRES_BY_KEY["novel"], 2026, 11)
    assert name == "国立国会図書館サーチ" and len(books) == 1
    assert errors == ["楽天ブックス: 503"]
