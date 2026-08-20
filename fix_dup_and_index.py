import sqlite3

conn = sqlite3.connect("predictions.db")

# Изтрий по-новия дубликат (id=29), запази оригинала (id=1)
cur = conn.execute("DELETE FROM predictions_log WHERE id = 29")
print(f"Изтрити редове: {cur.rowcount}")

# Провери, че вече няма дубликати
dups = conn.execute("""
    SELECT COUNT(*) c FROM (
        SELECT fixture_id, market_code, COUNT(*) k
        FROM predictions_log GROUP BY fixture_id, market_code HAVING k > 1
    )
""").fetchone()[0]
print(f"Оставащи дубликати: {dups}")
assert dups == 0, "Все още има дубликати - НЕ добавям индекс"

# Добави UNIQUE индекс
conn.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_predictions_fixture_market
    ON predictions_log(fixture_id, market_code)
""")
conn.commit()

indexes = [r[1] for r in conn.execute("PRAGMA index_list(predictions_log)")]
print(f"Индекси сега: {indexes}")

conn.close()
print("OK - дубликат изтрит, UNIQUE индекс създаден.")
