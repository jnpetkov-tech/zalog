import sqlite3

conn = sqlite3.connect("bets.db")
conn.row_factory = sqlite3.Row

# намираме дубликати: еднакви fixture_id + market_code + combo_id (третираме NULL правилно)
rows = conn.execute("SELECT * FROM bets ORDER BY id ASC").fetchall()

seen = {}
to_delete = []

for row in rows:
    key = (row["fixture_id"], row["market_code"], row["combo_id"])
    if key in seen:
        to_delete.append(row["id"])
    else:
        seen[key] = row["id"]

print(f"Намерени {len(to_delete)} дублирани реда за изтриване: {to_delete}")

if to_delete:
    conn.executemany("DELETE FROM bets WHERE id=?", [(i,) for i in to_delete])
    conn.commit()
    print("Изтрити успешно.")
else:
    print("Няма дубликати.")

conn.close()
