from typing import List, Dict, Optional, Union
import uuid
import time
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm


class QdrantStore:
    def __init__(
        self,
        url: str,
        collection: str,
        vector_size: int,
        upsert_batch: int | None = None,
        timeout: float | None = None,
        retries: int | None = None,
    ):
        # Timeout HTTP para requests ao Qdrant (segundos)
        timeout_val = float(timeout) if timeout is not None else 120.0
        self.client = QdrantClient(url=url, timeout=timeout_val)
        self.collection = collection
        self.vector_size = vector_size
        # Tamanho do lote para dividir requisições e evitar limite de 32 MiB do Qdrant HTTP
        self.upsert_batch = int(upsert_batch or 256)
        self.retries = int(retries or 3)

    # --- utilitários de retry simples com backoff exponencial ---
    def _with_retries(self, func, *args, **kwargs):
        delay = 1.0
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:  # inclui ReadTimeout/ResponseHandlingException
                last_exc = e
                if attempt == self.retries:
                    break
                time.sleep(delay)
                delay = min(delay * 2.0, 8.0)
        if last_exc:
            raise last_exc
        return None

    def ensure_collection(self):
        """Garante a coleção com o tamanho de vetor correto.
        - Se não existir: cria (create_collection).
        - Se existir com tamanho diferente: recria (recreate_collection).
        """
        try:
            info = self._with_retries(self.client.get_collection, self.collection)
            # Extrai tamanho atual
            current_size = None
            vc = getattr(info, "vectors_config", None)
            try:
                if vc is not None:
                    if hasattr(vc, "size"):
                        current_size = int(getattr(vc, "size"))
                    elif isinstance(vc, dict):
                        for v in vc.values():
                            if hasattr(v, "size"):
                                current_size = int(getattr(v, "size"))
                                break
            except Exception:
                current_size = None
            if current_size is None:
                try:
                    cfg = getattr(info, "config", None)
                    params = getattr(cfg, "params", None)
                    vectors = getattr(params, "vectors", None)
                    if hasattr(vectors, "size"):
                        current_size = int(getattr(vectors, "size"))
                except Exception:
                    current_size = None

            # Se já está com o tamanho certo, nada a fazer
            if current_size == int(self.vector_size):
                return

            # Tamanho diferente: recria
            self._with_retries(
                self.client.recreate_collection,
                collection_name=self.collection,
                vectors_config=qm.VectorParams(size=self.vector_size, distance=qm.Distance.COSINE),
            )
            return
        except Exception:
            # Coleção não existe: cria do zero (evita tentativa de delete)
            self._with_retries(
                self.client.create_collection,
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
        # Constrói todos os pontos primeiro
        all_points: List[qm.PointStruct] = []
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
            all_points.append(qm.PointStruct(id=qid, vector=vectors[i], payload=payload))

        # Envia em lotes para respeitar limites de tamanho de payload do Qdrant
        bsz = max(1, int(self.upsert_batch))
        for start in range(0, len(all_points), bsz):
            batch = all_points[start:start + bsz]
            self._with_retries(self.client.upsert, collection_name=self.collection, points=batch, wait=True)
