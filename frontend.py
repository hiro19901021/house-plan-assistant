import streamlit as st, backend as be, textwrap
import streamlit.components.v1 as components
import uuid
from slugify import slugify
import urllib.parse

# ---------- 変数の準備 ----------
if "plan_requested" not in st.session_state:
    st.session_state["plan_requested"] = False
if "plans" not in st.session_state:
    st.session_state["plans"] = None
if "overlay_url" not in st.session_state:
    st.session_state["overlay_url"] = None

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
    st.session_state["plan_requested"] = True  # ボタンが押された！
    st.session_state["plans"] = plans

# ---------- プラン提示結果表示 ----------
if st.session_state["plan_requested"]:  # ボタンが押されたら表示
    plans = st.session_state["plans"]
    if plans:
        st.subheader("類似図面")
        for p in plans:
            url = sb.storage.from_("floorplans").create_signed_url(
                p["path"], 3600
            ).get("signedURL")

            # 2) クリックされた PDF の URL を session_state に保存
            if st.button(p["filename"], key=f"btn_{p['id']}"):
                st.session_state["overlay_url"] = url

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

    # ---------- モーダル表示 ----------
    if st.session_state["overlay_url"]:
        viewer = "https://mozilla.github.io/pdf.js/web/viewer.html?file="
        iframe_url = viewer + urllib.parse.quote_plus(
            st.session_state["overlay_url"]
        )

        overlay_html = """
        <div id="sp_overlay" style="
                position:fixed;top:0;left:0;width:100%;height:100%;
            background:rgba(0,0,0,0.7);z-index:9999;">
            <div style="
                position:absolute;top:5%;left:5%;width:90%;height:90%;
            background:#fff;border-radius:8px;overflow:hidden;">
            <iframe src='{iframe_url}'
                    width='100%' height='100%' style='border:none;'></iframe>
            <button id="sp_close" style="
                    position:absolute;top:8px;right:16px;z-index:10000;
                padding:6px 12px;font-size:18px;border:none;
                    background:#fff;border-radius:4px;cursor:pointer;">
                ✕
            </button>
            </div>
        </div>

        <script>
            document.getElementById("sp_close").onclick = function () {
                document.getElementById("sp_overlay").remove();
            };
        </script>
        """

        components.html(overlay_html, height=0, width=0)   # JS 実行可

        # Python 側のフラグは消しておく（次クリックで再表示）
        st.session_state["overlay_url"] = None

# ---------- チャット欄ここから ----------  ★追加開始
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