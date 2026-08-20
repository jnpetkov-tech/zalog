import pandas as pd

df = pd.read_csv("bulgaria_merged_full.csv")
df["has_xg"] = df["home_xg"].notna() & df["away_xg"].notna()

print("Разбивка по сезони:")
summary = df.groupby("season")["has_xg"].agg(["sum", "count"])
summary.columns = ["с_валидно_xG", "общо_мачове"]
summary["процент"] = (summary["с_валидно_xG"] / summary["общо_мачове"] * 100).round(1)
print(summary)
