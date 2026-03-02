import asyncio
import time
import uuid
from app.services.ai.rag import RAGService, Document, RAGConfig

class MockRedisPipeline:
    def __init__(self):
        self.commands = []

    def hset(self, key, mapping):
        self.commands.append(("hset", key, mapping))

    async def execute(self):
        return [1] * len(self.commands)

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

class MockEmbeddingService:
    async def embed_batch(self, contents):
        return [[0.1] * 384 for _ in contents]

class PrecomputedEmbeddings:
    def __init__(self, embeddings):
        self._embeddings = embeddings

    async def embed_batch(self, contents):
        return self._embeddings

async def main():
    redis = MockRedis()

    config = RAGConfig(index_name="spectra:rag:idx:bench", doc_prefix="spectra:rag:doc:bench:")
    rag = RAGService(redis, config)
    rag._index_exists = True  # Skip initialization

    num_docs = 10000
    print(f"Benchmarking index_batch with {num_docs} documents...")

    # 1. Document creation
    t0 = time.time()
    docs = [
        Document(
            id=f"bench-{uuid.uuid4()}",
            content=f"This is a test document number {i} for benchmarking the index_batch method in RAG.",
            doc_type="knowledge",
        )
        for i in range(num_docs)
    ]
    t1 = time.time()
    print(f"  Document creation:    {t1 - t0:.4f}s")

    # 2. Embedding generation (mocked)
    rag.embeddings = MockEmbeddingService()
    t2 = time.time()
    contents = [doc.content for doc in docs]
    embeddings = await rag.embeddings.embed_batch(contents)
    t3 = time.time()
    print(f"  Embedding generation: {t3 - t2:.4f}s  (mocked — {len(embeddings[0])}-dim vectors)")

    # 3. Pipeline enqueue + execute (chunked)
    # Use pre-computed embeddings to isolate pipeline timing from embedding generation
    rag.embeddings = PrecomputedEmbeddings(embeddings)
    t4 = time.time()
    success_count = await rag.index_batch(docs)
    t5 = time.time()
    print(f"  Pipeline enqueue + execute ({config.batch_size} docs/chunk): {t5 - t4:.4f}s")

    print(f"\n  Total:                {t5 - t0:.4f}s  ({success_count}/{num_docs} indexed)")

if __name__ == "__main__":
    asyncio.run(main())
