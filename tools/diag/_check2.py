#!/usr/bin/env python3
import psycopg2
DB = dict(host='localhost', user='rag_user', password='your_password_here', dbname='rag_db')
conn = psycopg2.connect(**DB)
cur = conn.cursor()

# chunk 6880 status
cur.execute("SELECT id, embedding IS NOT NULL, tsv IS NOT NULL, chunk_type, doc_type, period, document_id FROM text_chunks WHERE id=6880")
row = cur.fetchone()
print("chunk_6880:", row)

# all chunks from document 19 with 赶工
cur.execute("SELECT id, chunk_index, embedding IS NOT NULL, tsv IS NOT NULL FROM text_chunks WHERE document_id=19 AND content ILIKE '%赶工%'")
rows = cur.fetchall()
print("doc19 赶工 chunks:", rows)

# doc 19 info
cur.execute("SELECT id, file_name, doc_type, period, doc_code FROM documents WHERE id=19")
print("document_19:", cur.fetchone())

# doc 18 info
cur.execute("SELECT id, file_name, doc_type, period, doc_code FROM documents WHERE id=18")
print("document_18:", cur.fetchone())

# fee_rates赶工
cur.execute("SELECT id, standard_year, fee_name, fee_category, rate_min, rate_max, rate_recommended, applicable_scope FROM fee_rates WHERE fee_name ILIKE '%赶工%' OR source_text ILIKE '%赶工%'")
rows = cur.fetchall()
print("fee_rates 赶工:", rows)

# sample fee_rates
cur.execute("SELECT id, standard_year, fee_name FROM fee_rates ORDER BY id LIMIT 10")
rows = cur.fetchall()
print("fee_rates sample:", rows)

# text search test (simulate plainto_tsquery)
cur.execute("SELECT id, content[:100] FROM text_chunks WHERE tsv @@ plainto_tsquery('simple', '赶工措施费') LIMIT 5")
rows = cur.fetchall()
print("tsquery 赶工措施费 matches:", len(rows), rows[:2] if rows else [])

conn.close()
