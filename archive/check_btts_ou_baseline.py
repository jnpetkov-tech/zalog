import pandas as pd

df = pd.read_csv("bulgaria_merged_full.csv")
test_df = df[df["season"] == df["season"].max()]

btts = (test_df["home_goals"] >= 1) & (test_df["away_goals"] >= 1)
btts_baseline = max(btts.mean(), 1 - btts.mean()) * 100

total_goals = test_df["home_goals"] + test_df["away_goals"]
over = total_goals > 2.5
ou_baseline = max(over.mean(), 1 - over.mean()) * 100

print(f"BTTS naive baseline: {btts_baseline:.1f}%  |  Наш резултат: 56.1%  |  {'РЕАЛНО' if 56.1 > btts_baseline else 'ФАЛШИВО'} подобрение")
print(f"O/U 2.5 naive baseline: {ou_baseline:.1f}%  |  Наш резултат: 53.1%  |  {'РЕАЛНО' if 53.1 > ou_baseline else 'ФАЛШИВО'} подобрение")
