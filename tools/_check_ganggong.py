#!/usr/bin/env python3
"""Check if 赶工措施费 data exists in rag_db, and insert if missing."""
import psycopg2
import json
import sys

DB = dict(host='localhost', user='rag_user', password='your_password_here', dbname='rag_db')

def run():
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()

    # 1. fee_rates columns
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='fee_rates' ORDER BY ordinal_position")
    cols = [r[0] for r in cur.fetchall()]
    print("fee_rates columns:", cols)

    cur.execute("SELECT COUNT(*) FROM fee_rates")
    print("fee_rates total rows:", cur.fetchone()[0])

    # 2. Search for 赶工 in fee_rates
    # Try common column names
    for col in cols:
        try:
            cur.execute(f"SELECT * FROM fee_rates WHERE {col}::text ILIKE '%赶工%' LIMIT 5")
            rows = cur.fetchall()
            if rows:
                print(f"Found 赶工 in column '{col}':", rows[:3])
        except Exception as e:
            pass

    # 3. text_chunks columns
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='text_chunks' ORDER BY ordinal_position")
    chunk_cols = [r[0] for r in cur.fetchall()]
    print("\ntext_chunks columns:", chunk_cols)

    cur.execute("SELECT COUNT(*) FROM text_chunks")
    print("text_chunks total rows:", cur.fetchone()[0])

    # 4. Search text_chunks for 赶工
    cur.execute("SELECT * FROM text_chunks WHERE content ILIKE '%赶工%' LIMIT 5")
    rows = cur.fetchall()
    print(f"\ntext_chunks with 赶工: {len(rows)} rows")
    for r in rows:
        print(" ->", str(r)[:200])

    # 5. documents table
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='documents' ORDER BY ordinal_position")
    doc_cols = [r[0] for r in cur.fetchall()]
    print("\ndocuments columns:", doc_cols)

    cur.execute("SELECT COUNT(*) FROM documents")
    print("documents total rows:", cur.fetchone()[0])

    # documents 18 and 19
    for doc_id in [18, 19]:
        cur.execute("SELECT id, file_name, doc_type, period, doc_code FROM documents WHERE id=%s", (doc_id,))
        row = cur.fetchone()
        print(f"\ndocument {doc_id}:", row)

    # chunk 6880 embedding status
    cur.execute("SELECT embedding IS NOT NULL, tsv IS NOT NULL, chunk_type, doc_type, period FROM text_chunks WHERE id=6880")
    row = cur.fetchone()
    print("\nchunk 6880 has_embedding/tsv/type:", row)

    # fee_rates 赶工数据
    cur.execute("SELECT id, standard_year, fee_name, fee_category, rate_min, rate_max, rate_recommended, applicable_scope FROM fee_rates WHERE fee_name ILIKE '%赶工%' OR fee_category ILIKE '%赶工%'")
    rows = cur.fetchall()
    print(f"\nfee_rates 赶工 rows: {len(rows)}")
    for r in rows:
        print(" ->", r)

    # all fee_rates entries
    cur.execute("SELECT id, standard_year, fee_name, fee_category FROM fee_rates LIMIT 20")
    print("\nAll fee_rates (first 20):")
    for r in cur.fetchall():
        print(" ->", r)

    conn.close()

if __name__ == '__main__':
    run()
