# IA RAG para Legislação da ANVISA

Este projeto implementa um pipeline de ingestão e vetorização de documentos legais (leis, resoluções, etc.) da ANVISA, com chunking híbrido e armazenamento integrado em três camadas:

- Elasticsearch: índice full‑text dos documentos completos
- Qdrant: base vetorial dos chunks com embeddings gratuitos
- Neo4j: grafo relacional Lei → Artigo → Parágrafo → Inciso → Chunk

O objetivo é permitir consultas híbridas (léxicas + semânticas) preservando o contexto jurídico e a estrutura hierárquica do texto legal.


## Arquitetura

- Ingestão lê arquivos de `./data` (HTML/PDF), extrai texto e normaliza.
- Chunking híbrido preserva marcadores legais (Art., §, incisos em romanos) e cria janelas de frases com sobreposição.
- Vetorização com modelo local gratuito `sentence-transformers/all-MiniLM-L6-v2`.
- Armazenamento:
  - Elasticsearch: cada documento completo (para busca lexical e navegação).
  - Qdrant: cada chunk com vetor e payload (lei/artigo/§/inciso, offsets no texto).
  - Neo4j: nós e relacionamentos hierárquicos, com arestas ligando nós ao(s) chunk(s) que cobrem aquele trecho.

Serviços sobem via `docker-compose.yaml`:
- Elasticsearch 8.x (sem segurança, modo single node)
- Qdrant
- Neo4j 4.4 (auth padrão: `neo4j/password`)


## Pré‑requisitos

- Docker Desktop (ou Docker Engine) e Docker Compose
- Python 3.10+
- Acesso à Internet na primeira execução (para baixar o modelo de embeddings). Depois funciona offline.
- Windows PowerShell (comandos abaixo usam sintaxe do PowerShell)


## Como executar

1) Suba a infraestrutura:
```
docker compose up -d
```

2) Crie e ative um ambiente Python e instale as dependências:
```
python -m venv .venv
. .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3) Crie o arquivo `.env` (ou copie do exemplo) e ajuste se necessário:
```
Copy-Item .env.example .env
# Opcional: edite valores no .env conforme sua máquina
```
Variáveis disponíveis (padrões já funcionam com o docker-compose):
- `ELASTICSEARCH_URL` (ex.: http://localhost:9200)
- `QDRANT_URL` (ex.: http://localhost:6333)
- `NEO4J_URL` (ex.: bolt://localhost:7687)
- `NEO4J_USER`, `NEO4J_PASSWORD`
- `EMBEDDING_MODEL` (default: sentence-transformers/all-MiniLM-L6-v2)
- `DATA_DIR` (default: ./data)
- `QDRANT_COLLECTION` (default: anvisa_chunks)
- `ELASTIC_INDEX` (default: anvisa_docs)

4) Coloque os arquivos de legislação na pasta `data/` (HTML ou PDF). O repositório já contém alguns exemplos.

5) Rode a ingestão (via CLI do `main.py`):
```
python main.py
# ou explicitamente
python main.py ingest

# Alternativa (continua funcionando):
python -m src.ingest
```

Ao final você verá algo como: `Vetores inseridos no Qdrant: N chunks.` e `Ingestão concluída.`


## Pesquisas de demonstração (CLI)

Após a ingestão, você pode experimentar diferentes modos de pesquisa com o subcomando `search` do `main.py`.

Comando geral:
```
python main.py search --q "sua consulta" \
  --mode {lexical,semantic,hybrid,all} \
  --size 10 \
  --limit 5 \
  [--no-explain]
