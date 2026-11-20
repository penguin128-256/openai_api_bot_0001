"""国立国会図書館サーチ (NDL Search) OpenSearch API から新刊を取得する。

APIキー・利用登録は不要。NDC（日本十進分類法）と出版年月で絞り込む。
NDL には内容紹介がほとんど無いため、openBD (ISBN検索) で内容紹介と書影を補う。

注意: NDL への登録は納本後になるため、発売から数日〜数週間遅れて反映される。
月初は「先月」を対象にするのがおすすめ。
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET

import requests

from .rakuten import Book

DEFAULT_ENDPOINT = "https://ndlsearch.ndl.go.jp/api/opensearch"
OPENBD_ENDPOINT = "https://api.openbd.jp/v1/get"
PAGE_SIZE = 200
REQUEST_INTERVAL_SEC = 1.0


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in el if _local(c.tag) == name]


def _text(el: ET.Element, name: str) -> str:
    for c in _children(el, name):
        if c.text and c.text.strip():
            return c.text.strip()
    return ""


def _attr_type(el: ET.Element) -> str:
    for k, v in el.attrib.items():
        if _local(k) == "type":
            return v
    return ""


def normalize_isbn(raw: str) -> str:
    return re.sub(r"[^0-9X]", "", raw.upper())


_ISSUED_RE = re.compile(r"(\d{4})\D?(\d{1,2})")


def parse_issued(raw: str) -> tuple[int, int] | None:
    """'2026.11' / '2026-11' / '2026-11-19' / '2026年11月' → (2026, 11)"""
    m = _ISSUED_RE.search(raw or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def parse_items(xml_text: str) -> tuple[int, list[dict]]:
    root = ET.fromstring(xml_text)
    channel = next((c for c in root.iter() if _local(c.tag) == "channel"), root)
    total = 0
    for c in channel:
        if _local(c.tag) == "totalResults" and c.text:
            total = int(c.text)
    items = []
    for it in _children(channel, "item"):
        isbn = ""
        ndc = ""
        for c in _children(it, "identifier"):
            if _attr_type(c).endswith("ISBN") and c.text:
                isbn = normalize_isbn(c.text)
                break
        for c in _children(it, "subject"):
            if "NDC" in _attr_type(c) and c.text:
                ndc = c.text.strip()
                break
        creators = [c.text.strip() for c in _children(it, "creator") if c.text]
        items.append({
            "isbn": isbn,
            "ndc": ndc,
            "title": _text(it, "title"),
            "author": ", ".join(creators) or _text(it, "author"),
            "publisher": _text(it, "publisher"),
            "issued": _text(it, "issued") or _text(it, "date"),
            "description": _text(it, "description"),
            "link": _text(it, "link"),
            "extent": _text(it, "extent"),
            "price": _text(it, "price"),
        })
    return total, items


def _price(raw: str) -> int:
    m = re.search(r"(\d[\d,]*)", raw or "")
    return int(m.group(1).replace(",", "")) if m else 0


class NDLSearchClient:
    name = "国立国会図書館サーチ"

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        session: requests.Session | None = None,
        sleep=time.sleep,
        enrich_with_openbd: bool = True,
        max_per_prefix: int = 600,
    ):
        self.endpoint = endpoint
        self.session = session or requests.Session()
        self._sleep = sleep
        self.enrich_with_openbd = enrich_with_openbd
        self.max_per_prefix = max_per_prefix
        self._calls = 0

    def _get(self, url: str, params: dict) -> requests.Response:
        if self._calls:
            self._sleep(REQUEST_INTERVAL_SEC)
        self._calls += 1
        resp = self.session.get(url, params=params, timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(f"NDLサーチ API エラー {resp.status_code}: {resp.text[:200]}")
        return resp

    def search(self, ndc: str, year: int, month: int) -> list[dict]:
        ym = f"{year:04d}-{month:02d}"
        results: list[dict] = []
        idx = 1
        while len(results) < self.max_per_prefix:
            params = {"ndc": ndc, "from": ym, "until": ym, "cnt": PAGE_SIZE, "idx": idx}
            total, items = parse_items(self._get(self.endpoint, params).text)
            results += items
            idx += PAGE_SIZE
            if not items or idx > total:
                break
        return results

    def fetch(self, genre, year: int, month: int) -> list[Book]:
        books: dict[str, Book] = {}
        for prefix in genre.ndc_prefixes:
            for it in self.search(prefix, year, month):
                # ISBN のない資料（雑誌記事・非売品など）や対象月外は除く
                if not it["isbn"] or parse_issued(it["issued"]) != (year, month):
                    continue
                if it["ndc"] and not it["ndc"].startswith(prefix):
                    continue
                if it["isbn"] in books:
                    continue
                books[it["isbn"]] = Book(
                    isbn=it["isbn"],
                    title=it["title"],
                    author=it["author"],
                    publisher=it["publisher"],
                    sales_date=it["issued"],
                    caption=it["description"],
                    item_url=it["link"],
                    image_url=f"https://ndlsearch.ndl.go.jp/thumbnail/{it['isbn']}.jpg",
                    price=_price(it["price"]),
                    review_count=0,
                    review_average=0.0,
                    size=it["extent"],
                )
        result = list(books.values())
        if self.enrich_with_openbd and result:
            self._enrich(result)
        return result

    def _enrich(self, books: list[Book]) -> None:
        """openBD から内容紹介と書影を補う。失敗しても無視する。"""
        try:
            resp = self.session.post(
                OPENBD_ENDPOINT, data={"isbn": ",".join(b.isbn for b in books)}, timeout=30
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return
        for book, rec in zip(books, data):
            if not rec:
                continue
            summary = rec.get("summary") or {}
            if summary.get("cover"):
                book.image_url = summary["cover"]
            if not book.caption:
                texts = (
                    rec.get("onix", {}).get("CollateralDetail", {}).get("TextContent", [])
                )
                # TextType 03=内容紹介, 02=短い説明
                for want in ("03", "02"):
                    for t in texts:
                        if t.get("TextType") == want and t.get("Text"):
                            book.caption = t["Text"]
                            break
                    if book.caption:
                        break
