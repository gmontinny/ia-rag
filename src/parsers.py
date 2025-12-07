import os
import re
from typing import List, Tuple
from bs4 import BeautifulSoup
from PyPDF2 import PdfReader
from .models import Document


ART_RE = re.compile(r"\bArt\.\s*(\d+[A-Za-zº]*)\b", re.IGNORECASE)
PAR_RE = re.compile(r"\b§\s*(\d+º?)\b|\bParágrafo\s+único\b", re.IGNORECASE)
INCISO_RE = re.compile(r"\b([IVXLCDM]+)\s*[-–]\s", re.IGNORECASE)


def _read_html(path: str) -> str:
    # Tenta múltiplos encodings comuns em documentos brasileiros
    encodings = ["utf-8", "latin-1", "iso-8859-1", "cp1252", "windows-1252"]
    html = None
    
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc) as f:
                html = f.read()
            # Verifica se tem caracteres estranhos (indica encoding errado)
            if "Ã" not in html or enc == encodings[-1]:
                break
        except (UnicodeDecodeError, LookupError):
            continue
    
    if html is None:
        # Fallback: lê como bytes e tenta detectar
        with open(path, "rb") as f:
            raw = f.read()
        html = raw.decode("utf-8", errors="replace")
    
    soup = BeautifulSoup(html, "lxml")
    # Remove scripts/styles
    for t in soup(["script", "style"]):
        t.extract()
    text = soup.get_text("\n")
    # collapse multiple newlines
    text = re.sub(r"\n{2,}", "\n\n", text)
    return text.strip()


def _read_pdf(path: str) -> str:
    reader = PdfReader(path)
    texts = []
    for page in reader.pages:
        try:
            texts.append(page.extract_text() or "")
        except Exception:
            continue
    text = "\n".join(texts)
    text = re.sub(r"\n{2,}", "\n\n", text)
    return text.strip()


def load_documents(data_dir: str) -> List[Document]:
    docs: List[Document] = []
    for name in os.listdir(data_dir):
        path = os.path.join(data_dir, name)
        if not os.path.isfile(path):
            continue
        if name.lower().endswith((".html", ".htm")):
            content = _read_html(path)
        elif name.lower().endswith(".pdf"):
            content = _read_pdf(path)
        else:
            continue
        title = os.path.splitext(name)[0]
        doc_id = title
        docs.append(Document(doc_id=doc_id, title=title, source_path=path, content=content))
    return docs
