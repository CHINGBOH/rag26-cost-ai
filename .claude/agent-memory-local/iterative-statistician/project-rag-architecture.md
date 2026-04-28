---
name: RAG System Architecture Overview
description: Architecture of the construction price RAG system at /home/l/rag-dashboard — agent graph, retrieval pipeline, and uncertainty handling
type: project
---

The construction price consulting RAG system uses a LangGraph-based multi-node agent with the following key components:

**Agent Graph Nodes** (graph.py, ~2771 lines):
1. query_analysis → intent_guard → navigator → planner → executor ↔ tool_node → chapter_resolver → executor → synthesize → presentation_policy → END

**Key Retrieval Tools** (tools.py, ~3836 lines):
- price_query: Exact price lookups from price_records SQL table
- price_trend: Time-series price trends with monthly averages
- concept_search: Concept hit + recursive drill-down to evidence
- hybrid_search: pgvector (ANN) + BM25 full-text fused via RRF
- text_search: Full-text + semantic mixed retrieval with path_constraint
- vector_search: Pure pgvector cosine similarity
- keyword_search: PostgreSQL tsvector/tsquery
- category_search: Catalog index lookup
- rule_clause_search: Scoped clause retrieval within locked doc/page range
- get_catalog_map: Chapter path structure lookup

**Uncertainty Handling Today**:
- SCORE_THRESHOLDS per source_db (pgvector: 0.40, pg_fulltext: 0.01, etc.)
- evaluate_retrieval_quality() in evaluator.py — 7-dim scoring for semantic queries
- _build_answer_evaluation() in graph.py — simplified eval for all query types
- tool_node fallback when effective_new_chunk_count==0 (location-word stripping, tool switching)
- max_iterations gate prevents infinite loops
- Fallback mode tracking (fallback_mode flag)

**ANN + Reranker** (structured_table_gate in tools.py):
- ANN: pgvector embedding <=> operator for top-5 fee_rates candidates
- Reranker: BGE-reranker-v2-m3 cross-encoder scores (query, fee_name+source_text) pairs
- Gate: sigmoid score > 0.5 means relevant
- IVFFlat probes=10 (increased from default 1)

**State** (state.py):
- query, query_type, query_entities, sub_queries, plan, current_step, iterations, max_iterations
- retrieved_chunks, evaluation, final_answer
- roadmap (navigator path_constraint), workspace (cross-chapter evidence pool)
- category_hints, target_doc_id/section/page_start/page_end for scoped retrieval
- fallback_mode for location-word degradation prevention

**Current iteration only handles**: executor ↔ tool_node loop (ReAct pattern) with max_iterations guard. No explicit uncertainty-driven convergence loop exists.