```

Exemplos:
- Todos os modos + explicação no grafo do top‑1 (padrão):
```
python main.py search --q "vigilância sanitária em serviços de saúde"
```
- Apenas lexical (Elasticsearch):
```
python main.py search --q "registro de produtos" --mode lexical
```
- Apenas semântica (Qdrant):
```
python main.py search --q "controle de infecções" --mode semantic --limit 5
```
- Híbrida (ES → Qdrant) sem explicação de grafo:
```
python main.py search --q "boas práticas de fabricação" --mode hybrid --size 15 --limit 5 --no-explain
```

Observações:
- O `payload` no Qdrant inclui o `chunk_id` original; o texto completo do chunk é obtido via Neo4j.
- O ID interno do Qdrant pode ser UUID/int; isso não afeta o uso do `chunk_id` para navegar no grafo.
- O comando `search` utiliza as variáveis de ambiente já suportadas pelo projeto.
- UI do Qdrant: você pode inspecionar coleções e buscar visualmente no dashboard em http://localhost:6333/dashboard (suba o serviço com `docker compose up -d`).


## Pergunte à base (RAG com prompts especializados)

Você pode fazer perguntas em linguagem natural com RAG, usando modelos Gemini (Google) ou GPT (OpenAI). O pipeline:
- Recupera evidências relevantes (chunks) via Qdrant, opcionalmente filtradas pelos candidatos do Elasticsearch (busca híbrida)
- Enriquece cada evidência com trilha no grafo (Lei → Artigo → § → Inciso) via Neo4j
- Monta um prompt especializado jurídico (PT‑BR) e chama o LLM para redigir a resposta com referências

Pré‑requisitos (.env):
```
LLM_PROVIDER=gemini        # ou openai
GEMINI_API_KEY=...         # se usar Gemini; GEMINI_MODEL=gemini-3-pro-preview
OPENAI_API_KEY=...         # se usar OpenAI;  OPENAI_MODEL=gpt-5
```

Comandos:
```
python main.py ask --q "quais são as responsabilidades sobre controle de infecções em serviços de saúde?"

# Escolher provedor e modelo explicitamente
python main.py ask --q "registro de produtos sujeitos à vigilância sanitária" --provider gemini --model gemini-3-pro-preview
python main.py ask --q "boas práticas de fabricação" --provider openai --model gpt-5 --topk 8 --temperature 0.1

# Desativar filtro híbrido (vai direto ao Qdrant)
python main.py ask --q "infrações e penalidades" --no-hybrid

# Mostrar os prompts enviados ao LLM (debug)
python main.py ask --q "parágrafo único aplicável a X" --debug
```

Saída típica: resposta estruturada em PT‑BR com seção “Referências” listando os índices [n] das evidências usadas e a trilha legal (Lei/Art/§/Inciso). Em caso de falta de base, o modelo é instruído a indicar explicitamente.

### Novos parâmetros úteis do RAG
- `--filter-law <termo>`: filtra/prioriza evidências por `law_id` no Qdrant (por exemplo: `L6437`, `L6437compilado`, `13.460`).
- `--no-hybrid`: desativa o pré‑filtro lexical do Elasticsearch, buscando diretamente no Qdrant (útil quando o ES ainda não está com o documento corretamente ranqueado).

### Exemplos práticos que funcionam bem
1) Focar na Lei 6.437/1977 (infrações e penalidades) — prioriza evidências dessa lei e evita perder candidatos no filtro lexical:
```
python main.py ask --q "quais são as infrações e penalidades previstas pela legislação sanitária?" \
  --filter-law L6437 \
  --no-hybrid \
  --topk 12 \
  --max-tokens 1200 \
  --temperature 0.1 \
  --debug
```

2) Quando o provedor retornar resposta vazia (bloqueio/segurança), tente outro modelo ou provedor:
```
# Modelo rápido e permissivo da Gemini
python main.py ask --q "quais são as infrações e penalidades previstas pela legislação sanitária?" \
  --filter-law L6437 --no-hybrid --topk 12 --provider gemini --model gemini-1.5-flash

# Controle com OpenAI (se possuir chave)
python main.py ask --q "quais são as infrações e penalidades previstas pela legislação sanitária?" \
  --filter-law L6437 --no-hybrid --topk 12 --provider openai --model gpt-5
```

3) Observação sobre fallback: se o LLM ainda assim devolver vazio, o sistema gera automaticamente um resumo extrativo com sentenças que mencionam termos como “infração”, “penalidade”, “multa”, etc., a partir dos trechos recuperados, e lista as referências.


## O que o pipeline faz

- Lê documentos em `data/` e indexa no Elasticsearch (índice `anvisa_docs`).
- Gera chunks híbridos mantendo contexto legal:
  - Detecta `Art.`, `§` (inclui “Parágrafo único”) e incisos em algarismos romanos.
  - Cria janelas de até 6 frases com sobreposição de 2 para melhor continuidade semântica.
- Gera embeddings locais e armazena no Qdrant (coleção `anvisa_chunks`, métrica cosine).
- Cria/atualiza o grafo no Neo4j com relacionamentos hierárquicos e atrela cada `Chunk` ao nível mais específico disponível.


## Exemplos de uso após a ingestão

### 1) Consultar documentos no Elasticsearch (busca lexical)

- Via navegador: http://localhost:9200/anvisa_docs/_search?pretty=true&q=conteudo:ANVISA

- Via `curl` (PowerShell):
```
curl -s "http://localhost:9200/anvisa_docs/_search" `
  -H "Content-Type: application/json" `
  -d '{
    "query": { "match": { "content": "vigilância sanitária" } },
    "size": 3
  }'
