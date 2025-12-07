from typing import List
from sentence_transformers import SentenceTransformer


class Embeddings:
    def __init__(self, model_name: str):
        self.model = SentenceTransformer(model_name)
        self.dim = self.model.get_sentence_embedding_dimension()

    def encode(self, texts: List[str], batch_size: int = 64) -> List[List[float]]:
        # Em sentence-transformers v3.x, quando convert_to_numpy=False, o retorno já é list,
        # portanto .tolist() causaria AttributeError. Usamos convert_to_numpy=True e então .tolist().
        return self.model.encode(
            texts,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
        ).tolist()
