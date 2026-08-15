## Plan: Milvus Graph Topology Detailed Execution

Refine the four-layer retrieval plan into four execution-ready artifacts: a data-layer checklist, a runtime-layer checklist, a validation-layer checklist, and a separate topology schema plus traversal policy design. Recommended approach: treat PostgreSQL as truth and topology metadata owner, Milvus as dense vector recall owner, concept graph as routing substrate, and topology as a bounded traversal mode inside the runtime rather than a separate truth store.

**Steps**
1. Produce three execution checklists with explicit sequencing, dependencies, and acceptance criteria: Data Layer, Runtime Layer, and Validation Layer.
2. Produce a separate detailed design draft for topology schema and traversal policy, including node model, edge model, anchor model, traversal limits, fallback rules, and runtime state contract.
3. Keep all implementation additive-first and feature-flagged so the legacy route remains available until the new route proves safer on benchmarks.

**Data Layer Checklist**
1. Freeze source-of-truth ownership.
Depends on nothing.
PostgreSQL owns document metadata, text chunks, price records, fee rates, trend points, concept graph tables, topology metadata, and evidence links. Milvus owns only derived dense vector indexes. No business truth is allowed to live only in Milvus.
2. Audit live schema and drift.
Depends on 1.
Verify live columns and indexes for text_chunks, price_records, fee_rates, trend_points, canonical_concepts, concept_relations, concept_evidence_links, chunk_vector_views, and document_registry. Resolve mismatches between runtime assumptions and schema references before adding any new route logic.
3. Normalize hierarchy metadata on document evidence.
Depends on 2.
Ensure text_chunks or an adjacent topology table can expose path, path_key, parent_path_key, book_code, chapter_code, section_code, clause_code, depth, sibling_rank, scope_kind, and parent_page_number. This is the minimum metadata needed for topology-aware routing and path-constrained retrieval.
4. Normalize entity and concept keys.
Depends on 2.
Add or backfill stable names for material, specification, fee item, rule item, and formula item. Maintain canonical names, aliases, and concept types in the concept graph so graph entry does not depend on raw OCR strings.
5. Partition evidence by retrieval role.
Depends on 3 and 4.
Define which rows are exact structured truth, which are clause-bearing text evidence, which are semantic chunk evidence, and which are topology metadata only. This separation is required so the runtime can prefer SQL truth over vector similarity when the query family requires precision.
6. Define the Milvus collection strategy.
Depends on 1 and 5.
Start with one primary collection for chunk embeddings and one optional collection for parent or multi-vector views. Delay concept-vector collections unless graph entry recall proves too weak. Required metadata fields in Milvus should include doc_id, file_name, page_number, path, path_key, chapter_code, section_code, chunk_type, source_kind, and collection_role.
7. Define the sync pipeline contract.
Depends on 6.
The sync chain must be PostgreSQL raw evidence -> embedding generation -> Milvus upsert. Graph build remains PostgreSQL raw evidence -> canonical_concepts / concept_relations / concept_evidence_links. No reverse sync from Milvus into PostgreSQL.
8. Define backfill and reconciliation flow.
Depends on 3, 4, and 7.
Add a controlled backfill plan for hierarchy metadata, canonical aliases, concept links, and Milvus collections. Include idempotent rerun behavior and orphan cleanup for deleted or replaced chunks.
9. Add data-layer performance surfaces.
Depends on 3, 4, and 6.
Add or verify indexes for exact price lookup, scoped clause filtering, concept-to-evidence lookup, and hierarchy path filtering in PostgreSQL. Milvus index settings should be documented but tuned later during validation.
10. Keep rollback-safe migration rules.
Depends on 2 through 9.
All new columns, tables, and collections must be additive. Legacy pgvector or old retrieval metadata can remain during transition until the new route is validated.

**Data Layer Files**
- /home/l/rag-dashboard/src/database/schema.sql — primary schema source for hierarchy metadata, concept graph tables, and derived evidence structures.
- /home/l/rag-dashboard/src/database/scripts/build_concept_graph.py — graph build pipeline to expand into topology-aware concept and evidence linking.
- /home/l/rag-dashboard/src/database/scripts/build_chunk_vector_views.py — source for parent or multi-vector view generation before Milvus sync.
- /home/l/rag-dashboard/src/database/scripts/run_full_ocr_embedding_pipeline.py — orchestration point for OCR, embeddings, graph build, and future Milvus sync.
- /home/l/rag-dashboard/src/database/scripts/verify.py — verification surface for hierarchy fields, embedding coverage, graph coverage, and collection health.

