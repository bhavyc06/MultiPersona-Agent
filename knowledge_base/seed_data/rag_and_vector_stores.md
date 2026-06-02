# RAG and Vector Store Patterns

## Retrieval-Augmented Generation Overview

Retrieval-Augmented Generation (RAG) grounds language model outputs in external knowledge by retrieving relevant documents at inference time. The standard pipeline: user query → embed query → vector search → retrieve top-k chunks → inject into LLM context → generate answer. This reduces hallucination, enables knowledge updates without retraining, and provides citation capability.

The quality ceiling of a RAG system is its retrieval quality. A model cannot compensate for missing or irrelevant retrieved context. Optimizing retrieval—chunking, embedding quality, search strategy, reranking—typically delivers larger gains than switching LLM versions.

Hybrid search combines dense retrieval (semantic similarity via embeddings) with sparse retrieval (BM25 keyword matching). Dense retrieval excels at semantic similarity and paraphrase matching. Sparse retrieval excels at exact-match terms, product codes, and rare proper nouns. Reciprocal Rank Fusion (RRF) merges dense and sparse ranked lists effectively. Most production RAG systems use hybrid search.

## Chunking Strategies

Chunking divides documents into segments for embedding. The right chunk size balances context (larger chunks provide more context per retrieval) and precision (smaller chunks improve retrieval relevance for specific queries). Common sizes: 256-512 tokens for Q&A, 512-1024 tokens for document summarization tasks.

Fixed-size chunking splits at a token or character count. Simple but ignores semantic boundaries—may split mid-sentence or mid-concept. Sentence-based chunking respects linguistic structure but produces variable-length chunks. Recursive character splitting (LangChain's default) tries larger separators first (`\n\n`, `\n`, ` `) then falls back to character splitting if chunks remain too large.

Semantic chunking embeds candidate sentences and splits where embedding cosine distance spikes—indicating a topic change. More computationally expensive but produces semantically coherent chunks. Small-to-big chunking stores small child chunks (for precision) linked to large parent chunks (for context); retrieve by child, return parent.

Overlap between chunks (e.g., 10-20% repeat) ensures that content at chunk boundaries appears in at least two chunks, improving retrieval recall for queries spanning a boundary.

## Embedding Models

Sentence-transformers models (SBERT) produce dense embeddings optimized for semantic similarity. `all-MiniLM-L6-v2` (384 dimensions, 22M parameters) delivers strong performance with fast inference. `all-mpnet-base-v2` (768 dimensions) improves quality at 3x the size. `e5-large-v2` and `bge-large-en-v1.5` achieve state-of-the-art retrieval performance on BEIR benchmarks.

OpenAI `text-embedding-3-small` (1536 dimensions) and `text-embedding-3-large` (3072 dimensions) offer high quality via API. ADA-002 is legacy but still widely deployed. Proprietary APIs add latency and cost; self-hosted sentence-transformers models are faster and cheaper at scale.

Embedding normalization is important: normalized vectors enable cosine similarity via dot product, which is faster than full cosine computation. Most vector databases expect normalized embeddings. Verify normalization before indexing.

## Reranking

Cross-encoder rerankers score query-document pairs jointly (unlike bi-encoder models that encode independently). The joint scoring captures fine-grained interaction between query and passage terms, producing significantly better relevance scores. `ms-marco-MiniLM-L-6-v2` is a widely-used cross-encoder trained on MS MARCO passage retrieval.

The standard RAG pipeline: retrieve top-20 via vector search, rerank with cross-encoder, take top-5. The initial retrieval is cheap (embedding comparison); the expensive cross-encoder runs only on the small candidate set. This staged retrieval balances recall (wide initial search) and precision (reranking).

Cohere Rerank API provides a hosted reranker. For on-premise or cost-sensitive deployments, sentence-transformers cross-encoders run efficiently on CPU for small candidate sets.

## Vector Database Selection

ChromaDB: embedded, in-process, no infrastructure required. Ideal for development and single-server deployments. Supports cosine, L2, and IP distance metrics. Persistent client uses SQLite + HNSW index on disk. Not suitable for multi-node horizontal scaling.

Pinecone: fully managed, serverless, scales automatically. Metadata filtering integrated into vector search. Managed upgrades and backups. Cost: ~$0.08/GB/month for pod-based, usage-based for serverless. Best for production SaaS workloads where operational simplicity is prioritized.

Qdrant and Weaviate: open source, deployable on Kubernetes, support multi-node sharding. Qdrant's Rust implementation delivers high throughput. Weaviate offers native GraphQL API and built-in text chunking. Both support filtering on payload/metadata during vector search without post-filtering.

pgvector: PostgreSQL extension adding a `vector` type and HNSW/IVFFlat indexes. Enables storing vectors alongside relational data. Ideal for teams already operating PostgreSQL who want to avoid a separate vector store. Performance is lower than specialized databases at large scale (>10M vectors).
