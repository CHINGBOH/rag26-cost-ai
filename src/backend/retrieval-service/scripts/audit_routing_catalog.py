#!/usr/bin/env python3
"""
Audit current routing catalog and fallback policy for major query families.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.query_analyzer import QueryAnalyzer


CATALOG = [
    {
        "family": "fee_formula",
        "query": "2025版费率标准中企业管理费的计算公式是什么？",
        "expected_intent": "standard_ref",
        "primary_path": "fee_formula_text -> structured fee chunks",
        "fallback_policy": ["literal_text", "semantic_text_chunks"],
    },
    {
        "family": "fee_range_comparison",
        "query": "2023版与2025版费率标准中，利润率的参考范围是否一致？",
        "expected_intent": "comparison",
        "primary_path": "fee_compare_text -> structured fee chunks",
        "fallback_policy": ["literal_text", "semantic_text_chunks"],
    },
    {
        "family": "monthly_price_lookup",
        "query": "2026年1月，中砂的价格是多少元/m³？",
        "expected_intent": "price",
        "primary_path": "price_query -> price_records",
        "fallback_policy": ["text_material_fallback", "ocr_price_fallback", "semantic_text_chunks"],
    },
    {
        "family": "annual_price_lookup",
        "query": "2025年深圳信息价中钛合金门窗的价格是多少？",
        "expected_intent": "price",
        "primary_path": "price_query -> price_records (annual prune)",
        "fallback_policy": ["text_price_fallback", "semantic_text_chunks"],
    },
    {
        "family": "trend_query",
        "query": "中砂从2026年1月到2月的价格走势如何？",
        "expected_intent": "trend_chart",
        "primary_path": "price_trend -> trend_points / trend_relations",
        "fallback_policy": ["price_records", "text_material_fallback", "ocr_price_fallback"],
    },
    {
        "family": "fill_requirement",
        "query": "工程概况表中的施工地点应按什么要求填写？",
        "expected_intent": "standard_ref",
        "primary_path": "fill_requirement_text",
        "fallback_policy": ["literal_text", "semantic_text_chunks"],
    },
    {
        "family": "appendix_standard",
        "query": "《深圳市装配式建筑评价标准》适用范围是什么？",
        "expected_intent": "standard_ref",
        "primary_path": "appendix_standard_text",
        "fallback_policy": ["literal_text", "semantic_text_chunks"],
    },
]


def main() -> None:
    analyzer = QueryAnalyzer()
    results = []
    for item in CATALOG:
        analysis = analyzer.analyze(item["query"])
        results.append(
            {
                **item,
                "actual_intent": analysis["intent"],
                "entities": analysis["entities"],
                "sub_queries": analysis["sub_queries"],
                "intent_matches": analysis["intent"] == item["expected_intent"],
            }
        )

    print(json.dumps({"families": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
