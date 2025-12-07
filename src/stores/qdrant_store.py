from typing import List, Dict, Optional, Union
import uuid
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm


class QdrantStore:
    def __init__(self, url: str, collection: str, vector_size: int):
        self.client = QdrantClient(url=url)
        self.collection = collection
        self.vector_size = vector_size

    def ensure_collection(self):
        exists = False
        try:
            info = self.client.get_collection(self.collection)
            exists = True
        except Exception:
            exists = False
        if not exists:
            self.client.recreate_collection(
                collection_name=self.collection,
                vectors_config=qm.VectorParams(size=self.vector_size, distance=qm.Distance.COSINE),
            )

    def _to_point_id(self, raw_id: str) -> Union[int, str]:
        """Qdrant aceita IDs inteiros ou UUID. Convertemos determinísticamente strings para UUIDv5.
        Mantemos inteiros quando possível.
        """
        # Se for inteiro em string, mantém como int
        if isinstance(raw_id, str) and raw_id.isdigit():
            try:
                return int(raw_id)
            except ValueError:
                pass
        # Caso contrário, gera UUIDv5 determinístico baseado no collection name + raw_id
        namespace = uuid.uuid5(uuid.NAMESPACE_URL, f"qdrant:{self.collection}")
        return str(uuid.uuid5(namespace, raw_id))

    def upsert(self, ids: List[str], vectors: List[List[float]], payloads: Optional[List[Dict]] = None):
        points: List[qm.PointStruct] = []
        for i, raw_id in enumerate(ids):
            qid = self._to_point_id(raw_id)
            payload: Optional[Dict] = None
            if payloads:
                payload = dict(payloads[i]) if payloads[i] is not None else {}
            else:
                payload = {}
            # Preserva o ID original no payload para rastreabilidade
            if "chunk_id" not in payload:
                payload["chunk_id"] = raw_id
            points.append(qm.PointStruct(id=qid, vector=vectors[i], payload=payload))
        self.client.upsert(collection_name=self.collection, points=points, wait=True)
