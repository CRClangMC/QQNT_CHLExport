# run_reindex.py
import sqlite3, sys
p = sys.argv[1]
conn = sqlite3.connect(p)
conn.execute("REINDEX group_msg_table;")
res = conn.execute("PRAGMA integrity_check;").fetchone()
print("integrity_check:", res)
conn.close()