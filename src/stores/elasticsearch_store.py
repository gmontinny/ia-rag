from typing import Dict
from elasticsearch import Elasticsearch


class ElasticsearchStore:
    def __init__(self, url: str, index: str):
        self.client = Elasticsearch(url)
        self.index = index

    def ensure_index(self):
        if not self.client.indices.exists(index=self.index):
            self.client.indices.create(
                index=self.index,
                mappings={
                    "properties": {
                        "title": {"type": "text"},
                        "content": {"type": "text"},
                        "source_path": {"type": "keyword"},
                        "meta": {"type": "object", "enabled": True},
                    }
                },
            )

    def index_document(self, doc_id: str, body: Dict):
        self.client.index(index=self.index, id=doc_id, document=body, refresh=False)
