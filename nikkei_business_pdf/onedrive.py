"""Microsoft Graph API で OneDrive にファイルをアップロードする(output.mode = "graph" 用)。

初回はデバイスコード認証(表示されたURLを開いてコードを入力)を行い、
以降はトークンキャッシュを使って自動でアップロードします。
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import msal
import requests

SCOPES = ["Files.ReadWrite"]
GRAPH = "https://graph.microsoft.com/v1.0"
CHUNK = 10 * 320 * 1024  # 3.2MB(320KiBの倍数である必要がある)


def get_token(client_id: str, tenant: str, cache_file: Path) -> str:
    if not client_id:
        raise SystemExit("config.toml の output.graph_client_id を設定してください(README参照)。")
    cache = msal.SerializableTokenCache()
    if cache_file.exists():
        cache.deserialize(cache_file.read_text())
    app = msal.PublicClientApplication(
        client_id, authority=f"https://login.microsoftonline.com/{tenant}", token_cache=cache)
    result = None
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
    if not result:
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise SystemExit(f"認証を開始できませんでした: {flow}")
        print(flow["message"], flush=True)  # 「https://microsoft.com/devicelogin を開いてコード XXX を入力」
        result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise SystemExit(f"OneDrive の認証に失敗しました: {result.get('error_description')}")
    if cache.has_state_changed:
        cache_file.parent.mkdir(exist_ok=True)
        cache_file.write_text(cache.serialize())
        cache_file.chmod(0o600)
    return result["access_token"]


def upload(local: Path, remote_path: str, *, client_id: str, tenant: str, cache_file: Path) -> str:
    token = get_token(client_id, tenant, cache_file)
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.post(
        f"{GRAPH}/me/drive/root:/{quote(remote_path)}:/createUploadSession",
        headers=headers,
        json={"item": {"@microsoft.graph.conflictBehavior": "replace"}},
        timeout=60,
    )
    r.raise_for_status()
    upload_url = r.json()["uploadUrl"]
    size = local.stat().st_size
    with local.open("rb") as f:
        start = 0
        while start < size:
            data = f.read(CHUNK)
            end = start + len(data) - 1
            resp = requests.put(upload_url, data=data, timeout=300, headers={
                "Content-Length": str(len(data)),
                "Content-Range": f"bytes {start}-{end}/{size}",
            })
            resp.raise_for_status()
            start = end + 1
    item = resp.json()
    return item.get("webUrl", f"OneDrive:/{remote_path}")
