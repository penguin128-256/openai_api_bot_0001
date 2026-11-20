"""楽天ブックス書籍検索APIから、指定した月の新刊を取得する。"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass

import requests

# 2026年の楽天API刷新で旧ドメイン app.rakuten.co.jp は停止。新ドメイン＋accessKey 認証が必要。
# 楽天側でパスが異なる場合は Secrets / 環境変数の endpoint で上書きしてください。
DEFAULT_ENDPOINT = "https://openapi.rakuten.co.jp/services/api/BooksBook/Search/20170404"
HITS_PER_PAGE = 30  # APIの上限
REQUEST_INTERVAL_SEC = 1.0  # 楽天APIは1秒に1リクエスト程度に抑える


@dataclass
class Book:
    isbn: str
    title: str
    author: str
    publisher: str
    sales_date: str
    caption: str
    item_url: str
    image_url: str
    price: int
    review_count: int
    review_average: float
    size: str

    def to_dict(self) -> dict:
        return asdict(self)


_DATE_RE = re.compile(r"(\d{4})年\s*(\d{1,2})月")


def parse_year_month(sales_date: str) -> tuple[int, int] | None:
    """'2026年11月19日' / '2026年11月下旬' / '2026年11月' などから (年, 月) を取り出す。"""
    m = _DATE_RE.search(sales_date or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _to_book(item: dict) -> Book:
    return Book(
        isbn=item.get("isbn", ""),
        title=item.get("title", ""),
        author=item.get("author", ""),
        publisher=item.get("publisherName", ""),
        sales_date=item.get("salesDate", ""),
        caption=item.get("itemCaption", ""),
        item_url=item.get("itemUrl", ""),
        image_url=item.get("largeImageUrl") or item.get("mediumImageUrl", ""),
        price=int(item.get("itemPrice") or 0),
        review_count=int(item.get("reviewCount") or 0),
        review_average=float(item.get("reviewAverage") or 0),
        size=item.get("size", ""),
    )


class RakutenAPIError(RuntimeError):
    def __init__(self, status: int, body: str):
        hint = {
            401: "アプリIDまたは accessKey が正しくありません。",
            403: "許可IPに現在のサーバーのIPが含まれていない可能性があります。",
            503: "認証エラーの可能性があります。アプリ種別が『バックエンドサービス』か、"
                 "新しい(UUID形式の)アプリIDと accessKey を使っているか確認してください。",
        }.get(status, "")
        super().__init__(f"楽天API エラー {status}: {hint} {body}".strip())
        self.status = status


class RakutenBooksClient:
    name = "楽天ブックス"

    def __init__(
        self,
        application_id: str,
        access_key: str = "",
        endpoint: str = DEFAULT_ENDPOINT,
        session: requests.Session | None = None,
        sleep=time.sleep,
    ):
        if not application_id:
            raise ValueError("楽天のアプリケーションIDが設定されていません。")
        self.application_id = application_id
        self.access_key = access_key
        self.endpoint = endpoint
        self.session = session or requests.Session()
        self._sleep = sleep

    def _search_page(self, genre_id: str, page: int) -> dict:
        params = {
            "format": "json",
            "formatVersion": 2,
            "applicationId": self.application_id,
            "booksGenreId": genre_id,
            "sort": "-releaseDate",
            "hits": HITS_PER_PAGE,
            "page": page,
            "outOfStockFlag": 1,  # 予約受付中の本も含める
        }
        if self.access_key:
            params["accessKey"] = self.access_key
        # 新APIはバックエンド型アプリで Origin ヘッダを付けると 503 になるため付けない
        resp = self.session.get(self.endpoint, params=params, timeout=20)
        if resp.status_code >= 400:
            raise RakutenAPIError(resp.status_code, resp.text[:300])
        return resp.json()

    def fetch(self, genre, year: int, month: int) -> list[Book]:
        return self.fetch_new_releases(genre.rakuten_genre_id, year, month)

    def fetch_new_releases(
        self, genre_id: str, year: int, month: int, max_pages: int = 15
    ) -> list[Book]:
        """発売日の新しい順に読み進め、対象月の本だけを集める。

        予約中の本（対象月より未来）は読み飛ばし、対象月より古い本が
        出てきたらそこで打ち切る。
        """
        target = (year, month)
        books: list[Book] = []
        seen: set[str] = set()

        for page in range(1, max_pages + 1):
            if page > 1:
                self._sleep(REQUEST_INTERVAL_SEC)
            data = self._search_page(genre_id, page)
            items = data.get("Items", [])
            # formatVersion=1 の形式 ({"Item": {...}}) にも対応
            items = [it.get("Item", it) for it in items]
            if not items:
                break

            reached_older = False
            for item in items:
                ym = parse_year_month(item.get("salesDate", ""))
                if ym is None:
                    continue
                if ym > target:
                    continue
                if ym < target:
                    reached_older = True
                    continue
                book = _to_book(item)
                key = book.isbn or book.title
                if key in seen:
                    continue
                seen.add(key)
                books.append(book)

            if reached_older or page >= int(data.get("pageCount") or 0):
                break

        return books
