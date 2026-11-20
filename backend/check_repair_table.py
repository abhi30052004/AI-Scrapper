import sqlite3

from app.services.onboarding import (
    initialize_onboarding_db,
    get_database_path,
)

initialize_onboarding_db()

conn = sqlite3.connect(get_database_path())

columns = conn.execute(
    "PRAGMA table_info(repair_history)"
).fetchall()

print("REPAIR HISTORY TABLE COLUMNS")
print("============================")

for column in columns:
    print(column)

conn.close()