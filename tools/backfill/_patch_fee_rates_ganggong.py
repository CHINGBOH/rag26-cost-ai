#!/usr/bin/env python3
"""
向 fee_rates 表插入赶工措施费系数数据。
数据来源：深圳市建设工程计价费率标准（2025）表3
"""
import psycopg2

DB = dict(host='localhost', user='rag_user', password='your_password_here', dbname='rag_db')

def run():
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()

    # 检查已有数据
    cur.execute("SELECT id, fee_name, fee_category, rate_min, rate_max, rate_recommended, standard_year FROM fee_rates WHERE fee_name ILIKE '%赶工%'")
    existing = cur.fetchall()
    print("Existing 赶工 rows:", existing)

    if existing:
        print("Already exists, skipping.")
        conn.close()
        return

    # 查找 document_id 19 (费率标准2025)
    cur.execute("SELECT id, doc_code FROM documents WHERE doc_code='fee_rate_2025'")
    doc = cur.fetchone()
    if not doc:
        print("ERROR: document fee_rate_2025 not found")
        conn.close()
        return
    doc_id = doc[0]
    print(f"Using document_id={doc_id}")

    # 插入两行：房建工程 + 市政工程赶工措施费系数
    rows = [
        {
            "doc_code": "fee_rate_2025",
            "document_id": doc_id,
            "standard_year": "2025",
            "fee_name": "赶工措施费",
            "fee_category": "房建工程",
            "base_formula": "赶工措施费=（1－合同工期／定额标准工期－20%）×（人工费+措施项目费）×赶工措施费系数",
            "rate_min": 0.6,
            "rate_max": 1.4,
            "rate_recommended": 1.0,
            "calc_base": "人工费+措施项目费",
            "applicable_scope": "发包人要求合同工期少于定额（标准）工期80%时适用",
            "page_number": None,
            "source_text": "表3赶工措施费系数：房建工程，参考范围0.6～1.4，推荐系数1.0",
            "confidence": 1.0,
        },
        {
            "doc_code": "fee_rate_2025",
            "document_id": doc_id,
            "standard_year": "2025",
            "fee_name": "赶工措施费",
            "fee_category": "市政工程",
            "base_formula": "赶工措施费=（1－合同工期／定额标准工期－20%）×（人工费+措施项目费）×赶工措施费系数",
            "rate_min": 0.6,
            "rate_max": 1.0,
            "rate_recommended": 0.8,
            "calc_base": "人工费+措施项目费",
            "applicable_scope": "发包人要求合同工期少于定额（标准）工期80%时适用",
            "page_number": None,
            "source_text": "表3赶工措施费系数：市政工程，参考范围0.6～1.0，推荐系数0.8",
            "confidence": 1.0,
        },
    ]

    for r in rows:
        cur.execute("""
            INSERT INTO fee_rates
              (doc_code, document_id, standard_year, fee_name, fee_category,
               base_formula, rate_min, rate_max, rate_recommended, calc_base,
               applicable_scope, page_number, source_text, confidence)
            VALUES
              (%(doc_code)s, %(document_id)s, %(standard_year)s, %(fee_name)s, %(fee_category)s,
               %(base_formula)s, %(rate_min)s, %(rate_max)s, %(rate_recommended)s, %(calc_base)s,
               %(applicable_scope)s, %(page_number)s, %(source_text)s, %(confidence)s)
        """, r)
        print(f"Inserted: {r['fee_category']} 推荐系数={r['rate_recommended']}")

    conn.commit()
    conn.close()
    print("Done.")

if __name__ == '__main__':
    run()
