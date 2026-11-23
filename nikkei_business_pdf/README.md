# 日経ビジネス → PDF → OneDrive

日経ビジネス電子版の最新号の記事をまとめて **1冊のPDF**(目次ページ+記事ごとのしおり付き)にし、
OneDrive に保存します。iPad の OneDrive アプリや「ファイル」アプリで「オフラインで使用可能にする」
を有効にすれば、毎号オフラインで読めます。

> ⚠ **個人利用に限ってください。** 日経ビジネス電子版の有料会員が、自分の契約の範囲で
> 自分だけが読むためのツールです。作成したPDFを他人に共有・配布しないでください。
> 自動取得について日経IDの利用規約もご確認ください。アクセス間隔(既定3秒)は短くしないでください。

## しくみ

1. 保存済みの日経IDログイン情報を使い、ブラウザ(Chromium)で「バックナンバー」ページを開き、最新号の目次ページ(`/atcl/NBD/19/mokuji/番号/`)を探す
2. 目次ページの記事リンクを紙面の順番で、特集・連載・時事深層などのセクション名と一緒に集める
3. 各記事から見出し・著者・写真・本文だけを取り出し、読みやすい縦長レイアウト(明朝体、文字大きめ)に組み直してPDF化
4. 目次ページ+全記事を `日経ビジネス_YYYYMMDD.pdf` に結合し、特集・連載などの単位でしおりを付ける
5. OneDrive に保存。処理した号は `.state/history.json` に記録し、次回はスキップ

## セットアップ(Mac / Windows)

Python 3.11 以上が必要です。

```bash
cd nikkei_business_pdf
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cp config.example.toml config.toml # Windows: copy config.example.toml config.toml
```

`config.toml` の `[output] folder` を、自分のPCの OneDrive 同期フォルダ内に変更します。

- Mac: `~/Library/CloudStorage/OneDrive-Personal/日経ビジネス`
- Windows: `~/OneDrive/日経ビジネス`

### 初回ログイン

```bash
python nb2pdf.py login
```

ブラウザが開くので日経IDでログインし、ターミナルに戻って Enter を押します。
ログイン情報は `.state/nikkei_session.json` に保存されます(パスワードは保存しません)。
期限が切れたら、もう一度 `login` を実行してください。

### 実行

```bash
python nb2pdf.py list     # まず記事一覧が正しく取れるか確認
python nb2pdf.py run      # 最新号をPDF化して保存
python nb2pdf.py run --limit 3   # お試し: 先頭3本だけ
python nb2pdf.py run --issue-url https://business.nikkei.com/atcl/NBD/19/mokuji/00396/  # 号を指定
python nb2pdf.py run --force   # 作り直す
```

## 毎号自動で実行する

日経ビジネスは週刊なので、週1回の実行にしています(既定: 土曜 7:15。PCが起動している必要があります)。

- **Mac**: `schedule/com.user.nb2pdf.plist` の `/PATH/TO` を書き換え、ファイル内のコメントの手順で登録
- **Windows**: `schedule/register_windows_task.ps1` を実行
- **Linux**: `crontab -e` に `15 7 * * 6 cd /path/to/nikkei_business_pdf && .venv/bin/python nb2pdf.py run`

## iPad での読み方

1. iPad に OneDrive アプリを入れて同じアカウントでサインイン
2. 「日経ビジネス」フォルダのPDFを長押し →「オフラインで使用可能にする」
   (フォルダごと設定するには Microsoft 365 の契約が必要です)
3. PDFを開くと、左のしおりから記事に移動できます。「ブック」アプリに取り込んでも読めます

## OneDrive アプリがないPCで使う場合(Graph API で直接アップロード)

1. [Azure ポータル](https://portal.azure.com/) →「アプリの登録」→「新規登録」
   - サポートされているアカウントの種類: 「個人用 Microsoft アカウントのみ」(会社/学校アカウントなら適宜)
2. 「認証」→「パブリック クライアント フローを許可する」を **はい**
3. 「API のアクセス許可」に Microsoft Graph の委任された許可 `Files.ReadWrite` を追加
4. `config.toml` で `mode = "graph"`、`graph_client_id` にアプリケーション (クライアント) ID を設定
5. 初回の `run` で表示されるURLを開き、コードを入力してサインイン(以降は自動)

## うまくいかないとき

- **記事が0本 / 違うリンクを拾う**: サイトの構造が変わった可能性があります。`list` で確認し、
  `config.toml` の `issue_link_pattern` / `article_link_pattern` を調整してください
- **記事の途中までしかない**: ログイン切れです。`python nb2pdf.py login` を再実行
- **記事の最後に「有料会員なら…」の案内が出る**: ログインできていません。`login` を再実行
- **余計な要素が残る / 本文が消える**: `article_selectors` / `article_remove_selectors` を調整
- **文字が小さい**: `font_scale` を大きく(例: 1.3)、または `format = "A5"`
