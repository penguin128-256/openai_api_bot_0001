#!/usr/bin/env python3
"""日経ビジネス電子版の最新号をPDF化して OneDrive に保存するツール。

個人の有料購読者が、自分の契約の範囲で「自分だけがオフラインで読む」ためのツールです。
生成したPDFを他人と共有・配布しないでください(著作権法・日経IDの利用規約に反します)。

使い方:
    python nb2pdf.py login            # 初回のみ: ブラウザが開くので日経IDでログイン
    python nb2pdf.py run              # 最新号をPDF化して保存(処理済みの号はスキップ)
    python nb2pdf.py run --issue-url URL   # 号を指定して実行
    python nb2pdf.py run --force      # 処理済みでも作り直す
    python nb2pdf.py list             # 号ページから見つかった記事一覧を表示(動作確認用)
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import tempfile
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

BASE_DIR = Path(__file__).resolve().parent
STATE_DIR = BASE_DIR / ".state"
SESSION_FILE = STATE_DIR / "nikkei_session.json"
HISTORY_FILE = STATE_DIR / "history.json"
LOGIN_URL = "https://business.nikkei.com/"


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def load_config(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"設定ファイルがありません: {path}\n"
                 f"config.example.toml を config.toml にコピーして編集してください。")
    with path.open("rb") as f:
        return tomllib.load(f)


# ---------------------------------------------------------------- 記事の収集

@dataclass
class Article:
    url: str
    title: str
    section: str = ""


def normalize_url(url: str) -> str:
    """クエリ・フラグメントを落として記事URLを正規化する。"""
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))


DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")


def parse_issue_date(text: str) -> str | None:
    """「2026年11月23日号」のような文字列から YYYYMMDD を取り出す(合併号は最初の日付)。"""
    m = DATE_RE.search(text or "")
    if not m:
        return None
    return f"{int(m.group(1)):04d}{int(m.group(2)):02d}{int(m.group(3)):02d}"


def find_latest_issue(page, cfg: dict) -> tuple[str, str]:
    """バックナンバー一覧から最新号の目次URLと日付(YYYYMMDD)を返す。"""
    nk = cfg["nikkei"]
    page.goto(nk["magazine_url"], wait_until="domcontentloaded")
    page.wait_for_timeout(nk.get("wait_ms", 1500))
    pattern = re.compile(nk["issue_link_pattern"])
    best: tuple[int, str, str] | None = None  # (号番号, URL, リンク文字列)
    links = page.eval_on_selector_all(
        "a[href]", "els => els.map(e => [e.href, e.innerText.trim()])")
    for href, text in links:
        m = pattern.search(href)
        if m and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), normalize_url(href), text)
    if best is None:
        sys.exit("最新号のリンクが見つかりませんでした。config.toml の issue_link_pattern を確認してください。")
    date = parse_issue_date(best[2]) or datetime.now().strftime("%Y%m%d")
    return best[1], date


def collect_articles(page, issue_url: str, cfg: dict) -> tuple[list[Article], str | None]:
    """号の目次ページから記事リンクを紙面の順序で集める。(記事一覧, 号の日付)を返す。"""
    nk = cfg["nikkei"]
    page.goto(issue_url, wait_until="domcontentloaded")
    page.wait_for_timeout(nk.get("wait_ms", 1500))
    date = parse_issue_date(page.evaluate(
        "() => [...document.querySelectorAll('h1')].map(e => e.innerText).join(' ')"))
    # 目次部分(toc_selector)の中だけを見て、各リンクの直前の見出しをセクション名にする
    raw = page.evaluate(
        """([rootSel, headSel]) => {
            const root = (rootSel && document.querySelector(rootSel)) || document.body;
            const out = [];
            let section = "";
            const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
            while (walker.nextNode()) {
                const el = walker.currentNode;
                if (el.matches(headSel) && !el.closest('a')) {
                    section = el.innerText.trim().split('\\n')[0];
                } else if (el.tagName === 'A' && el.href) {
                    out.push({href: el.href, text: el.innerText.trim(), section});
                }
            }
            return out;
        }""",
        [nk.get("toc_selector", ""), nk.get("section_heading_selector", "h2")],
    )
    pattern = re.compile(nk["article_link_pattern"])
    exclude = re.compile(nk["article_exclude_pattern"]) if nk.get("article_exclude_pattern") else None
    seen: dict[str, Article] = {}
    for item in raw:
        if not pattern.search(item["href"]) or (exclude and exclude.search(item["href"])):
            continue
        url = normalize_url(item["href"])
        title = re.sub(r"\s+", " ", item["text"]).strip()
        if url in seen:
            if len(title) > len(seen[url].title):  # より長いリンク文字列をタイトルに
                seen[url].title = title
            continue
        seen[url] = Article(url=url, title=title, section=item["section"])
    return list(seen.values())[: nk.get("max_articles", 150)], date


# ---------------------------------------------------------------- PDF化

def print_css(cfg: dict) -> str:
    nk, pdf = cfg["nikkei"], cfg["pdf"]
    hide = ",".join(nk.get("hide_selectors", []))
    scale = pdf.get("font_scale", 1.0)
    rules = f"""
        html {{ font-size: {scale * 100:.0f}% !important; }}
        body {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
        img {{ max-width: 100% !important; height: auto !important; page-break-inside: avoid; }}
        p {{ line-height: 1.8 !important; }}
        * {{ position: static !important; }}
    """
    if hide:
        rules += f"{hide} {{ display: none !important; }}"
    return rules


def scroll_to_bottom(page) -> None:
    """遅延読み込み画像を読み込ませるため、ページ末尾までスクロールする。"""
    page.evaluate(
        """async () => {
            for (let y = 0; y < document.body.scrollHeight; y += 600) {
                window.scrollTo(0, y);
                await new Promise(r => setTimeout(r, 80));
            }
            window.scrollTo(0, 0);
        }"""
    )


def render_page(page, url: str, out: Path, cfg: dict) -> tuple[str, list[str]]:
    """1ページをPDF化し、(ページタイトル, 次ページURL一覧)を返す。"""
    nk, pdf = cfg["nikkei"], cfg["pdf"]
    page.goto(url, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(nk.get("wait_ms", 1500))
    scroll_to_bottom(page)
    title = page.evaluate(
        "() => (document.querySelector('h1')?.innerText || document.title || '').trim()"
    )
    title = re.sub(r"[：:|｜]\s*日経ビジネス電子版\s*$", "", title)
    # 同じ記事の続きページ(?P=2 など)を探す
    next_pat = re.compile(nk.get("next_page_pattern", r"[?&]P=(\d+)"))
    base = normalize_url(url)
    nexts = []
    for href in page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)"):
        if normalize_url(href) == base and next_pat.search(href):
            nexts.append(href.split("#")[0])

    # 本文だけを取り出して、読みやすいレイアウトで組み直す(リーダー表示)
    body = extract_article_html(page, cfg)
    if body:
        page.set_content(reader_html(body, url, cfg), wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=20000)  # 画像の読み込み待ち
        except Exception:
            pass
    else:  # 本文が見つからない場合はページ全体を印刷用CSSで出力
        page.add_style_tag(content=print_css(cfg))
    m = f"{pdf.get('margin_mm', 12)}mm"
    page.pdf(
        path=str(out),
        format=pdf.get("format", "A4"),
        print_background=True,
        margin={"top": m, "bottom": m, "left": m, "right": m},
    )
    return title, nexts


def extract_article_html(page, cfg: dict) -> str:
    """記事ページから、見出し・メタ情報・本文などの要素(article_selectors)だけを取り出す。"""
    nk = cfg["nikkei"]
    return page.evaluate(
        """([sels, removeSels]) => {
            const parts = [], originals = [];
            for (const sel of sels) {
                for (const el of document.querySelectorAll(sel)) {
                    if (originals.some(o => o.contains(el))) continue;  // 取り出し済み要素の中身は重複させない
                    originals.push(el);
                    const c = el.cloneNode(true);
                    // 遅延読み込み画像の実URLを src に入れ、URLを絶対パスにする
                    c.querySelectorAll('img').forEach(img => {
                        const real = img.dataset.src || img.dataset.original || img.getAttribute('src');
                        if (real) img.setAttribute('src', new URL(real, location.href).href);
                        img.removeAttribute('srcset'); img.removeAttribute('loading');
                    });
                    c.querySelectorAll('source').forEach(s => s.remove());
                    if (removeSels) c.querySelectorAll(removeSels).forEach(x => x.remove());
                    c.dataset.part = sel;
                    parts.push(c);
                }
            }
            // 本文(最後のセレクタ)が無ければ失敗扱い
            if (!parts.some(p => p.dataset.part === sels[sels.length - 1])) return "";
            return parts.map(p => p.outerHTML).join("\\n");
        }""",
        [nk.get("article_selectors", []), ",".join(nk.get("article_remove_selectors", []))],
    ) if nk.get("article_selectors") else ""


def reader_html(body: str, url: str, cfg: dict) -> str:
    scale = cfg["pdf"].get("font_scale", 1.0)
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<base href="{html.escape(url)}"><style>
  html {{ font-size: {11 * scale:.1f}pt; }}
  body {{ font-family: 'Hiragino Mincho ProN', 'Noto Serif CJK JP', 'Yu Mincho', serif;
         line-height: 1.85; color: #111; margin: 0; }}
  h1 {{ font-family: 'Hiragino Sans', 'Noto Sans CJK JP', sans-serif; font-size: 1.9em;
        line-height: 1.35; margin: .2em 0 .4em; }}
  h2, h3, h4 {{ font-family: 'Hiragino Sans', 'Noto Sans CJK JP', sans-serif; line-height: 1.4;
               margin: 1.4em 0 .5em; page-break-after: avoid; }}
  p {{ margin: 0 0 .9em; text-align: justify; }}
  a {{ color: inherit; text-decoration: none; }}
  img {{ max-width: 100%; height: auto; display: block; margin: .6em auto; page-break-inside: avoid; }}
  figure {{ margin: 1em 0; page-break-inside: avoid; }}
  figcaption, small, .caption {{ font-size: .8em; color: #555; line-height: 1.5; }}
  ul, ol {{ padding-left: 1.4em; }}
  table {{ border-collapse: collapse; font-size: .9em; }} td, th {{ border: 1px solid #ccc; padding: 2px 6px; }}
  [data-part*="parentTitle"] {{ font-size: .9em; color: #c00; font-weight: bold; margin: 0; }}
  [data-part*="meta"] {{ font-size: .8em; color: #555; list-style: none; padding: 0; margin: 0 0 1em; }}
  [data-part*="meta"] li {{ display: inline; margin-right: 1em; }}
  [data-part*="meta"] img {{ display: none; }}
  .source-url {{ font-size: .7em; color: #888; margin-top: 2em; border-top: 1px solid #ddd; padding-top: .4em; }}
</style></head><body>
{body}
<div class="source-url">出典: {html.escape(url)}</div>
</body></html>"""


def page_num(url: str, cfg: dict) -> int:
    m = re.search(cfg["nikkei"].get("next_page_pattern", r"[?&]P=(\d+)"), url)
    return int(m.group(1)) if m else 1


def render_article(page, art: Article, workdir: Path, idx: int, cfg: dict) -> list[Path]:
    """記事(複数ページ含む)をPDF化し、ページ順のPDFファイル一覧を返す。"""
    files: list[Path] = []
    todo, done = [art.url], set()
    interval = cfg["nikkei"].get("request_interval_sec", 3)
    while todo:
        url = todo.pop(0)
        key = (normalize_url(url), page_num(url, cfg))
        if key in done:
            continue
        done.add(key)
        out = workdir / f"{idx:03d}_{key[1]:02d}.pdf"
        title, nexts = render_page(page, url, out, cfg)
        if key[1] == 1 and title:
            art.title = title
        files.append(out)
        todo.extend(n for n in nexts if (normalize_url(n), page_num(n, cfg)) not in done)
        todo.sort(key=lambda u: page_num(u, cfg))
        time.sleep(interval)
    return sorted(files)


def is_paywalled(page, cfg: dict) -> bool:
    sel = cfg["nikkei"].get("paywall_selector", "")
    return bool(sel) and page.query_selector(sel) is not None


def render_toc(page, issue_date: str, articles: list[Article], out: Path, cfg: dict) -> None:
    rows, current = [], None
    for i, a in enumerate(articles, 1):
        if a.section and a.section != current:
            current = a.section
            rows.append(f"<h2>{html.escape(a.section)}</h2>")
        rows.append(f"<div class='row'><span class='n'>{i}</span>{html.escape(a.title)}</div>")
    d = datetime.strptime(issue_date, "%Y%m%d")
    doc = f"""<!doctype html><html lang="ja"><meta charset="utf-8"><style>
        body {{ font-family: 'Hiragino Sans', 'Noto Sans JP', 'Yu Gothic', sans-serif; }}
        h1 {{ font-size: 28pt; border-bottom: 3px solid #333; padding-bottom: 8px; }}
        h2 {{ font-size: 13pt; margin: 18px 0 6px; color: #555; }}
        .row {{ font-size: 12pt; padding: 4px 0; border-bottom: 1px solid #ddd; }}
        .n {{ display: inline-block; width: 2.5em; color: #888; }}
    </style><h1>日経ビジネス {d.year}年{d.month}月{d.day}日号</h1>{''.join(rows)}</html>"""
    page.set_content(doc)
    m = f"{cfg['pdf'].get('margin_mm', 12)}mm"
    page.pdf(path=str(out), format=cfg["pdf"].get("format", "A4"),
             margin={"top": m, "bottom": m, "left": m, "right": m})


def merge_pdfs(toc: Path, parts: list[tuple[Article, list[Path]]], out: Path, title: str) -> None:
    """目次と各記事を1つのPDFにまとめ、記事ごとのしおり(ブックマーク)を付ける。"""
    from pypdf import PdfReader, PdfWriter

    w = PdfWriter()
    w.append(PdfReader(toc))
    w.add_outline_item("目次", 0)
    section_marks: dict[str, object] = {}
    for art, files in parts:
        start = len(w.pages)
        for f in files:
            w.append(PdfReader(f))
        parent = None
        if art.section:
            if art.section not in section_marks:
                section_marks[art.section] = w.add_outline_item(art.section, start)
            parent = section_marks[art.section]
        w.add_outline_item(art.title or art.url, start, parent=parent)
    w.add_metadata({"/Title": title, "/Author": "日経ビジネス"})
    w.page_mode = "/UseOutlines"  # 開いたときにしおりを表示
    with out.open("wb") as f:
        w.write(f)


# ---------------------------------------------------------------- 保存先

def save_output(pdf_path: Path, filename: str, cfg: dict) -> str:
    out = cfg["output"]
    if out.get("mode", "folder") == "graph":
        import onedrive
        return onedrive.upload(pdf_path, f"{out.get('graph_folder', '日経ビジネス')}/{filename}",
                               client_id=out["graph_client_id"],
                               tenant=out.get("graph_tenant", "consumers"),
                               cache_file=STATE_DIR / "msal_cache.json")
    dest_dir = Path(out["folder"]).expanduser()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    dest.write_bytes(pdf_path.read_bytes())
    return str(dest)


def load_history() -> dict:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return {}


def save_history(h: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(h, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- コマンド

def new_context(p, headless: bool = True):
    exe = os.environ.get("NB2PDF_CHROMIUM")  # 任意: 使用するChromiumのパス
    browser = p.chromium.launch(headless=headless, executable_path=exe or None)
    kw = {"locale": "ja-JP", "viewport": {"width": 1100, "height": 1400}}
    if SESSION_FILE.exists():
        kw["storage_state"] = str(SESSION_FILE)
    return browser, browser.new_context(**kw)


def cmd_login(args, cfg) -> None:
    from playwright.sync_api import sync_playwright

    STATE_DIR.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser, ctx = new_context(p, headless=False)
        page = ctx.new_page()
        page.goto(LOGIN_URL)
        print("\n開いたブラウザで日経IDにログインしてください。")
        input("ログインが完了したら、ここで Enter キーを押してください... ")
        ctx.storage_state(path=str(SESSION_FILE))
        SESSION_FILE.chmod(0o600)
        browser.close()
    print(f"ログイン情報を保存しました: {SESSION_FILE}")


def cmd_list(args, cfg) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, ctx = new_context(p)
        page = ctx.new_page()
        issue_url, date = (args.issue_url, args.date) if args.issue_url \
            else find_latest_issue(page, cfg)
        print(f"号: {date}  {issue_url}")
        articles, d2 = collect_articles(page, issue_url, cfg)
        print(f"号の日付(目次ページより): {d2}")
        for i, a in enumerate(articles, 1):
            print(f"{i:3d}. [{a.section}] {a.title}\n     {a.url}")
        browser.close()


def cmd_run(args, cfg) -> None:
    from playwright.sync_api import sync_playwright

    if not SESSION_FILE.exists() and not args.no_login:
        sys.exit("ログイン情報がありません。先に `python nb2pdf.py login` を実行してください。")
    history = load_history()
    with sync_playwright() as p:
        browser, ctx = new_context(p)
        page = ctx.new_page()
        if args.issue_url:
            issue_url, date = args.issue_url, args.date
        else:
            issue_url, date = find_latest_issue(page, cfg)
        if date and date in history and not args.force:
            log(f"{date}号は処理済みです({history[date]['saved_to']})。--force で作り直せます。")
            browser.close()
            return

        articles, toc_date = collect_articles(page, issue_url, cfg)
        date = date or toc_date or datetime.now().strftime("%Y%m%d")
        log(f"対象の号: {date}  {issue_url}")
        if date in history and not args.force:
            log(f"{date}号は処理済みです({history[date]['saved_to']})。--force で作り直せます。")
            browser.close()
            return
        if not articles:
            browser.close()
            sys.exit("記事が見つかりませんでした。config.toml の article_link_pattern を確認してください。")
        log(f"{len(articles)} 本の記事を見つけました。")
        if args.limit:
            articles = articles[: args.limit]
            log(f"--limit 指定により先頭 {len(articles)} 本だけ処理します(お試し用。履歴には記録しません)。")

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            parts, warned = [], False
            for i, art in enumerate(articles, 1):
                log(f"({i}/{len(articles)}) {art.title[:40]}")
                try:
                    files = render_article(page, art, work, i, cfg)
                    if not warned and is_paywalled(page, cfg):
                        warned = True
                        log("⚠ 有料記事の続きが表示されていない可能性があります。"
                            "`python nb2pdf.py login` で再ログインしてください。")
                    parts.append((art, files))
                except Exception as e:  # 1本失敗しても全体は続行
                    log(f"  失敗しました: {e}")
            toc = work / "000_toc.pdf"
            render_toc(page, date, [a for a, _ in parts], toc, cfg)
            # ログイン状態(Cookie)を更新して保存しておく
            ctx.storage_state(path=str(SESSION_FILE))
            browser.close()

            filename = f"日経ビジネス_{date}.pdf"
            merged = work / filename
            merge_pdfs(toc, parts, merged, filename.removesuffix(".pdf"))
            saved = save_output(merged, filename, cfg)

    if args.limit:
        log(f"完了(お試し): {saved}")
        return
    history[date] = {"issue_url": issue_url, "articles": len(parts),
                     "saved_to": saved, "created_at": datetime.now().isoformat(timespec="seconds")}
    save_history(history)
    log(f"完了: {saved}")


def main() -> None:
    ap = argparse.ArgumentParser(description="日経ビジネス最新号をPDF化してOneDriveに保存")
    ap.add_argument("--config", type=Path, default=BASE_DIR / "config.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="日経IDでログインしてセッションを保存")
    for name in ("run", "list"):
        sp = sub.add_parser(name)
        sp.add_argument("--issue-url", help="最新号ではなく、この号ページを処理する")
        sp.add_argument("--date", help="号の日付 YYYYMMDD(--issue-url 指定時のファイル名用)")
        if name == "run":
            sp.add_argument("--force", action="store_true", help="処理済みの号も作り直す")
            sp.add_argument("--limit", type=int, help="先頭のN本だけ処理する(動作確認用)")
            sp.add_argument("--no-login", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    cfg = load_config(args.config)
    {"login": cmd_login, "run": cmd_run, "list": cmd_list}[args.cmd](args, cfg)


if __name__ == "__main__":
    main()