**Data Layer Acceptance**
1. All runtime-required hierarchy fields either exist live or have a documented additive migration and backfill path.
2. Every query-relevant evidence row belongs to one dominant retrieval role: structured truth, clause text, semantic chunk, or topology metadata.
3. Milvus collection metadata is sufficient to support runtime filtering without asking Milvus to become the source of truth.
4. Re-running ingestion and sync does not create orphaned graph links or stale vector entries.

**Runtime Layer Checklist**
1. Freeze route taxonomy.
Depends on Data Layer 1 and 5.
The runtime must explicitly distinguish sql, vector, graph, and topology routes. Every tool output and every decision step must record which route was chosen.
2. Upgrade vector backend abstraction.
Depends on Data Layer 6.
Use the existing vector store abstraction as the control surface. Add Milvus as a first-class backend and preserve pgvector only as fallback or transitional backend.
3. Reassign vector responsibilities.
Depends on Runtime 2.
vector_search should become backend-driven and Milvus-first when enabled. The dense leg of hybrid_search should follow the same abstraction. keyword, full-text, exact SQL, and clause routing remain PostgreSQL-driven.
4. Promote graph route into a real entry surface.
Depends on Data Layer 4.
graph_search should return concept anchors, concept confidence, preferred downstream route, direct evidence links, and routeable metadata. It must not behave like a generic dense search.
5. Introduce topology route as a separate tool and state transition.
Depends on Data Layer 3 and Runtime 4.
topology_search should accept an anchor plus bounded traversal policy and return expansion results with graph_depth, anchor lineage, path context, and stop reason metadata.
6. Rewrite navigator around topology anchors.
Depends on Data Layer 3 and Runtime 5.
The navigator should no longer be a flat title matcher only. It should emit roadmap entries with anchor_id, anchor_type, path, path_key, parent_id, sibling_rank, preferred_route, and allowed expansions.
7. Make planner topology-aware.
Depends on Runtime 6.
Planner should interpret the roadmap to decide when to force path-constrained retrieval, when to ask graph first, and when to allow bounded topology expansion. It should not default to unconstrained semantic retrieval once an anchor exists.
8. Bind query families to route policy.
Depends on Runtime 1, 4, and 6.
Price and comparison stay SQL-first. Standard_ref becomes graph plus topology plus scoped text first. Trend stays structured-data-first with vector explanation second. Calculation stays variable-and-rule-first. Semantic fallback is allowed only after primary routes fail or remain incomplete.
9. Extend runtime state.
Depends on Runtime 5 through 8.
Add topology_anchors, active_anchor, explored_anchors, blocked_anchors, topology_history, active_path_constraint, allowed_expansions, route_decision_reason, dominant_uncertainty, and remaining_evidence_gaps.
10. Add topology-aware evaluator and decision node.
Depends on Runtime 9.
The evaluator should score route correctness, path honor, exactness, coverage, missing-variable status, graph confidence, and topology budget usage. The decision node should use those signals to continue, switch route, deepen one hop, or stop.
11. Define bounded fallback rules.
Depends on Runtime 10.
If SQL exact evidence exists, do not jump to vector. If graph anchor exists but direct evidence is missing, allow one topology hop. If topology depth budget is exhausted, do not keep wandering; either escalate to scoped text or stop with explicit insufficiency.
12. Add runtime feature flags.
Depends on Runtime 2 through 11.
At minimum expose enable_milvus_vector, enable_graph_route, enable_topology_route, and enable_topology_depth_2. All flags must be independently disableable.
13. Roll out by route, not by entire system.
Depends on Runtime 12.
Sequence: Milvus for vector_search only, then Milvus in hybrid dense leg, then real graph_search, then topology for standard_ref, then topology for comparison and calculation after the first benchmark gate passes.

**Runtime Layer Files**
- /home/l/rag-dashboard/src/backend/retrieval-service/config/settings.py — backend and feature-flag configuration.
- /home/l/rag-dashboard/src/backend/retrieval-service/infrastructure/vector_store.py — vector backend abstraction and Milvus adapter surface.
- /home/l/rag-dashboard/src/backend/retrieval-service/app/agent/tools.py — main route tools: vector_search, hybrid_search, graph_search, topology_search, text_search, price_query.
- /home/l/rag-dashboard/src/backend/retrieval-service/app/agent/graph.py — navigator, planner, executor, evaluator insertion points, and route selection flow.
- /home/l/rag-dashboard/src/backend/retrieval-service/app/agent/state.py — topology and route-history state model.
- /home/l/rag-dashboard/src/backend/retrieval-service/app/agent/query_analyzer.py — query-family and hierarchy signal extraction.
- /home/l/rag-dashboard/src/backend/retrieval-service/app/agent/evaluator.py — route correctness and bounded traversal evaluation.
- /home/l/rag-dashboard/src/backend/retrieval-service/app/api.py — response metadata and trace surface.

