import re
from typing import List, Tuple
from .models import Document, Chunk, LegalRef


ART_RE = re.compile(r"\bArt\.\s*(\d+[A-Za-zº]*)\b", re.IGNORECASE)
PAR_RE = re.compile(r"\b§\s*(\d+º?)\b|\bParágrafo\s+único\b", re.IGNORECASE)
INCISO_RE = re.compile(r"\b([IVXLCDM]+)\s*[-–]\s", re.IGNORECASE)


def _simple_sentence_split(text: str) -> List[str]:
    # Basic sentence splitter for Portuguese (period, question, exclamation)
    parts = re.split(r"(?<=[\.!?])\s+(?=[A-ZÁÉÍÓÚÂÊÎÔÛÃÕÇ])", text)
    return [p.strip() for p in parts if p.strip()]


def hybrid_chunk(document: Document, max_sentences: int = 6, overlap: int = 2) -> List[Chunk]:
    """Hybrid chunking: preserve legal structure markers and create sentence windows with overlap.
    Each chunk carries best-effort legal references (law/article/paragraph/inciso).
    """
    text = document.content
    sentences = _simple_sentence_split(text)
    chunks: List[Chunk] = []

    # Track current legal context while iterating sentences
    current_article = None
    current_paragraph = None
    current_inciso = None

    # Precompute sentence start positions
    positions: List[Tuple[int, int]] = []
    idx = 0
    for s in sentences:
        pos = text.find(s, idx)
        if pos == -1:
            pos = idx
        positions.append((pos, pos + len(s)))
        idx = pos + len(s)

    # Sliding window
    i = 0
    while i < len(sentences):
        window = sentences[i : min(i + max_sentences, len(sentences))]
        chunk_text = " ".join(window)

        # update legal context based on sentences within the window
        for s in window:
            m_art = ART_RE.search(s)
            if m_art:
                current_article = m_art.group(1)
                current_paragraph = None
                current_inciso = None
            m_par = PAR_RE.search(s)
            if m_par:
                current_paragraph = m_par.group(0)
                current_inciso = None
            m_inc = INCISO_RE.search(s)
            if m_inc:
                current_inciso = m_inc.group(1)

        start = positions[i][0]
        end = positions[min(i + max_sentences, len(sentences)) - 1][1]

        legal_ref = LegalRef(
            law_id=document.title,
            article=current_article,
            paragraph=current_paragraph,
            inciso=current_inciso,
        )
        chunk_id = f"{document.doc_id}:{start}-{end}"
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                doc_id=document.doc_id,
                text=chunk_text,
                legal_ref=legal_ref,
                start_char=start,
                end_char=end,
            )
        )
        # advance with overlap
        if i + max_sentences >= len(sentences):
            break
        i += max_sentences - overlap if max_sentences > overlap else 1

    return chunks
