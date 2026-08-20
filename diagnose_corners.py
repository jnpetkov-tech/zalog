import pandas as pd

df = pd.read_csv("bulgaria_merged_full.csv")
test_df = df.dropna(subset=["home_corners", "away_corners"])
test_df = test_df[test_df["season"] == 2025]

total_corners = test_df["home_corners"] + test_df["away_corners"]
print("Разпределение на общите корнери в тестовия сезон:")
print(total_corners.describe())
print()
print(f"Мачове с over 9.5: {(total_corners > 9.5).sum()} от {len(total_corners)} ({(total_corners > 9.5).mean()*100:.1f}%)")
print(f"Мачове с under 9.5: {(total_corners <= 9.5).sum()} от {len(total_corners)} ({(total_corners <= 9.5).mean()*100:.1f}%)")
print()
print("Ако винаги гадаем мнозинството клас, точността би била:", 
      round(max((total_corners > 9.5).mean(), (total_corners <= 9.5).mean())*100, 1), "%")
