import streamlit as st, backend as be, textwrap
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


    st.subheader("類似図面")
    for p in plans:
        url = sb.storage.from_("floorplans").create_signed_url(
            p["path"], 3600
        ).link

        if st.button(p["filename"]):
            overlay_html = f"""
            <div style='position:fixed;top:0;left:0;width:100%;height:100%;
                        background:rgba(0,0,0,0.6);z-index:9999;'>
            <div style='position:absolute;top:5%;left:5%;width:90%;height:90%;'>
                <iframe src="{url}" width="100%" height="100%" style="border:none;"></iframe>
            </div>
            </div>
            """
            components.html(overlay_html, height=0, width=0)

    st.subheader("提案プラン")
    ctx = "\n".join(f"{p['filename']}" for p in plans)
    prompt = f"""あなたはハウスメーカーの設計士です。
要望: 家族{fam}人, {rooms}部屋, {area}㎡, 予算{bud}万円
こだわり: {pref}
参考図面: {ctx}
日本語で最適なプランを3案提案してください。"""
    ans = be.openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt}]
    ).choices[0].message.content
    st.write(ans)