import uuid, openai, pypdf
from io import BytesIO
from supabase import create_client

# ---- Supabase クライアント ----
def get_sb(st):
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_SERVICE_KEY"])   # 強権限キー

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