import sqlite3
import json

from app.services.onboarding import get_database_path

conn = sqlite3.connect(get_database_path())
conn.row_factory = sqlite3.Row

row = conn.execute(
    "SELECT * FROM repair_history WHERE id = ?",
    (1,),
).fetchone()

if row:
    print("REPAIR HISTORY RECORD")
    print("=====================")
    print("ID:", row["id"])
    print("Config ID:", row["original_config_id"])
    print("Status:", row["status"])
    print("Confidence:", row["confidence"])
    print("Reason:", row["reason"])
    print("Proposed config:", json.loads(row["proposed_config_json"]))
else:
    print("Record not found")

conn.close()