**Runtime Layer Acceptance**
1. Every retrieval result clearly identifies one primary route: sql, vector, graph, or topology.
2. graph_search and topology_search are distinct in purpose and output shape.
3. Query-family route policy is enforceable and does not silently degrade into generic semantic search.
4. Topology traversal is bounded and produces explicit stop reasons.
5. Disabling any new feature flag returns the runtime to a safe legacy path.

**Validation Layer Checklist**
1. Separate result validation from route validation.
Depends on Runtime 1.
Keep answer-shape and refusal checks, but add route-level assertions: chosen path, path constraint honored, topology depth used, and fallback reason.
2. Add data integrity checks before runtime checks.
Depends on Data Layer 2 through 8.
Validate hierarchy fields, concept coverage, evidence-link density, Milvus collection shape, and embedding dimension before judging runtime behavior.
3. Add contract checks for navigator and planner.
Depends on Runtime 6 and 7.
Navigator must output roadmap entries with topology anchors. Planner must either honor those anchors or log an explicit reason for relaxing them.
4. Add tool-level tests.
Depends on Runtime 2 through 5.
Cover Milvus backend selection, vector fallback, graph anchor generation, topology hop metadata, and bounded traversal behavior.
5. Add route-policy tests by query family.
Depends on Runtime 8.
Assert that price and comparison prefer SQL, standard_ref prefers graph/topology, trend prefers structured series, and calculation surfaces missing variables before synthesis.
6. Add evaluator and decision-loop tests.
Depends on Runtime 10 and 11.
Validate that route switching, one-hop topology expansion, and stop decisions follow the declared policy and do not loop indefinitely.
7. Extend benchmark coverage.
Depends on Validation 1 through 6.
Use the current 16-question benchmark as the outer suite and add route assertions, hop-count assertions, and refusal correctness assertions. Standard_ref questions should be the first hard gate for topology behavior. Price and trend questions should be the first hard gate for SQL plus Milvus coexistence.
8. Add observability audits.
Depends on Runtime 12.
Ensure runtime logs or traces record selected route, anchor id, graph depth, path constraint, fallback reason, and stop reason. These traces are required for post-run diagnosis.
9. Define rollout acceptance thresholds.
Depends on Validation 7 and 8.
Do not promote any new route to default unless it matches or exceeds legacy answer safety, reduces refusal ambiguity, and keeps traversal bounded on the benchmark set.
10. Define rollback triggers.
Depends on Validation 9.
If topology route increases loopiness, route confusion, or hallucinated precision, disable topology route or depth 2 first before broader rollback. If Milvus recall quality degrades path selection, disable Milvus vector first while leaving graph and topology intact.

**Validation Layer Files**
- /home/l/rag-dashboard/src/backend/retrieval-service/tests/test_query_analyzer_routing.py — route-policy regression surface.
- /home/l/rag-dashboard/src/backend/retrieval-service/tests/test_contract_verification.py — roadmap and path-honor contract checks.
- /home/l/rag-dashboard/src/backend/retrieval-service/tests/test_convergence_loop.py — bounded decision-loop behavior.
- /home/l/rag-dashboard/src/backend/retrieval-service/tests/test_price_query_text_fallback.py — structured fallback behavior and retrieval path assertions.
- /home/l/rag-dashboard/tests/test_agent_16.py — outer benchmark and refusal audit surface.
- /home/l/rag-dashboard/src/database/scripts/verify.py — substrate verification surface.
- /home/l/rag-dashboard/AGENTS.md — refusal-mode and benchmark-audit constraints.

**Validation Layer Acceptance**
1. Tests validate route behavior, not only answer text.
2. Benchmarks can tell whether topology helped, was skipped, or over-expanded.
3. No new route is promoted without route-level evidence and refusal-mode audit.
4. Rollback triggers are defined before rollout starts.

