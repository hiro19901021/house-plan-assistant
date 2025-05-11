import uuid, openai, pypdf
from io import BytesIO
from supabase import create_client

def get_sb(st):
    """
    Supabase クライアントを返す。
    - nested 形式  : st.secrets["supabase"]["url"]
    - flat 形式    : st.secrets["SUPABASE_URL"]
    どちらでも動く。
    """
    # URL 取得
    url = st.secrets.get("SUPABASE_URL") \
        or st.secrets["supabase"]["url"]

    # キー取得
    key = st.secrets.get("SUPABASE_SERVICE_KEY") \
        or st.secrets["supabase"]["service_key"]

    return create_client(url, key)

# ---- PDF → テキスト ----
def pdf_to_text(data: bytes) -> str:
    reader = pypdf.PdfReader(BytesIO(data))
    return "\n".join(p.extract_text() or "" for p in reader.pages)

# ---- Embedding ----
openai.api_key = openai_key = None  # set later

def embed(txt: str):
    rsp = openai.embeddings.create(
        model="text-embedding-3-small", input=[txt])
    return rsp.data[0].embedding

# ---- テキストを安全サイズに分割 ----
def chunk_text(txt: str, max_chars: int = 6000):
    """
    OpenAI Embedding が受け取れる 8k token 未満に
    ざっくり合わせるため文字数で分割（日本語 ≒3 字で 1 token 目安）
    """
    for i in range(0, len(txt), max_chars):
        yield txt[i : i + max_chars]
