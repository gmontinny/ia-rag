from typing import List, Optional
import numpy as np
import torch


class Embeddings:
    """Wrapper que suporta tanto modelos Sentence-Transformers quanto modelos Hugging Face (Transformers).

    - Se o nome do modelo for compatível com `SentenceTransformer`, usamos diretamente (mais rápido/prático).
    - Caso contrário, caímos para `AutoModel` + `AutoTokenizer` com mean pooling e normalização L2.
    - Suporta autenticação no Hugging Face Hub via token.
    """

    def __init__(
        self,
        model_name: str,
        hf_token: Optional[str] = None,
        local_files_only: bool = False,
        force_backend: Optional[str] = None,
    ):
        self.model_name = model_name
        self.hf_token = (hf_token or "").strip()
        self.local_files_only = bool(local_files_only)
        self.backend = "st"  # or "hf"
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        BACKUP_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
        # Ordem de tentativa: controlada por force_backend e heurística do nome do modelo
        force = (force_backend or "").strip().lower()
        try_hf_first = False
        if force in ("hf", "transformers"):
            try_hf_first = True
        elif force in ("st", "sentence-transformers"):
            try_hf_first = False
        else:
            # Heurística: se não for um modelo da org sentence-transformers, tente HF primeiro
            try_hf_first = not (model_name.startswith("sentence-transformers/"))

        st_err = None
        hf_err = None

        def _load_st():
            nonlocal st_err
            try:
                import sentence_transformers  # type: ignore
                from sentence_transformers import SentenceTransformer  # type: ignore

                st_kwargs = {}
                # Detecta versão do ST e usa apenas o argumento correto
                try:
                    ver = getattr(sentence_transformers, "__version__", "3")
                except Exception:
                    ver = "3"
                if self.hf_token:
                    if str(ver).startswith("3"):
                        st_kwargs["token"] = self.hf_token
                    else:
                        st_kwargs["use_auth_token"] = self.hf_token
                if self.local_files_only:
                    st_kwargs["local_files_only"] = True

                self._st_model = SentenceTransformer(model_name, **st_kwargs)
                self.dim = self._st_model.get_sentence_embedding_dimension()
                self.backend = "st"
                print(f"[Embeddings] Using backend=ST model={model_name} device={self.device} dim={self.dim}")
                return True
            except Exception as e:
                self._st_model = None
                st_err = e
                return False

        def _load_hf():
            nonlocal hf_err
            try:
                from transformers import AutoModel, AutoTokenizer  # type: ignore
                tok_kwargs = {"local_files_only": self.local_files_only}
                mdl_kwargs = {"local_files_only": self.local_files_only, "trust_remote_code": False}
                if self.hf_token:
                    tok_kwargs["token"] = self.hf_token
                    mdl_kwargs["token"] = self.hf_token

                self._hf_tokenizer = AutoTokenizer.from_pretrained(model_name, **tok_kwargs)
                self._hf_model = AutoModel.from_pretrained(model_name, **mdl_kwargs)
                self._hf_model.to(self.device)
                hidden = getattr(getattr(self._hf_model, "config", None), "hidden_size", None)
                if not hidden:
                    hidden = 768
                self.dim = int(hidden)
                self.backend = "hf"
                print(f"[Embeddings] Using backend=HF model={model_name} device={self.device} dim={self.dim}")
                return True
            except Exception as e:
                hf_err = e
                # Se estiver offline e os arquivos não existirem, dar erro claro
                if self.local_files_only:
                    raise RuntimeError(
                        f"Falha ao carregar modelo HF '{model_name}' com HF_LOCAL_FILES_ONLY=true. "
                        f"Garanta que os arquivos estejam em cache local. Erro: {e}"
                    )
                return False

        # Tenta na ordem definida
        if try_hf_first:
            if _load_hf() or _load_st():
                return
        else:
            if _load_st() or _load_hf():
                return

        # Fallback final para um modelo público estável
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            st_kwargs = {"local_files_only": self.local_files_only}
            self._st_model = SentenceTransformer(BACKUP_MODEL, **st_kwargs)
            self.dim = self._st_model.get_sentence_embedding_dimension()
            self.backend = "st"
            print(
                f"[Embeddings] Aviso: não foi possível carregar '{model_name}' (ST={st_err} | HF={hf_err}). "
                f"Usando fallback '{BACKUP_MODEL}' (dim={self.dim})."
            )
            return
        except Exception as e_bk:
            raise RuntimeError(
                f"Falha ao carregar embeddings. Tentativas: ordem={'HF->ST' if try_hf_first else 'ST->HF'}.\n"
                f"Erros: ST={st_err} | HF={hf_err} | BK={e_bk}"
            )

    def _hf_encode_batch(self, batch_texts: List[str]) -> np.ndarray:
        # Tokeniza com truncation para 512 tokens (BERT/LegaL-BERT)
        toks = self._hf_tokenizer(
            batch_texts,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        toks = {k: v.to(self.device) for k, v in toks.items()}
        with torch.no_grad():
            out = self._hf_model(**toks)
            last_hidden = out.last_hidden_state  # [B, T, H]
            attention_mask = toks["attention_mask"].unsqueeze(-1).expand(last_hidden.size())  # [B, T, H]
            # mean pooling mascarada
            sum_embeddings = (last_hidden * attention_mask).sum(dim=1)
            sum_mask = attention_mask.sum(dim=1).clamp(min=1e-9)
            emb = sum_embeddings / sum_mask
            # normalização L2
            emb = torch.nn.functional.normalize(emb, p=2, dim=1)
        return emb.cpu().numpy()

    def encode(self, texts: List[str], batch_size: int = 64) -> List[List[float]]:
        if not texts:
            return []
        if self.backend == "st" and self._st_model is not None:
            # Sentence-Transformers otimizado
            arr = self._st_model.encode(
                texts,
                batch_size=batch_size,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
            return arr.tolist()

        # Transformers puro: processa em lotes
        embeddings: List[np.ndarray] = []
        for i in range(0, len(texts), batch_size):
            arr = self._hf_encode_batch(texts[i : i + batch_size])
            embeddings.append(arr)
        all_emb = np.vstack(embeddings)
        return all_emb.tolist()
