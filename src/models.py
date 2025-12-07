from dataclasses import dataclass, field
from typing import List, Optional, Dict


@dataclass
class LegalRef:
    law_id: str
    article: Optional[str] = None
    paragraph: Optional[str] = None
    inciso: Optional[str] = None


@dataclass
class Document:
    doc_id: str
    title: str
    source_path: str
    content: str
    meta: Dict[str, str] = field(default_factory=dict)


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    text: str
    legal_ref: LegalRef
    start_char: int
    end_char: int
    tokens: int = 0
    extra: Dict[str, str] = field(default_factory=dict)