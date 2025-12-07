"""Teste direto com API REST do Qdrant usando httpx"""
import httpx
import json

print("Testando conexão direta com Qdrant via HTTP...")

try:
    # Criar cliente HTTP
    client = httpx.Client(timeout=10.0)
    
    # Testar endpoint básico
    print("\n1. Testando GET /collections...")
    response = client.get("http://127.0.0.1:6333/collections")
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.text[:200]}")
    
    # Criar coleção
    collection_name = "anvisa_chunks"
    print(f"\n2. Criando coleção '{collection_name}'...")
    
    payload = {
        "vectors": {
            "size": 768,
            "distance": "Cosine"
        }
    }
    
    response = client.put(
        f"http://127.0.0.1:6333/collections/{collection_name}",
        json=payload
    )
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.text}")
    
    # Verificar coleção
    print(f"\n3. Verificando coleção '{collection_name}'...")
    response = client.get(f"http://127.0.0.1:6333/collections/{collection_name}")
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.text[:500]}")
    
    print("\n✓ Teste concluído com sucesso!")
    client.close()
    
except Exception as e:
    print(f"\n✗ Erro: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
