import streamlit as st, backend as be, textwrap
import streamlit.components.v1 as components
import uuid
from slugify import slugify

# ✅ ページ設定（ここは1回だけ）
st.set_page_config(page_title="HousePlan Assistant", layout="wide")

# --- セッション初期化と UI セットアップ ---
def init_session():
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("plans", None)
    st.session_state.setdefault("overlay_url", None)
    st.session_state.setdefault("proposal_text", None)
    st.session_state.setdefault("show_modal", False)

def setup_ui():
    st.markdown("""
    <style>
    body{font-family: "Helvetica Neue", Arial; color:#222}
    .sidebar-content{width:260px}
    #MainMenu,footer,header{visibility:hidden}
    </style>
    """, unsafe_allow_html=True)

init_session()
setup_ui()


# --- Chat セッション変数を初期化 ---
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []   # 空リスト

# --- プラン固定用 ---
if "proposal_text" not in st.session_state:
    st.session_state["proposal_text"] = None

openai_key = st.secrets["OPENAI_API_KEY"]
be.openai.api_key = openai_key
sb = be.get_sb(st)

# ---------- ページ設定 ----------
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
# ---------- プラン生成関数 ----------
def generate_plan(request_row, plans):
    fam, rooms, area, bud, pref = (
        request_row["family_size"],
        request_row["rooms"],
        request_row["area_sqm"],
        request_row["budget_million_jpy"],
        request_row["preferences"],
    )
    ctx = "\n".join(p["filename"] for p in plans)
    prompt = f"""あなたはハウスメーカーの設計士です。
要望: 家族{fam}人, {rooms}部屋, {area}㎡, 予算{bud}万円
こだわり: {pref}
参考図面: {ctx}
日本語で最適なプランを3案提案してください。"""
    rsp = be.openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt}]
    )
    return rsp.choices[0].message.content

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
    with st.spinner("プランを検討中です…"):
        req = sb.table("customer_requests").insert(
            {"family_size": fam, "rooms": rooms,
             "area_sqm": area, "budget_million_jpy": bud,
             "preferences": pref}).execute().data[0]

        query = be.embed(f"{fam}人 {rooms}部屋 {area}㎡ 予算{bud}万円 {pref}")
        plans = sb.rpc("match_plans", {"query": query, "top_n": 3}).execute().data
        st.session_state["plans"] = plans
        st.session_state["proposal_text"] = generate_plan(req, plans)
    st.experimental_rerun()


# ---------- ここから置き換え ----------
plans = st.session_state["plans"]          # 1) キャッシュを取り出す
if st.session_state.get("show_modal") and st.session_state.get("overlay_url"):
    with st.modal("図面プレビュー"):
        st.components.v1.iframe(
            st.session_state["overlay_url"],
            height=600, width=800
        )
        st.button("閉じる", on_click=lambda: st.session_state.update({
            "show_modal": False, "overlay_url": None
        }))


st.divider()
st.subheader("追加質問・修正要望チャット")

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
        system_prompt = f"""
        あなたはハウスメーカーの営業担当です。
        以下のプラン概要を前提に、お客様の追加質問に答えてください。

        --- プラン概要 ---
        {st.session_state['proposal_text']}
        ------------------
        """

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