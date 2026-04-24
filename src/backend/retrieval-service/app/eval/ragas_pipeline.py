#!/usr/bin/env python3
"""
RAGAS Evaluation Pipeline for RAG Dashboard
Runs golden test set questions through the RAG system and scores with RAGAS metrics.

Usage:
  python3 ragas_pipeline.py [--dry-run] [--question-ids 01,02,03]

Metrics:
  - faithfulness: answer supported by retrieved context
  - answer_relevancy: answer addresses the question
  - context_precision: retrieved chunks are relevant
"""
import os
import sys
import json
import uuid
import argparse
import logging
from datetime import datetime
from pathlib import Path

# Add retrieval-service to path
RETRIEVAL_SVC = Path(__file__).parent.parent.parent
sys.path.insert(0, str(RETRIEVAL_SVC))

import psycopg2

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

EVAL_SET_PATH = Path("/home/l/rag-dashboard/data/eval/golden_test_set.json")
DB_CONFIG = dict(host="localhost", dbname="rag_db", user="rag_user", password=os.environ.get("POSTGRES_PASSWORD", "rag_password"))

LLM_URL = os.environ.get("LLM_URL", "http://127.0.0.1:8080/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "no-key")


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def call_rag(question: str, intent: str) -> dict:
    """Call the RAG agent and return answer + retrieved contexts."""
    try:
        from app.agent.graph import get_agent_graph
        from app.agent.state import RAGAgentState

        graph = get_agent_graph()
        config = {"configurable": {"thread_id": f"eval_{uuid.uuid4().hex[:8]}"}}
        initial_state: RAGAgentState = {
            "messages": [],
            "query": question,
            "query_type": intent,
            "sub_queries": [],
            "iterations": 0,
            "max_iterations": 2,
            "retrieved_chunks": [],
            "evaluation": {},
            "final_answer": "",
            "tool_call_cache": {},
            "calculation_inputs": {},
        }
        result = graph.invoke(initial_state, config=config)
        return {
            "answer": result.get("final_answer", ""),
            "contexts": [c.get("content", "") for c in result.get("retrieved_chunks", [])[:5]],
            "chunks_count": len(result.get("retrieved_chunks", [])),
            "query_type": result.get("query_type", intent),
            "iterations": result.get("iterations", 1),
        }
    except Exception as e:
        logger.error(f"RAG call failed: {e}")
        return {"answer": "", "contexts": [], "chunks_count": 0, "query_type": intent, "iterations": 0}


def _strip_for_scoring(text: str) -> str:
    """
    Prepare answer text for scoring:
    1. Remove citation reference section (---\\n**参考来源：**\\n...)
    2. Strip inline citation markers 【...】 and 《...》
    """
    import re
    # Remove citation reference block appended by _format_citations()
    text = re.sub(r"\n?---\n\*\*参考来源：\*\*.*", "", text, flags=re.DOTALL)
    # Strip inline 【...】 markers (e.g. 【tc_6882】 or 【《文件》P5】)
    text = re.sub(r"\u3010[^\u3011]*\u3011", "", text)
    # Strip 《...》 markers
    text = re.sub(r"\u300a[^\u300b]*\u300b", "", text)
    return text


def _tokenize(text: str) -> set:
    """
    Character-level CJK tokenisation.
    Uses [a-zA-Z0-9_]+ (ASCII-only) so digits do NOT absorb adjacent CJK chars.
    e.g. 'P100中楼梯' → {'P100', '中', '楼', '梯'} instead of {'P100中楼梯'}
    """
    import re
    return set(re.findall(r"[\u4e00-\u9fa5]|[a-zA-Z0-9_]+", text))


_STOPS = {"的", "了", "在", "是", "和", "有", "为", "以", "从", "到", "中", "与",
          "P", "p", "第", "页", "根", "据"}


def score_faithfulness(question: str, answer: str, contexts: list[str]) -> float:
    """
    Faithfulness: check if key answer tokens appear in retrieved contexts.
    Uses character-level CJK tokenization to handle Chinese correctly.
    """
    if not answer or not contexts:
        return 0.0
    import re
    combined_ctx = " ".join(contexts)

    answer_clean = _strip_for_scoring(answer)

    answer_words = _tokenize(answer_clean) - _STOPS
    ctx_words    = _tokenize(combined_ctx) - _STOPS

    if not answer_words:
        return 0.5  # can't judge

    # Extract meaningful numbers (exclude 1-digit which are likely noise)
    numbers_in_answer = [n for n in re.findall(r"\d+\.?\d*", answer_clean)
                         if len(n) >= 2]
    numbers_in_context = re.findall(r"\d+\.?\d*", combined_ctx)

    if numbers_in_answer:
        # Number-grounded faithfulness
        matched_nums = sum(1 for n in numbers_in_answer if n in numbers_in_context)
        num_score = matched_nums / len(numbers_in_answer)
        # Also compute word overlap for non-numeric content
        word_overlap = len(answer_words & ctx_words) / len(answer_words)
        return round(0.6 * num_score + 0.4 * min(1.0, word_overlap * 1.5), 4)
    else:
        # Pure text faithfulness via character overlap
        word_overlap = len(answer_words & ctx_words) / len(answer_words)
        return round(min(1.0, word_overlap * 1.5), 4)


def score_answer_relevancy(question: str, answer: str) -> float:
    """Check if answer addresses the question (character-level keyword overlap)."""
    if not answer:
        return 0.0
    answer_clean = _strip_for_scoring(answer)
    q_words = _tokenize(question) - _STOPS
    a_words = _tokenize(answer_clean) - _STOPS
    if not q_words:
        return 0.5
    overlap = len(q_words & a_words) / len(q_words)
    # Mild penalty only for extremely short answers (< 8 chars)
    if len(answer_clean.strip()) < 8:
        return round(overlap * 0.6, 4)
    return round(min(1.0, overlap * 1.5), 4)


def score_context_precision(question: str, contexts: list[str]) -> float:
    """Check how relevant retrieved contexts are to the question (character-level CJK)."""
    if not contexts:
        return 0.0
    _stops_ext = _STOPS | {"要", "按", "照", "什", "么", "吗"}
    q_words = _tokenize(question) - _stops_ext
    if not q_words:
        return 0.5
    scores = []
    for ctx in contexts:
        ctx_words = _tokenize(ctx) - _stops_ext
        overlap = len(q_words & ctx_words) / len(q_words)
        scores.append(min(1.0, overlap * 2))
    return round(sum(scores) / len(scores), 4)


def run_evaluation(questions: list[dict], dry_run: bool = False) -> dict:
    """Run all questions through RAG and score."""
    eval_run_id = f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    conn = get_conn()
    results = []

    logger.info(f"Starting eval run: {eval_run_id}, {len(questions)} questions")

    for i, q in enumerate(questions):
        qid = q["id"]
        question = q["question"]
        intent = q["intent"]
        ground_truth = q.get("ground_truth")

        logger.info(f"[{i+1}/{len(questions)}] Q{qid} ({intent}): {question[:60]}...")

        if dry_run:
            answer = f"[DRY RUN] Mock answer for: {question[:30]}"
            contexts = ["Mock context 1", "Mock context 2"]
            chunks_count = 2
            iterations = 1
        else:
            rag_result = call_rag(question, intent)
            answer = rag_result["answer"]
            contexts = rag_result["contexts"]
            chunks_count = rag_result["chunks_count"]
            iterations = rag_result["iterations"]

        # Score
        faithfulness = score_faithfulness(question, answer, contexts)
        relevancy = score_answer_relevancy(question, answer)
        precision = score_context_precision(question, contexts)
        passed = faithfulness >= 0.5 and relevancy >= 0.4 and precision >= 0.3
        citations_count = answer.count("【") if answer else 0
        sandbox_used = "```python" in answer or "python_eval" in str(answer)

        result = {
            "eval_run_id": eval_run_id,
            "question_id": qid,
            "question": question,
            "intent": intent,
            "answer": answer,
            "contexts": contexts,
            "ground_truth": ground_truth,
            "faithfulness": round(faithfulness, 3),
            "answer_relevancy": round(relevancy, 3),
            "context_precision": round(precision, 3),
            "passed": passed,
            "chunks_count": chunks_count,
            "iterations": iterations,
            "citations_count": citations_count,
            "sandbox_used": sandbox_used,
        }
        results.append(result)

        # Save to DB
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO eval_results
                (eval_run_id, question_id, question, intent, answer, contexts, ground_truth,
                 faithfulness, answer_relevancy, context_precision, passed, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (eval_run_id, qid, question, intent, answer, contexts, ground_truth,
              faithfulness, relevancy, precision, passed,
              f"chunks={chunks_count} iters={iterations}"))
        conn.commit()
        cur.close()

        logger.info(f"  → faithfulness={faithfulness:.2f} relevancy={relevancy:.2f} precision={precision:.2f} {'✓' if passed else '✗'}")

    conn.close()

    # Summary
    passed_count = sum(1 for r in results if r["passed"])
    avg_f = sum(r["faithfulness"] for r in results) / len(results)
    avg_r = sum(r["answer_relevancy"] for r in results) / len(results)
    avg_p = sum(r["context_precision"] for r in results) / len(results)

    summary = {
        "eval_run_id": eval_run_id,
        "total": len(results),
        "passed": passed_count,
        "pass_rate": round(passed_count / len(results), 2),
        "avg_faithfulness": round(avg_f, 3),
        "avg_answer_relevancy": round(avg_r, 3),
        "avg_context_precision": round(avg_p, 3),
        "results": results,
    }

    # Save JSON report
    report_path = Path(f"/home/l/rag-dashboard/reports/{eval_run_id}.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    logger.info(f"\n=== EVAL SUMMARY ({eval_run_id}) ===")
    logger.info(f"Passed: {passed_count}/{len(results)} ({100*passed_count//len(results)}%)")
    logger.info(f"Avg Faithfulness: {avg_f:.3f}")
    logger.info(f"Avg Answer Relevancy: {avg_r:.3f}")
    logger.info(f"Avg Context Precision: {avg_p:.3f}")
    logger.info(f"Report saved: {report_path}")

    return summary


def main():
    parser = argparse.ArgumentParser(description="RAGAS Evaluation Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Skip actual RAG calls")
    parser.add_argument("--question-ids", type=str, help="Comma-separated question IDs to run (e.g., 01,02,15)")
    args = parser.parse_args()

    with open(EVAL_SET_PATH, encoding="utf-8") as f:
        eval_set = json.load(f)

    questions = eval_set["questions"]

    if args.question_ids:
        ids = set(args.question_ids.split(","))
        questions = [q for q in questions if q["id"] in ids]
        logger.info(f"Filtered to {len(questions)} questions: {args.question_ids}")

    if not questions:
        logger.error("No questions found")
        sys.exit(1)

    run_evaluation(questions, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
