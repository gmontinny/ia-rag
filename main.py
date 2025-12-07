"""
Arquivo principal para executar os processos do projeto.

Uso rápido:
  - python main.py            # roda a ingestão completa (padrão)
  - python main.py ingest     # idem

Observação: certifique-se de que os serviços (Elasticsearch, Qdrant, Neo4j)
estão em execução (ex.: via docker compose up -d) e que o .env está configurado.
"""

import argparse
import sys


def cmd_ingest(_args=None):
    # Import adiado para acelerar start e evitar carregar dependências quando não necessário
    from src.ingest import main as ingest_main

    ingest_main()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ia_rag",
        description="Executa processos do pipeline (ingestão, etc.)",
    )
    sub = parser.add_subparsers(dest="command")

    # Subcomando: ingest
    p_ingest = sub.add_parser("ingest", help="Executa a ingestão e indexação completa")
    p_ingest.set_defaults(func=cmd_ingest)

    # Subcomando: search
    def cmd_search(args):
        from src.search import run_search

        return run_search(
            mode=args.mode,
            query=args.query,
            size=args.size,
            limit=args.limit,
            explain=not args.no_explain,
        )

    p_search = sub.add_parser(
        "search",
        help="Executa consultas de exemplo (lexical, semântica, híbrida) e opção de contexto no grafo",
    )
    p_search.add_argument("--q", "--query", dest="query", required=True, help="Texto da consulta")
    p_search.add_argument(
        "--mode",
        choices=["lexical", "semantic", "hybrid", "all"],
        default="all",
        help="Modo de busca: lexical|semantic|hybrid|all (padrão: all)",
    )
    p_search.add_argument("--size", type=int, default=10, help="Tamanho para candidatos do ES (default=10)")
    p_search.add_argument("--limit", type=int, default=5, help="Top-K no Qdrant (default=5)")
    p_search.add_argument("--no-explain", action="store_true", help="Não buscar contexto no grafo para o top-1")
    p_search.set_defaults(func=cmd_search)

    # Subcomando: ask (RAG)
    def cmd_ask(args):
        from src.rag import run_rag

        answer = run_rag(
            query=args.query,
            topk=args.topk,
            provider=args.provider,
            model_name=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            use_hybrid=not args.no_hybrid,
            filter_law=args.filter_law,
            debug_print=args.debug,
        )
        # Imprime a resposta final do LLM
        print(answer)

    p_ask = sub.add_parser(
        "ask",
        help="Faz uma pergunta usando RAG (recupera evidências e gera resposta com LLM)",
    )
    p_ask.add_argument("--q", "--query", dest="query", required=True, help="Pergunta/consulta em linguagem natural")
    p_ask.add_argument("--topk", type=int, default=6, help="Número de evidências (chunks) a recuperar (default=6)")
    p_ask.add_argument(
        "--provider",
        choices=["gemini", "openai"],
        default=None,
        help="Provedor do LLM: gemini|openai (padrão: LLM_PROVIDER do .env)",
    )
    p_ask.add_argument("--model", default=None, help="Nome do modelo (padrão: *_MODEL do .env)")
    p_ask.add_argument("--temperature", type=float, default=0.2, help="Temperatura de geração (default=0.2)")
    p_ask.add_argument("--max-tokens", type=int, default=800, help="Limite de tokens de saída (default=800)")
    p_ask.add_argument("--no-hybrid", action="store_true", help="Desativa filtro lexical do ES antes do Qdrant")
    p_ask.add_argument(
        "--filter-law",
        default=None,
        help="Filtra/prioriza evidências pelo campo law_id no Qdrant (ex.: L6437compilado, 13.460, etc.)",
    )
    p_ask.add_argument("--debug", action="store_true", help="Mostra prompts enviados ao LLM")
    p_ask.set_defaults(func=cmd_ask)

    return parser


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    if not argv:
        # Comando padrão: ingest
        return cmd_ingest()
    args = parser.parse_args(argv)
    if hasattr(args, "func"):
        return args.func(args)
    # Se nenhum subcomando válido for fornecido, mostra ajuda
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
