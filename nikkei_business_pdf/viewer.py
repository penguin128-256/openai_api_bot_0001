"""誌面ビューアーに表示された紙面を、表示されたままの見た目で1ページずつ撮影してPDFにする。

ログイン済みのブラウザで誌面ビューアーを開き、
「画面を撮影 → 次のページへ」を、ページが変わらなくなるまで繰り返します。
画面に表示されたものを撮影するだけで、ビューアーの保護機能を回避する処理はしていません。
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path


def log(msg: str) -> None:
    from nb2pdf import log as _log
    _log(msg)


def open_viewer(ctx, page, issue_url: str, vcfg: dict):
    """号の目次ページから誌面ビューアーを開き、ビューアーのページを返す。"""
    if vcfg.get("viewer_url"):
        page.goto(vcfg["viewer_url"], wait_until="domcontentloaded")
        return page
    page.goto(issue_url, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    btn = page.locator(vcfg.get("open_button_selector", ".c-viewerLink")).first
    if btn.count() == 0:
        raise SystemExit("「誌面ビューアーで読む」ボタンが見つかりません(open_button_selector を確認)。")
    # 新しいタブで開く場合と、同じタブ/モーダル内で開く場合の両方に対応
    try:
        with ctx.expect_page(timeout=15000) as new:
            btn.click()
        vpage = new.value
    except Exception:
        vpage = page
    vpage.wait_for_load_state("domcontentloaded")
    # 未ログイン時は有料会員向けの案内モーダルが出る
    if vpage is page and page.locator(".l-modal.-viewerPaywall").is_visible():
        raise SystemExit("誌面ビューアーを開けません。ログインが切れています。`python nb2pdf.py login` を実行してください。")
    log(f"誌面ビューアー: {vpage.url}")
    return vpage


def wait_settled(vpage, vcfg: dict) -> None:
    try:
        vpage.wait_for_load_state("networkidle", timeout=vcfg.get("page_timeout_ms", 15000))
    except Exception:
        pass
    vpage.wait_for_timeout(vcfg.get("page_wait_ms", 1500))


def shoot(vpage, vcfg: dict) -> bytes:
    sel = vcfg.get("page_selector", "")
    if sel and vpage.locator(sel).count():
        return vpage.locator(sel).first.screenshot(type="png")
    return vpage.screenshot(type="png")


def do_action(vpage, action: str) -> None:
    kind, _, arg = action.partition(":")
    if kind == "key":
        vpage.keyboard.press(arg)
    elif kind == "click":
        vpage.locator(arg).first.click(timeout=3000)
    elif kind == "clickxy":  # 画面上の割合 例 "clickxy:0.95,0.5"(右端をクリック)
        fx, fy = (float(v) for v in arg.split(","))
        size = vpage.viewport_size
        vpage.mouse.click(size["width"] * fx, size["height"] * fy)


def capture_viewer(vpage, vcfg: dict) -> list[bytes]:
    """ページを撮影しながら最後のページまで進め、撮影画像(PNG)の一覧を返す。"""
    vpage.bring_to_front()
    wait_settled(vpage, vcfg)
    for action in vcfg.get("before_actions", []):  # 例: 単ページ表示への切り替え
        do_action(vpage, action)
        wait_settled(vpage, vcfg)
    vpage.mouse.move(1, 1)  # 操作バーなどを隠す
    shots = [shoot(vpage, vcfg)]
    hashes = [hashlib.sha1(shots[0]).hexdigest()]
    actions = list(vcfg.get("next_actions", ["key:ArrowLeft", "key:ArrowRight"]))
    working: str | None = None
    while len(shots) < vcfg.get("max_pages", 400):
        moved = False
        for action in ([working] if working else actions):
            try:
                do_action(vpage, action)
            except Exception:
                continue
            wait_settled(vpage, vcfg)
            vpage.mouse.move(1, 1)
            img = shoot(vpage, vcfg)
            h = hashlib.sha1(img).hexdigest()
            if h == hashes[-1]:
                continue  # 変化なし → 別の操作を試す / 最終ページ
            if h in hashes:  # 一度見たページに戻った(先頭に戻るタイプのビューアー)
                return shots
            working = action
            shots.append(img)
            hashes.append(h)
            moved = True
            if len(shots) % 10 == 0:
                log(f"  {len(shots)} ページ撮影")
            break
        if not moved:
            break
    if working is None and len(shots) == 1:
        log("⚠ ページをめくれませんでした。config.toml の [viewer] next_actions を確認してください。")
    return shots


def images_to_pdf(shots: list[bytes], out: Path, vcfg: dict) -> None:
    from PIL import Image

    quality = vcfg.get("jpeg_quality", 85)
    pages = []
    for raw in shots:
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality)  # PNGのままだと巨大になるのでJPEGに
        pages.append(Image.open(io.BytesIO(buf.getvalue())))
    pages[0].save(out, "PDF", save_all=True, append_images=pages[1:], resolution=144)


def save_debug(vpage, debug_dir: Path) -> None:
    """ビューアーがうまく撮れないときの調査用に、画面とページ構造を保存する。"""
    debug_dir.mkdir(parents=True, exist_ok=True)
    vpage.screenshot(path=str(debug_dir / "viewer.png"))
    info = vpage.evaluate(
        """() => ({url: location.href, title: document.title,
            frames: [...document.querySelectorAll('iframe')].map(f => f.src),
            canvases: document.querySelectorAll('canvas').length,
            buttons: [...document.querySelectorAll('button,[role=button],a')].slice(0, 80)
                .map(b => (b.className || '') + ' | ' + (b.getAttribute('aria-label') || b.innerText || '').trim().slice(0, 20)),
            big: [...document.querySelectorAll('img,canvas,div')].filter(e => e.offsetWidth > 300 && e.offsetHeight > 300)
                .slice(0, 30).map(e => e.tagName + '.' + (e.className || '') + ' ' + e.offsetWidth + 'x' + e.offsetHeight)})"""
    )
    import json
    (debug_dir / "viewer.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"調査用の情報を保存しました: {debug_dir}")
