"""おすすめ結果を Markdown に整形する（月次レポート・Issue 用）。"""

from __future__ import annotations

from .recommender import GenreResult


def to_markdown(year: int, month: int, results: list[GenreResult]) -> str:
    lines = [f"# 📚 {year}年{month}月の新刊おすすめ", ""]
    for res in results:
        lines += [f"## {res.genre.label}", ""]
        if res.summary:
            lines += [f"_{res.summary}_", ""]
        if not res.recommendations:
            lines += ["おすすめできる新刊が見つかりませんでした。", ""]
            continue
        for i, rec in enumerate(res.recommendations, 1):
            b = rec.book
            title = f"[{b.title}]({b.item_url})" if b.item_url else b.title
            tag = f" `{rec.subgenre}`" if rec.subgenre else ""
            lines.append(f"### {i}. {title}{tag}")
            lines.append(f"{b.author} / {b.publisher} / {b.sales_date} / {b.price:,}円")
            lines.append("")
            lines.append(rec.reason)
            if rec.who_for:
                lines.append(f"- **こんな人に**: {rec.who_for}")
            lines.append("")
        src = f"{res.source} の" if res.source else ""
        lines.append(f"<sub>{src}候補 {res.candidate_count} 冊から選定{res.notice}</sub>")
        lines.append("")
    return "\n".join(lines)
