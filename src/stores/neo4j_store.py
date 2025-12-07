from typing import Optional
from neo4j import GraphDatabase


class Neo4jStore:
    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def ensure_schema(self):
        with self.driver.session() as sess:
            sess.execute_write(
                lambda tx: tx.run("CREATE CONSTRAINT IF NOT EXISTS FOR (l:Law) REQUIRE l.id IS UNIQUE")
            )
            sess.execute_write(
                lambda tx: tx.run("CREATE CONSTRAINT IF NOT EXISTS FOR (a:Article) REQUIRE a.id IS UNIQUE")
            )
            sess.execute_write(
                lambda tx: tx.run("CREATE CONSTRAINT IF NOT EXISTS FOR (p:Paragraph) REQUIRE p.id IS UNIQUE")
            )
            sess.execute_write(
                lambda tx: tx.run("CREATE CONSTRAINT IF NOT EXISTS FOR (i:Inciso) REQUIRE i.id IS UNIQUE")
            )
            sess.execute_write(
                lambda tx: tx.run("CREATE CONSTRAINT IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE")
            )

    def upsert_hierarchy(self, law_id: str, article: Optional[str], paragraph: Optional[str], inciso: Optional[str]):
        with self.driver.session() as sess:
            sess.execute_write(
                lambda tx: tx.run(
                    "MERGE (l:Law {id: $law_id}) RETURN l", law_id=law_id
                )
            )
            last_label = "Law"
            last_id = law_id
            if article:
                art_id = f"{law_id}:Art{article}"
                with self.driver.session() as s2:
                    s2.execute_write(
                        lambda tx: tx.run(
                            "MERGE (a:Article {id: $id, num: $num})\n"
                            "WITH a\n"
                            "MATCH (l:Law {id: $law})\n"
                            "MERGE (l)-[:HAS_ARTICLE]->(a)",
                            id=art_id, num=article, law=law_id,
                        )
                    )
                last_label = "Article"
                last_id = art_id
            if paragraph:
                par_id = f"{law_id}:{article or ''}:Par{paragraph}"
                with self.driver.session() as s3:
                    s3.execute_write(
                        lambda tx: tx.run(
                            "MERGE (p:Paragraph {id: $id, num: $num})\n"
                            "WITH p\n"
                            "MATCH (a:Article {id: $art})\n"
                            "MERGE (a)-[:HAS_PARAGRAPH]->(p)",
                            id=par_id, num=paragraph, art=f"{law_id}:Art{article}" if article else None,
                        )
                    )
                last_label = "Paragraph"
                last_id = par_id
            if inciso:
                inc_id = f"{law_id}:{article or ''}:{paragraph or ''}:Inc{inciso}"
                with self.driver.session() as s4:
                    s4.execute_write(
                        lambda tx: tx.run(
                            "MERGE (i:Inciso {id: $id, num: $num})\n"
                            "WITH i\n"
                            "MATCH (p:Paragraph {id: $par})\n"
                            "MERGE (p)-[:HAS_INCISO]->(i)",
                            id=inc_id, num=inciso, par=f"{law_id}:{article or ''}:Par{paragraph}" if paragraph else None,
                        )
                    )
                last_label = "Inciso"
                last_id = inc_id
            return last_label, last_id

    def attach_chunk(self, parent_id: str, chunk_id: str, text: str, start_char: int, end_char: int):
        with self.driver.session() as sess:
            sess.execute_write(
                lambda tx: tx.run(
                    "MERGE (c:Chunk {id: $id}) SET c.text=$text, c.start=$start, c.end=$end\n"
                    "WITH c\n"
                    "OPTIONAL MATCH (l:Law {id: $parent})\n"
                    "OPTIONAL MATCH (a:Article {id: $parent})\n"
                    "OPTIONAL MATCH (p:Paragraph {id: $parent})\n"
                    "OPTIONAL MATCH (i:Inciso {id: $parent})\n"
                    "FOREACH (_ IN CASE WHEN l IS NOT NULL THEN [1] ELSE [] END | MERGE (l)-[:HAS_CHUNK]->(c))\n"
                    "FOREACH (_ IN CASE WHEN a IS NOT NULL THEN [1] ELSE [] END | MERGE (a)-[:HAS_CHUNK]->(c))\n"
                    "FOREACH (_ IN CASE WHEN p IS NOT NULL THEN [1] ELSE [] END | MERGE (p)-[:HAS_CHUNK]->(c))\n"
                    "FOREACH (_ IN CASE WHEN i IS NOT NULL THEN [1] ELSE [] END | MERGE (i)-[:HAS_CHUNK]->(c))",
                    id=chunk_id, text=text, start=start_char, end=end_char, parent=parent_id,
                )
            )
