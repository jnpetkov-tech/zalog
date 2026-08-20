import pandas as pd

df = pd.read_csv("bulgaria_merged_full.csv")
test_df = df[df["season"] == df["season"].max()]

print("=== ПРОВЕРКА НА NAIVE BASELINE ЗА ВСИЧКИ ПАЗАРИ ===\n")

# BTTS
btts = (test_df["home_goals"] >= 1) & (test_df["away_goals"] >= 1)
print(f"BTTS: Да={btts.mean()*100:.1f}%, Не={(1-btts.mean())*100:.1f}%")
print(f"  Naive baseline: {max(btts.mean(), 1-btts.mean())*100:.1f}%")
print(f"  Нашият резултат беше: 56.1%\n")

# Over/Under 2.5
total_goals = test_df["home_goals"] + test_df["away_goals"]
over = total_goals > 2.5
print(f"O/U 2.5: Over={over.mean()*100:.1f}%, Under={(1-over.mean())*100:.1f}%")
print(f"  Naive baseline: {max(over.mean(), 1-over.mean())*100:.1f}%")
print(f"  Нашият резултат беше: 53.1%\n")

# 1X2
home_win = (test_df["home_goals"] > test_df["away_goals"]).mean()
draw = (test_df["home_goals"] == test_df["away_goals"]).mean()
away_win = (test_df["home_goals"] < test_df["away_goals"]).mean()
print(f"1X2: Дом={home_win*100:.1f}%, Равен={draw*100:.1f}%, Гост={away_win*100:.1f}%")
print(f"  Naive baseline (най-честа categoria): {max(home_win, draw, away_win)*100:.1f}%")
print(f"  Нашият резултат беше: 53.8% (xG модел)\n")

# HT/FT - най-честата конкретна комбинация
def result(h, a):
    if h > a: return "1"
    elif h == a: return "X"
    else: return "2"

test_df = test_df.dropna(subset=["home_ht_goals", "away_ht_goals"])
combos = test_df.apply(lambda r: f"{result(r.home_ht_goals, r.away_ht_goals)}/{result(r.home_goals, r.away_goals)}", axis=1)
print("HT/FT най-чести комбинации:")
print(combos.value_counts(normalize=True).head(5) * 100)
print(f"  Naive baseline (най-честа): {combos.value_counts(normalize=True).max()*100:.1f}%")
print(f"  Нашият резултат беше: 33.0%")
