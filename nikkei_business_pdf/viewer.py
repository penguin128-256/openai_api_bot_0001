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


def scope(vpage, vcfg: dict):
    """紙面が iframe の中にある場合は、その iframe の中を対象にする(frame_selector)。"""
    fs = vcfg.get("frame_selector", "")
    return vpage.frame_locator(fs).first if fs else vpage


def focus_frame(vpage, vcfg: dict) -> None:
    """キー操作が iframe 内のビューアーに届くよう、iframe にフォーカスを移す。"""
    fs = vcfg.get("frame_selector", "")
    if not fs:
        return
    try:
        handle = vpage.locator(fs).first.element_handle(timeout=5000)
        frame = handle.content_frame() if handle else None
        if frame:
            frame.evaluate("() => { window.focus(); (document.activeElement || document.body).focus?.(); }")
    except Exception:
        pass


def shoot(vpage, vcfg: dict) -> bytes:
    sel = vcfg.get("page_selector", "")
    fs = vcfg.get("frame_selector", "")
    if sel:
        loc = scope(vpage, vcfg).locator(sel).first
        try:
            return loc.screenshot(type="png", timeout=5000)
        except Exception:
            pass  # 見つからなければ下の撮り方にフォールバック
    if fs and vpage.locator(fs).count():
        return vpage.locator(fs).first.screenshot(type="png")
    return vpage.screenshot(type="png")


def do_action(vpage, action: str, vcfg: dict | None = None) -> None:
    vcfg = vcfg or {}
    kind, _, arg = action.partition(":")
    if kind == "key":
        focus_frame(vpage, vcfg)
        vpage.keyboard.press(arg)
    elif kind == "click":
        scope(vpage, vcfg).locator(arg).first.click(timeout=3000)
    elif kind == "wait":  # 例 "wait:2000"
        vpage.wait_for_timeout(int(arg))
    elif kind == "clickxy":  # 画面上の割合 例 "clickxy:0.95,0.5"(右端をクリック)
        fx, fy = (float(v) for v in arg.split(","))
        size = vpage.viewport_size
        vpage.mouse.click(size["width"] * fx, size["height"] * fy)


def capture_viewer(vpage, vcfg: dict, limit: int | None = None) -> list[bytes]:
    """ページを撮影しながら最後のページまで進め、撮影画像(PNG)の一覧を返す。"""
    vpage.bring_to_front()
    wait_settled(vpage, vcfg)
    for action in vcfg.get("before_actions", []):  # 例: 単ページ表示への切り替え
        do_action(vpage, action, vcfg)
        wait_settled(vpage, vcfg)
    vpage.mouse.move(1, 1)  # 操作バーなどを隠す
    shots = [shoot(vpage, vcfg)]
    hashes = [hashlib.sha1(shots[0]).hexdigest()]
    actions = list(vcfg.get("next_actions", ["key:ArrowLeft", "key:ArrowRight"]))
    working: str | None = None
    max_pages = min(limit or 10**9, vcfg.get("max_pages", 400))
    while len(shots) < max_pages:
        moved = False
        for action in ([working] if working else actions):
            try:
                do_action(vpage, action, vcfg)
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
            if working is None:
                log(f"  ページめくりの操作: {action}")
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


DEBUG_JS = """() => {
    const desc = e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '')
        + (typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\\s+/).join('.') : '');
    const box = e => { const r = e.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; };
    return {
        url: location.href, title: document.title,
        iframes: [...document.querySelectorAll('iframe')].map(f => ({sel: desc(f), src: f.src, box: box(f)})),
        canvases: [...document.querySelectorAll('canvas')].map(c => ({sel: desc(c), box: box(c), size: [c.width, c.height]})),
        images: [...document.querySelectorAll('img')].filter(i => i.offsetWidth > 200)
            .slice(0, 20).map(i => ({sel: desc(i), box: box(i), natural: [i.naturalWidth, i.naturalHeight],
                                     src: (i.currentSrc || i.src).slice(0, 80)})),
        big: [...document.querySelectorAll('div,section,main,figure,svg')]
            .filter(e => e.offsetWidth > 300 && e.offsetHeight > 300).slice(0, 40).map(e => ({sel: desc(e), box: box(e)})),
        controls: [...document.querySelectorAll('button,[role=button],a,[onclick],input,select')].slice(0, 120)
            .map(b => ({sel: desc(b), box: box(b),
                        label: (b.getAttribute('aria-label') || b.getAttribute('title') || b.innerText || b.value || '').trim().slice(0, 20)})),
    };
}"""


def save_debug(vpage, debug_dir: Path) -> None:
    """ビューアーがうまく撮れないときの調査用に、画面とページ構造(iframe の中も含む)を保存する。
    ページ構造には要素のクラス名・位置・ボタンの短いラベルだけを記録し、本文は保存しない。"""
    import json

    debug_dir.mkdir(parents=True, exist_ok=True)
    size = vpage.viewport_size
    vpage.mouse.move(1, 1)
    vpage.wait_for_timeout(1500)
    vpage.screenshot(path=str(debug_dir / "viewer.png"))
    # 画面中央にマウスを置いたとき(操作バーが出るタイプか確認する用)
    vpage.mouse.move(size["width"] / 2, size["height"] / 2)
    vpage.wait_for_timeout(1000)
    vpage.screenshot(path=str(debug_dir / "viewer_hover.png"))
    vpage.mouse.move(size["width"] / 2, size["height"] - 5)
    vpage.wait_for_timeout(1000)
    vpage.screenshot(path=str(debug_dir / "viewer_hover_bottom.png"))
    frames = []
    for fr in vpage.frames:
        try:
            frames.append(fr.evaluate(DEBUG_JS))
        except Exception as e:
            frames.append({"url": fr.url, "error": str(e)[:200]})
    info = {"viewport": size, "frames": frames}
    (debug_dir / "viewer.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"調査用の情報を保存しました: {debug_dir}(viewer.png / viewer_hover*.png / viewer.json)")
