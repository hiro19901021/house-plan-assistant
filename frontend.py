# ===== 共通ヘルパー =====
import streamlit as st
def show_pdf_modal(url: str):
    """
    Streamlit ≥1.29 なら st.modal を使う。
    それ未満、またはネスト制限で AttributeError が出る環境では
    簡易ダイアログに自動フォールバックする。
    """
    def _body():
        st.markdown(
            f"<iframe src='{url}' width='100%' height='650' style='border:none'></iframe>",
            unsafe_allow_html=True,
        )

    # st.modal が使えるか判定
    if hasattr(st, "modal"):
        try:
            with st.modal("図面プレビュー", key="pdf_modal"):
                _body()
                if st.button("閉じる", key="close_modal_btn"):
                    st.session_state.pop("pdf_modal_url", None)
                    st.rerun()
        except AttributeError:
            # まれにネスト制限で AttributeError が出る場合
            st.warning("⚠️ 表示環境の都合で簡易プレビューになります")
            _body()
    else:
        st.warning("⚠️ Streamlit のバージョンが古いため簡易プレビューになります")
        _body()

import streamlit as st, backend as be, textwrap
# ---------- Overlay 用セッション状態 ----------
if "plans" not in st.session_state or not isinstance(st.session_state["plans"], list):
    st.session_state["plans"] = []     # 空リストを保証
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
# plans を空リストで初期化しておくと TypeError を根本回避
plans = st.session_state.get("plans", [])
if not isinstance(plans, list):
    plans = []                  # 安全弁

if plans:
    # ❶ 重複除去: 署名トークンを除いた path で辞書化
    uniq = {}
    for p in plans:
        key_path = p["path"].split("?")[0]
        uniq[key_path] = p      # 後勝ちでも内容は同じ
    plans = list(uniq.values())

    st.subheader("類似図面")

    # ❷ ボタン列
    for p in plans:
        signed = sb.storage.from_("floorplans").create_signed_url(
            p["path"], 3600
        ).get("signedURL")

        btn_key = f"similar_{hash(p['path'].split('?')[0])}"
        if st.button(p["filename"], key=btn_key):
            # 既にモーダルが開いていれば URL を更新
            st.session_state["pdf_modal_url"] = signed

# ❸ モーダル呼び出し（必ず 1 か所）
if "pdf_modal_url" in st.session_state:
    show_pdf_modal(st.session_state["pdf_modal_url"])
# ---------- 類似図面ブロックここまで ----------


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
