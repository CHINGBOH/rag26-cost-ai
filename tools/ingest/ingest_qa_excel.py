#!/usr/bin/env python3
"""
Ingest Q&A test questions from Excel:
1. Insert as text_chunks (type='qa_question') into PostgreSQL
2. Export as JSON evaluation set for RAGAS
"""
import os
import json
import psycopg2
import openpyxl
from pathlib import Path

DB_CONFIG = dict(host='localhost', dbname='rag_db', user='rag_user', password=os.environ.get('POSTGRES_PASSWORD', 'rag_password'))
EXCEL_PATH = Path('/home/l/rag-dashboard/data/knowledge_base/智能体问答.xlsx')
EVAL_OUTPUT = Path('/home/l/rag-dashboard/data/eval/golden_test_set.json')

# Intent classification for each question (manual annotation)
INTENT_MAP = {
    '01': 'standard_ref',     # 计算规则
    '02': 'price',            # 人工费
    '03': 'comparison',       # 价格对比
    '04': 'trend_chart',      # 价格走势
    '05': 'price',            # 价格查询
    '06': 'standard_ref',     # 费用组成
    '07': 'standard_ref',     # 填写要求
    '08': 'price',            # 费率查询
    '09': 'semantic',         # 政策解读
    '10': 'semantic',         # 计算基数
    '11': 'standard_ref',     # 定额标准
    '12': 'comparison',       # 版本对比
    '13': 'calculation',      # 计算题
    '14': 'calculation',      # 计算题
    '15': 'price',            # 价格查询
    '16': 'comparison',       # 变化幅度
}

# Ground truth answers (partial, for reference)
# Will be populated by actual RAG system runs
KNOWN_ANSWERS = {
    '15': '中砂价格约为 90~100 元/m³（2026年1月深圳信息价）',
    '08': '房建工程赶工措施费推荐系数为 0.5%~1.5%',
}


def main():
    print('Loading Excel Q&A file...')
    wb = openpyxl.load_workbook(EXCEL_PATH, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))

    questions = []
    for row in rows[1:]:  # Skip header
        if not row or not row[0]:
            continue
        seq_no = str(row[0]).strip().zfill(2)
        module = str(row[1]).strip() if row[1] else 'RAG智能问答'
        question = str(row[2]).strip() if row[2] else ''
        if not question:
            continue
        questions.append({
            'id': seq_no,
            'module': module,
            'question': question,
            'intent': INTENT_MAP.get(seq_no, 'semantic'),
            'ground_truth': KNOWN_ANSWERS.get(seq_no, None),
        })

    print(f'Loaded {len(questions)} questions')

    # Insert into PostgreSQL as special document + text_chunks
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # Register Q&A as a document
    cur.execute("""
        INSERT INTO documents (file_name, file_path, doc_type, status, doc_code)
        VALUES (%s, %s, 'qa_set', 'imported', 'qa_test_set_v1')
        ON CONFLICT (doc_code) DO UPDATE SET status='imported'
        RETURNING id
    """, ('智能体问答.xlsx', str(EXCEL_PATH), ))
    qa_doc_id = cur.fetchone()[0]
    print(f'Q&A document registered: id={qa_doc_id}')

    # Insert each question as a text chunk
    for i, q in enumerate(questions):
        content = f"问题{q['id']}: {q['question']}"
        cur.execute("""
            INSERT INTO text_chunks
                (document_id, page_number, chunk_index, content, chunk_type, confidence)
            VALUES (%s, %s, %s, %s, 'qa_question', 1.0)
            ON CONFLICT DO NOTHING
        """, (qa_doc_id, 1, i, content))

    conn.commit()
    print(f'Inserted {len(questions)} Q&A chunks into text_chunks')

    cur.close()
    conn.close()

    # Export evaluation set JSON
    EVAL_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    eval_set = {
        'version': '1.0',
        'description': '深圳建设工程智能问答评估集',
        'total': len(questions),
        'questions': questions,
    }
    with open(EVAL_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(eval_set, f, ensure_ascii=False, indent=2)
    print(f'Evaluation set saved to: {EVAL_OUTPUT}')

    # Print summary
    from collections import Counter
    intent_counts = Counter(q['intent'] for q in questions)
    print('\nIntent distribution:')
    for intent, cnt in sorted(intent_counts.items()):
        print(f'  {intent}: {cnt}')


if __name__ == '__main__':
    main()
