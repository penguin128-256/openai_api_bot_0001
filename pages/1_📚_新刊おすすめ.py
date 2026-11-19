from datetime import date

import streamlit as st

from book_recommender.genres import GENRES
from book_recommender.service import make_clients, recommend_for_genres, shift_month

st.set_page_config(page_title="新刊おすすめ", page_icon="📚", layout="wide")
st.title("📚 今月の新刊おすすめ")
st.caption("楽天ブックスの新刊情報から、あなたの好みに合う本をAIがジャンルごとに選びます。")

today = date.today()
month_options = [shift_month(today, d) for d in (1, 0, -1, -2)]
default_index = 1  # 今月

with st.sidebar:
    st.header("条件")
    year, month = st.selectbox(
        "対象月",
        month_options,
        index=default_index,
        format_func=lambda ym: f"{ym[0]}年{ym[1]}月",
    )
    selected = st.multiselect(
        "ジャンル",
        GENRES,
        default=GENRES[:2],
        format_func=lambda g: g.label,
    )
    top_n = st.slider("ジャンルごとの冊数", 1, 10, 5)
    preferences = st.text_area(
        "あなたの好み（任意）",
        value=st.session_state.get("preferences", ""),
        placeholder="例: 東野圭吾や伊坂幸太郎が好き。ビジネス書は組織づくり・マーケティングに興味あり。自己啓発は苦手。",
        height=150,
    )
    st.session_state["preferences"] = preferences
    run = st.button("おすすめを探す", type="primary", width="stretch")


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def cached_recommend(year: int, month: int, genre_keys: tuple, preferences: str, top_n: int):
    genres = [g for g in GENRES if g.key in genre_keys]
    rakuten, recommender = make_clients()
    return recommend_for_genres(rakuten, recommender, genres, year, month, preferences, top_n)


if run:
    if not selected:
        st.warning("ジャンルを1つ以上選んでください。")
        st.stop()
    try:
        with st.spinner("新刊を集めて、おすすめを選んでいます…（ジャンルあたり20〜40秒ほど）"):
            st.session_state["results"] = cached_recommend(
                year, month, tuple(g.key for g in selected), preferences, top_n
            )
        st.session_state["results_month"] = (year, month)
    except Exception as e:  # APIキー未設定・通信エラーなど
        st.error(f"おすすめの取得に失敗しました: {e}")
        st.stop()

results = st.session_state.get("results")
if not results:
    st.info("左の条件を設定して「おすすめを探す」を押してください。")
    st.stop()

ry, rm = st.session_state["results_month"]
st.subheader(f"{ry}年{rm}月の新刊から")
tabs = st.tabs([r.genre.label for r in results])
for tab, res in zip(tabs, results):
    with tab:
        if res.summary:
            st.markdown(f"_{res.summary}_")
        st.caption(f"候補 {res.candidate_count} 冊から選定")
        if not res.recommendations:
            st.write("おすすめできる新刊が見つかりませんでした。")
        for i, rec in enumerate(res.recommendations, 1):
            b = rec.book
            with st.container(border=True):
                img, body = st.columns([1, 5])
                if b.image_url:
                    img.image(b.image_url, width="stretch")
                title = f"[{b.title}]({b.item_url})" if b.item_url else b.title
                body.markdown(f"#### {i}. {title}")
                meta = f"{b.author} ／ {b.publisher} ／ {b.sales_date} ／ {b.price:,}円"
                if rec.subgenre:
                    meta = f"`{rec.subgenre}`　" + meta
                body.markdown(meta)
                body.write(rec.reason)
                if rec.who_for:
                    body.markdown(f"**こんな人に**: {rec.who_for}")
