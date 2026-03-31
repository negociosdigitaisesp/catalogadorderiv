import glob
import psycopg2

conn = psycopg2.connect("postgresql://postgres:1CIwYGQv09MUQA@db.ypqekkkrfklaqlzhkbwg.supabase.co:5432/postgres")
conn.autocommit = True
cur = conn.cursor()

for f in sorted(glob.glob("sql/*.sql")):
    if f.split('\\')[-1].startswith(('03','04','05','06','07','08','09','10')):
        print(f"Applying {f}...")
        try:
            cur.execute(open(f, encoding='utf-8').read())
        except Exception as e:
            print(f"FAILED on {f}: {e}")
