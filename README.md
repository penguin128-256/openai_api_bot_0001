# openai_api_bot_0001

OpenAI API を使った Streamlit アプリです。

- **My AI Assistant**（`app.py`）: チャットボット
- **📚 新刊おすすめ**（`pages/1_📚_新刊おすすめ.py`）: 指定した月の新刊を国立国会図書館サーチ／楽天ブックスから取得し、
  あなたの好みに合わせて AI がジャンルごとにおすすめを選び、理由を添えて紹介します。
- **月次レポート**（`monthly_report.py` + GitHub Actions）: 毎月自動でおすすめを作り、GitHub Issue で届けます。

## データ取得元

| 取得元 | 登録 | 特徴 |
|---|---|---|
| 国立国会図書館サーチ（NDL Search） | **不要** | ISBN付きの国内刊行書をほぼ網羅。納本後の登録のため発売から数日〜数週間遅れる。内容紹介は openBD（ISBN検索・登録不要）で補完 |
| 楽天ブックス | 要（アプリID＋accessKey） | 予約中・発売直後の本も取れる。2026年のAPI刷新で旧ドメイン `app.rakuten.co.jp` は停止。新しい「バックエンドサービス」型アプリと**許可IP設定**が必要なため、IPが固定でない Streamlit Cloud / GitHub Actions とは相性が悪い |

既定は `auto`（楽天が設定されていれば楽天、失敗したら国会図書館に自動で切り替え）です。
画面のサイドバー、または設定 `[Books] source = "ndl"`（環境変数 `BOOK_SOURCE`）で切り替えられます。

## 仕組み

1. ジャンルごとに対象月の新刊を取得する（国会図書館は NDC＝日本十進分類法、楽天はジャンルIDで絞り込み）
2. 内容紹介のある本・レビューの多い本を優先して最大60冊に絞り込む
3. OpenAI に「読者の好み」と候補リストを渡し、おすすめを選んでもらう
   - AI は候補リストの番号で本を指定し、リストにない本は採用しない（架空の本が混ざらないようにするため）

ジャンルは `book_recommender/genres.py` で定義しています（ビジネス・経済／小説・エッセイ／人文・思想・社会／科学・技術）。

## 準備

### 1. （任意）楽天ウェブサービスのアプリを登録

国会図書館サーチだけで使う場合は不要です。楽天を使う場合は https://webservice.rakuten.co.jp/ で
**バックエンドサービス型**のアプリを新規登録し、アプリケーションID（UUID形式）と accessKey を控え、
呼び出し元サーバーのIPを許可IPに登録します。503 が返る場合はアプリ種別、404 の場合は
接続先URL（`endpoint`）を楽天の最新ドキュメントで確認してください。

### 2. Secrets を設定

Streamlit Community Cloud の「Secrets」（ローカルでは `.streamlit/secrets.toml`）:

```toml
[OpenAIAPI]
openai_api_key = "sk-..."
# model = "gpt-4o-mini"   # 任意

[Books]
source = "auto"   # auto / ndl / rakuten

[RakutenAPI]      # 楽天を使う場合のみ
application_id = "楽天のアプリケーションID"
access_key = "楽天のaccessKey"
# endpoint = "https://openapi.rakuten.co.jp/services/api/BooksBook/Search/20170404"  # 異なる場合のみ
```

環境変数 `OPENAI_API_KEY` / `OPENAI_MODEL` / `BOOK_SOURCE` / `RAKUTEN_APP_ID` / `RAKUTEN_ACCESS_KEY` / `RAKUTEN_ENDPOINT` でも指定できます。

### 3. 起動

```bash
pip install -r requirements.txt
streamlit run app.py
```

左のメニューから「📚 新刊おすすめ」を開き、対象月・ジャンル・好みを入力して「おすすめを探す」を押します。
APIへの負荷を抑えるため1秒1リクエストに制限しており、ジャンルあたり数十秒かかります。結果は12時間キャッシュされます。

## 毎月自動でおすすめを受け取る（GitHub Actions）

`.github/workflows/monthly-books.yml` が毎月15日 9:17（日本時間）に**先月の新刊**を対象に実行され、
レポートを Issue として投稿します。GitHub の通知設定でメールやアプリに届きます。

リポジトリの Settings → Secrets and variables → Actions で以下を登録してください。

| 種類 | 名前 | 内容 |
|---|---|---|
| Secret | `OPENAI_API_KEY` | OpenAI APIキー |
| Variable | `BOOK_SOURCE` | 取得元（省略時 `ndl`。Actions は実行IPが変わるため楽天は非推奨） |
| Secret | `RAKUTEN_APP_ID` / `RAKUTEN_ACCESS_KEY` | 楽天を使う場合のみ |
| Variable | `READING_PREFERENCES` | 好み（任意）。例: 「伊坂幸太郎が好き。ビジネス書は組織論とマーケティング」 |

Actions タブから「Run workflow」で手動実行もできます（対象月を指定可能）。

手元で実行する場合:

```bash
OPENAI_API_KEY=... python monthly_report.py --source ndl --month 2026-10 --genres business,novel --out report.md
```

## テスト

```bash
pip install pytest
python -m pytest
```