```

### 2) Inspecionar a coleção no Qdrant (via HTTP)

- Informações da coleção:
```
curl http://localhost:6333/collections/anvisa_chunks
```

- Buscar semanticamente (exemplo simples usando `curl`):
```
# Primeiro gere o embedding da consulta em Python e cole o vetor no campo "vector" abaixo
# (ver exemplo de código Python a seguir)
```

Exemplo Python rápido de busca vetorial:
```
python
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer
client = QdrantClient(url="http://localhost:6333")
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
query = "exigências para serviços de saúde"
vec = model.encode([query], normalize_embeddings=True)[0].tolist()
res = client.search(collection_name="anvisa_chunks", query_vector=vec, limit=5)
for p in res:
    print(p.payload.get("law_id"), p.payload.get("article"), p.score)
```

### 3) Explorar o grafo no Neo4j

- Acesse o browser do Neo4j: http://localhost:7474
- Login padrão (compose): user `neo4j`, senha `password` (se alterar, atualize no `.env`).

Consultas Cypher úteis:
```
// Contar nós por tipo
MATCH (n:Law) RETURN count(n) as leis;
MATCH (n:Article) RETURN count(n) as artigos;
MATCH (n:Paragraph) RETURN count(n) as paragrafos;
MATCH (n:Inciso) RETURN count(n) as incisos;
MATCH (n:Chunk) RETURN count(n) as chunks;

// Amostrar uma lei e seus artigos
MATCH (l:Law)-[:HAS_ARTICLE]->(a:Article)
RETURN l.id, collect(a.num)[0..10];

// Navegar até chunks de um Artigo específico
MATCH (a:Article {id: $artigoId})-[:HAS_CHUNK]->(c:Chunk)
RETURN c.id, c.text[0..200] LIMIT 5;
// Ex.: SET $artigoId = "L9784:Art1"
```


## Estrutura do código

- `src/config.py`: carregamento de configurações via `.env`
- `src/parsers.py`: leitura e extração de texto de HTML/PDF
- `src/chunker.py`: chunking híbrido com contexto legal
- `src/embeddings.py`: wrapper do `SentenceTransformer`
- `src/stores/`: conectores de armazenamento (Elasticsearch, Qdrant, Neo4j)
- `src/ingest.py`: lógica principal de ingestão
- `src/search.py`: demonstração de buscas (lexical, semântica, híbrida) e contexto via grafo
- `main.py`: ponto de entrada/CLI para executar ingestão e pesquisas (`search`)
- `docker-compose.yaml`: serviços de infraestrutura


## Dicas e solução de problemas

- Elasticsearch não inicia ou retorna erro de conexão:
  - Verifique `docker compose ps` e logs `docker compose logs elasticsearch`.
  - Porta 9200 deve estar livre.
  - O compose está com `xpack.security.enabled=false` para simplificar.

- Neo4j solicita alteração de senha no primeiro start:
  - Atualize `NEO4J_PASSWORD` no `.env` para a nova senha e rode a ingestão novamente.

- Qdrant com erro de coleção inexistente:
  - O script cria/recria a coleção automaticamente. Confira logs e se a URL está correta.

- Torch/embeddings em CPU lenta ou sem AVX:
  - Pode ser necessário instalar uma versão compatível de `torch`.
  - Reduza `batch_size` em `src/ingest.py` (linha onde chama `emb.encode`).

- Performance geral:
  - Execute a ingestão com serviços já “quentes” (após primeiro start).
  - Ajuste `max_sentences`/`overlap` em `hybrid_chunk` conforme o tamanho dos documentos.


## Próximos passos (sugestões)

- API de consulta RAG combinando:
  - Filtro lexical no Elasticsearch → candidatos
  - Re‑rank/expansão semântica no Qdrant
  - Recuperação de contexto e trilha de navegação via Neo4j
- UI simples para consultas e visualização do grafo
- Normalização mais robusta dos marcadores legais (variações de formatação)


## Licença

Uso interno/demonstrativo. Ajuste conforme a necessidade do seu projeto.
