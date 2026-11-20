"""毎月の新刊おすすめレポートを Markdown で出力する。

使い方:
    RAKUTEN_APP_ID=... OPENAI_API_KEY=... python monthly_report.py
    python monthly_report.py --month 2026-12 --genres business,novel --out report.md

好みは --preferences または環境変数 READING_PREFERENCES で指定できます。
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date

from book_recommender.genres import GENRES, GENRES_BY_KEY
from book_recommender.report import to_markdown
from book_recommender.service import make_clients, recommend_for_genres


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--month", help="対象月 YYYY-MM（省略時は今月）")
    p.add_argument(
        "--genres",
        default=",".join(g.key for g in GENRES),
        help="カンマ区切りのジャンルキー: " + ", ".join(f"{g.key}({g.label})" for g in GENRES),
    )
    p.add_argument("--top", type=int, default=5, help="ジャンルごとの冊数")
    p.add_argument("--preferences", default=os.environ.get("READING_PREFERENCES", ""))
    p.add_argument(
        "--source", choices=["auto", "ndl", "rakuten"], default=None,
        help="データ取得元（省略時は BOOK_SOURCE 環境変数、なければ auto）",
    )
    p.add_argument("--out", help="出力ファイル（省略時は標準出力）")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.month:
        year, month = (int(x) for x in args.month.split("-"))
    else:
        today = date.today()
        year, month = today.year, today.month

    try:
        genres = [GENRES_BY_KEY[k.strip()] for k in args.genres.split(",") if k.strip()]
    except KeyError as e:
        print(f"不明なジャンル: {e}", file=sys.stderr)
        return 2

    sources, recommender = make_clients(args.source)
    results = recommend_for_genres(
        sources, recommender, genres, year, month, args.preferences, args.top,
        on_progress=lambda m: print(m, file=sys.stderr),
    )
    md = to_markdown(year, month, results)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
