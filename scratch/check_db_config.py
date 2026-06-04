import sqlite3
import os
from pathlib import Path

DB_PATH = Path("d:/IOT/data/smartdoor.db")
if not DB_PATH.exists():
    print("Database file does not exist!")
else:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM config")
    rows = c.fetchall()
    print("=== Config Database Contents ===")
    for row in rows:
        print(f"{row['id']}: {row['val_text']}")
    conn.close()
