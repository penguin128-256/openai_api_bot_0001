# openai_api_bot_0001

OpenAI API を使った Streamlit アプリです。

- **My AI Assistant**（`app.py`）: チャットボット
- **📚 新刊おすすめ**（`pages/1_📚_新刊おすすめ.py`）: 指定した月の新刊を楽天ブックスから取得し、
  あなたの好みに合わせて AI がジャンルごとにおすすめを選び、理由を添えて紹介します。
- **月次レポート**（`monthly_report.py` + GitHub Actions）: 毎月自動でおすすめを作り、GitHub Issue で届けます。

## 仕組み

1. 楽天ブックス書籍検索API で、ジャンルごとに発売日の新しい順に新刊を取得し、対象月の本だけ残す
2. 内容紹介のある本・レビューの多い本を優先して最大60冊に絞り込む
3. OpenAI に「読者の好み」と候補リストを渡し、おすすめを選んでもらう
   - AI は候補リストの番号で本を指定し、リストにない本は採用しない（架空の本が混ざらないようにするため）

ジャンルは `book_recommender/genres.py` で定義しています（ビジネス・経済／小説・エッセイ／人文・思想・社会／科学・技術）。

## 準備

### 1. 楽天ウェブサービスのアプリIDを取得（無料）

https://webservice.rakuten.co.jp/ でアプリを登録し、アプリケーションIDを控えます。

### 2. Secrets を設定

Streamlit Community Cloud の「Secrets」（ローカルでは `.streamlit/secrets.toml`）:

```toml
[OpenAIAPI]
openai_api_key = "sk-..."
# model = "gpt-4o-mini"   # 任意

[RakutenAPI]
application_id = "楽天のアプリケーションID"
# endpoint = "https://app.rakuten.co.jp/services/api/BooksBook/Search/20170404"  # 変更があった場合のみ
```

環境変数 `OPENAI_API_KEY` / `OPENAI_MODEL` / `RAKUTEN_APP_ID` / `RAKUTEN_ENDPOINT` でも指定できます。

### 3. 起動

```bash
pip install -r requirements.txt
streamlit run app.py
```

左のメニューから「📚 新刊おすすめ」を開き、対象月・ジャンル・好みを入力して「おすすめを探す」を押します。
楽天APIの利用制限（1秒1リクエスト）を守るため、ジャンルあたり数十秒かかります。結果は12時間キャッシュされます。

## 毎月自動でおすすめを受け取る（GitHub Actions）

`.github/workflows/monthly-books.yml` が毎月3日 9:17（日本時間）に実行され、
レポートを Issue として投稿します。GitHub の通知設定でメールやアプリに届きます。

リポジトリの Settings → Secrets and variables → Actions で以下を登録してください。

| 種類 | 名前 | 内容 |
|---|---|---|
| Secret | `OPENAI_API_KEY` | OpenAI APIキー |
| Secret | `RAKUTEN_APP_ID` | 楽天アプリケーションID |
| Variable | `READING_PREFERENCES` | 好み（任意）。例: 「伊坂幸太郎が好き。ビジネス書は組織論とマーケティング」 |

Actions タブから「Run workflow」で手動実行もできます（対象月を指定可能）。

手元で実行する場合:

```bash
RAKUTEN_APP_ID=... OPENAI_API_KEY=... python monthly_report.py --month 2026-12 --genres business,novel --out report.md
```

## テスト

```bash
pip install pytest
python -m pytest
```
