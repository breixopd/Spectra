import asyncio
import time
import uuid
import json
from app.services.ai.rag import RAGService, Document, RAGConfig

class MockRedisPipeline:
    def __init__(self):
        self.commands = []

    def hset(self, key, mapping):
        self.commands.append(("hset", key, mapping))

    async def execute(self):
        # Simulate execution
        pass

class MockRedis:
    def __init__(self):
        self.hsets = []

    def ft(self, name):
        class MockInfo:
            async def info(self): return {}
        return MockInfo()

    async def hset(self, key, mapping):
        self.hsets.append((key, mapping))

    def pipeline(self):
        return MockRedisPipeline()

async def main():
    redis = MockRedis()

    config = RAGConfig(index_name="spectra:rag:idx:bench", doc_prefix="spectra:rag:doc:bench:")
    rag = RAGService(redis, config)
    rag._index_exists = True # Skip initialization

    # Create test docs
    num_docs = 10000
    docs = []
    for i in range(num_docs):
        docs.append(Document(
            id=f"bench-{uuid.uuid4()}",
            content=f"This is a test document number {i} for benchmarking the index_batch method in RAG.",
            doc_type="knowledge"
        ))

    print(f"Benchmarking pipeline preparation with {num_docs} documents...")

    # Mock embeddings to isolate pipelining performance
    class MockEmbeddingService:
        async def embed_batch(self, contents):
            # return fake embeddings (384 floats)
            return [[0.1]*384 for _ in contents]

    rag.embeddings = MockEmbeddingService()

    start_time = time.time()
    await rag.index_batch(docs)
    end_time = time.time()

    print(f"Time taken to prepare pipeline: {end_time - start_time:.4f} seconds")

if __name__ == "__main__":
    asyncio.run(main())
