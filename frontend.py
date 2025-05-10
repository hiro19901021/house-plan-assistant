import streamlit as st, backend as be, textwrap
# ---------- Overlay 用セッション状態 ----------
if "plans" not in st.session_state:
    st.session_state["plans"] = None
if "chat_history" not in st.session_state:      # ★追加
    st.session_state["chat_history"] = []       # ★追加
import streamlit.components.v1 as components
import uuid
from slugify import slugify

openai_key = st.secrets["OPENAI_API_KEY"]
be.openai.api_key = openai_key
sb = be.get_sb(st)

# ---------- ページ設定 ----------
st.set_page_config("HousePlan Assistant", layout="wide")
st.markdown("""
<style>
body{font-family: "Helvetica Neue", Arial; color:#222}
.sidebar-content{width:260px}
#MainMenu,footer,header{visibility:hidden}
</style>""", unsafe_allow_html=True)

# ---------- サイドバー ----------
st.sidebar.header("PDF Upload")
pdfs = st.sidebar.file_uploader(
    "複数選択可", type="pdf", accept_multiple_files=True)

if st.sidebar.button("Register PDFs") and pdfs:
    for pdf in pdfs:
        # ---------- アップロード処理 ----------
        safe_name = slugify(pdf.name, lowercase=False)
        path = f"{uuid.uuid4()}/{safe_name}"
        st.sidebar.info("Uploading…")

        try:
            sb.storage.from_("floorplans").upload(
                path,
                pdf.getvalue(),
                {"content-type": "application/pdf"}
            )

            # ---- 埋め込みベクトルを計算して DB へ保存 ----
                        # ---- テキストをチャンク分割 → それぞれ埋め込み保存 ----
            full_txt = be.pdf_to_text(pdf.getvalue())
            for chunk in be.chunk_text(full_txt):
                emb = be.embed(chunk)
                sb.table("floorplans").insert(
                    {"filename": pdf.name,
                     "path": path,
                     "embedding": emb}
                ).execute()


            st.sidebar.success(f"✓ {pdf.name} uploaded")
        except Exception as e:
            st.sidebar.error(f"UPLOAD NG: {e}")
            st.stop()
        # ---------- アップロード処理ここまで ----------

# ---------- 要望フォーム ----------
st.title("House-Plan Assistant")
with st.form("request"):
    col1, col2 = st.columns(2)
    fam   = col1.number_input("家族人数", min_value=1, value=3)
    rooms = col1.number_input("希望部屋数", min_value=1, value=3)
    area  = col1.number_input("延床面積 (㎡)", value=100)
    bud   = col2.number_input("予算 (万円)", value=3000)
    pref  = col2.text_area("こだわり", "")
    submitted = st.form_submit_button("プラン提示")

if submitted:
    req = sb.table("customer_requests").insert(
        {"family_size": fam, "rooms": rooms,
         "area_sqm": area, "budget_million_jpy": bud,
         "preferences": pref}).execute().data[0]
    query = be.embed(
        f"{fam}人 {rooms}部屋 {area}㎡ 予算{bud}万円 {pref}")
    plans = sb.rpc("match_plans",
                   {"query": query, "top_n": 3}).execute().data
    st.session_state["plans"] = plans

# ---------- 類似図面（重複除去→一覧→モーダル） ----------
plans = st.session_state.get("plans")
if plans:

    # ❶ 重複除去 : ?トークンを除いたファイルパスで一意化
    uniq = {}
    for p in plans:
        key_path = p["path"].split("?")[0]
        if key_path not in uniq:
            uniq[key_path] = p
    plans = list(uniq.values())

# ❷ 一覧ボタン表示
    st.subheader("類似図面")
    for idx, p in enumerate(plans):
        signed = sb.storage.from_("floorplans").create_signed_url(
            p["path"], 3600
        ).get("signedURL")

        if st.button(p["filename"], key=f"plan_btn_{idx}"):
            st.session_state["pdf_modal_url"] = signed

# ❸ モーダル表示
if st.session_state.get("pdf_modal_url"):
    with st.modal("図面プレビュー", key="pdf_modal"):
        st.markdown(
            f"<iframe src='{st.session_state['pdf_modal_url']}' "
            "width='100%' height='650' style='border:none'></iframe>",
            unsafe_allow_html=True
        )
        if st.button("閉じる", key="close_modal_btn"):
            st.session_state["pdf_modal_url"] = None
# ---------- 類似図面ブロックここまで ----------


# ---------- モーダル表示 ----------
if "pdf_modal_url" not in st.session_state:
    st.session_state["pdf_modal_url"] = None

# ★★★ ここから追加：重複除去 ★★★
# key は p["path"] でも p["filename"] でも OK。今回は path で判定
dedup = {}
for p in plans:
    dedup[p["path"]] = p          # 同じ path が来たら上書き＝結果的に 1 件だけ残る
plans = list(dedup.values())
        st.session_state["pdf_modal_url"] = None

for idx, p in enumerate(plans):               # ★ enumerate で idx 付与
    url = sb.storage.from_("floorplans").create_signed_url(
        p["path"], 3600
    ).get("signedURL")

    unique_key = f"plan_btn_{idx}"            # ★ かぶらないキー
    if st.button(p["filename"], key=unique_key):
        st.session_state["pdf_modal_url"] = url

# URL がセットされていればモーダル表示
if st.session_state["pdf_modal_url"]:
    with st.modal("図面プレビュー"):
        st.markdown(
            f"<iframe src='{st.session_state['pdf_modal_url']}' "
            "width='100%' height='650' style='border:none'></iframe>",
            unsafe_allow_html=True
        )
        # 閉じるボタン
        if st.button("閉じる", key="close_modal_btn"):
            st.session_state["pdf_modal_url"] = None
# ---------- モーダル表示ここまで ----------

    st.subheader("提案プラン")
    ctx = "\n".join(f"{p['filename']}" for p in plans)
    prompt = f"""あなたはハウスメーカーの設計士です。
要望: 家族{fam}人, {rooms}部屋, {area}㎡, 予算{bud}万円
こだわり: {pref}
参考図面: {ctx}
日本語で最適なプランを3案提案してください。"""
    with st.spinner("提案プランを検討中です…"):
        ans = be.openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":prompt}]
        ).choices[0].message.content
    st.write(ans)
    # ---------- チャット欄ここから ----------  ★追加開始
st.divider()
st.subheader("💬 追加質問・修正要望チャット")

# ① これまでのやり取りを表示
for m in st.session_state["chat_history"]:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# ② 入力ボックス
if user_msg := st.chat_input("ここに質問や修正要望を入力してください…"):
    # ②-1 ユーザー発言を履歴に追加
    st.session_state["chat_history"].append({"role": "user", "content": user_msg})

    # ②-2 LLM へ送信
    with st.spinner("回答を生成中…"):
        system_prompt = "これまでのプラン提案と以下の追加要望を踏まえて回答してください。"
        reply = be.openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=(
                [{"role": "system", "content": system_prompt}]
                + st.session_state["chat_history"]
            )
        ).choices[0].message.content

    # ②-3 アシスタント発言を履歴へ
    st.session_state["chat_history"].append({"role": "assistant", "content": reply})

    st.experimental_rerun()   # 画面を即リフレッシュ
# ---------- チャット欄ここまで ----------  ★追加終了