**Topology Schema + Traversal Policy**
1. Topology purpose.
Topology exists to reduce uncertainty by moving through bounded structural and semantic neighborhoods. It is not a generic graph exploration feature and not a substitute for exact SQL truth.
2. Node model.
Node classes should include document, book, chapter, section, clause_page, concept, material, fee_item, rule_item, formula_item, trend_series, and evidence_chunk. Each node must have a stable node_id, node_type, display_name, normalized_name where applicable, source_table, source_id, path, path_key, parent_id when hierarchical, and metadata.
3. Edge model.
Edge classes should include contains, parent_of, sibling_order, alias_of, variant_of, refers_to, calculated_by, evidenced_by, trend_of, related_to, and scope_applies_to. Every edge should carry edge_type, source_node_id, target_node_id, weight, directionality, and provenance metadata.
4. Anchor model.
Runtime anchor types should include concept anchor, hierarchy anchor, clause anchor, exact-value anchor, and trend anchor. Each anchor must declare anchor_id, anchor_type, preferred_route, confidence, path_context, allowed_expansions, and expiry condition.
5. Topology state contract.
The runtime should persist topology_anchors, active_anchor, explored_anchors, blocked_anchors, topology_history, graph_depth_budget, active_path_constraint, allowed_expansions, fallback_chain, and topology_stop_reason.
6. Traversal primitives.
Supported primitives in the first rollout should be descend_to_child, jump_to_sibling, escalate_to_parent, follow_concept_relation, and follow_evidence_relation. No unrestricted neighbor expansion is allowed.
7. Traversal depth policy.
Default max depth is 1. Depth 2 is optional and flag-guarded. Depth greater than 2 is out of scope for the first production rollout. Depth usage must be logged on every topology result.
8. Expansion policy by query family.
For standard_ref, prefer hierarchy anchor then clause descent then sibling jump then parent escalation. For comparison, start from exact-value anchor or material concept anchor and allow only one additional concept or evidence hop. For calculation, start from rule or fee-item anchor and allow one formula or evidence hop. For trend, use topology only to explain or disambiguate series context after structured series retrieval.
9. Stop policy.
Stop topology traversal immediately when exact SQL truth is found for a precision query, when a clause-bearing answer contract is satisfied for a standard_ref query, when no allowed expansions remain, when depth budget is exhausted, or when the latest hop provides no information gain.
10. Fallback policy.
If graph anchor confidence is weak, fall back to scoped text or keyword retrieval instead of deepening topology. If hierarchy metadata is missing, degrade to graph or scoped text. If Milvus is unavailable, vector fallback returns to pgvector or skips dense recall without invalidating SQL and graph routes.
11. Output contract.
Every topology result should include anchor_id, anchor_type, graph_depth, relation_chain, retrieval_path, evidence_kind, path_context, and stop_reason or next_allowed_expansions. This is required for both debugging and evaluator logic.
12. Safety policy.
Topology must never authorize numeric synthesis by itself. For precise numeric questions it may only help locate missing scope or evidence; the final numeric grounding must still come from structured truth or clearly cited clause evidence.

**Topology Design Acceptance**
1. Node and edge classes are concrete enough to map to current tables and runtime outputs.
2. Traversal rules are bounded, query-family-aware, and auditable.
3. Topology serves uncertainty reduction and scope control, not open-ended graph search.
4. Output metadata is rich enough for evaluator, logs, and benchmark assertions.

**Decisions**
- PostgreSQL remains the owner of topology metadata and concept graph structure in the first rollout.
- Milvus is introduced only as the dense vector layer, not as a truth layer.
- Topology depth is intentionally conservative in the first production plan.
- Standard_ref and clause-heavy queries are the first topology target family.
- The 16-question benchmark remains the outer acceptance surface, but it must be extended to validate path and topology behavior.

**Further Considerations**
1. If hierarchy metadata is incomplete or noisy, create a dedicated topology-backfill phase before enabling topology in the runtime.
2. If concept graph quality is weak, prioritize alias cleanup and evidence-link quality over deeper traversal logic.
3. If Milvus metadata filtering cannot support strict scoping in practice, keep topology-constrained final retrieval in PostgreSQL during the first rollout.

**Execution Envelope**
- Branch: `feature/wo-jiao-er-ha-milvus-topology`
- Issue: `#49` `我叫二哈：Milvus 向量空间 + 图谱/拓扑检索接入 retrieval-service`
- Rollout rule: additive-first, feature-flagged, rollback-safe

**Immediate Execution Order**
1. Extend retrieval-service vector config for Milvus.
2. Add Milvus adapter and backend factory.
3. Wire `vector_search` and the dense leg of `hybrid_search` through the adapter.
4. Restore `graph_search` using existing concept graph helpers.
5. Add `topology_search` with bounded hop metadata.
6. Add focused tests before widening rollout.