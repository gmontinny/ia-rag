"""Script de teste para verificar conectividade com Qdrant"""
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
import time

print("Testando conexão com Qdrant...")

try:
    # Criar cliente com timeout maior
    client = QdrantClient(url="http://localhost:6333", timeout=300)
    print("✓ Cliente criado")
    
    # Listar coleções existentes
    print("\nListando coleções...")
    collections = client.get_collections()
    print(f"✓ Coleções existentes: {collections}")
    
    # Tentar criar coleção de teste
    collection_name = "anvisa_chunks"
    vector_size = 768  # legal-bert-pt-br
    
    print(f"\nVerificando se coleção '{collection_name}' existe...")
    try:
        info = client.get_collection(collection_name)
        print(f"✓ Coleção já existe: {info}")
    except Exception as e:
        print(f"Coleção não existe, criando... (erro: {e})")
        
        print(f"Criando coleção '{collection_name}' com dimensão {vector_size}...")
        result = client.create_collection(
            collection_name=collection_name,
            vectors_config=qm.VectorParams(size=vector_size, distance=qm.Distance.COSINE)
        )
        print(f"✓ Coleção criada: {result}")
        
        # Aguardar um pouco
        time.sleep(2)
        
        # Verificar novamente
        info = client.get_collection(collection_name)
        print(f"✓ Coleção verificada: {info}")
    
    print("\n✓ Teste concluído com sucesso!")
    
except Exception as e:
    print(f"\n✗ Erro: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
