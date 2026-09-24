"""
archive/fetch_euro_team_countries_20260924.py - ZADACHA_TRI.md, ЧАСТ В (24.09.2026).

Еднократно: държавата на всеки отбор, играл в евротурнирите (Шампионска лига 2,
Лига Европа 3, Лига на конференциите 848), сезони 2022-2026. 15 заявки към
/teams (по една на турнир x сезон), през api_football._api_get() (rate limiter +
api_calls.log). Изход: euro_team_countries.csv (team, country) в корена - вход за
евро модела в football_lib (fit_euro_model), и копие в validation/ за доказателство.
Пускай наново в началото на всеки сезон (нови отбори в квалификациите); отбор без
държава в файла не гърми - влиза в общата група "?".
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import pandas as pd  # noqa: E402

import api_football as af  # noqa: E402

rows = {}
for lid in (2, 3, 848):
    for season in range(2022, 2027):
        r = af._api_get("/teams", params={"league": lid, "season": season}).json()
        if r.get("errors"):
            print(lid, season, r["errors"])
            continue
        for x in r.get("response", []):
            rows[x["team"]["name"]] = x["team"]["country"]
        print(lid, season, r.get("results"))
out = pd.DataFrame(sorted(rows.items()), columns=["team", "country"])
out.to_csv("euro_team_countries.csv", index=False)
out.to_csv("validation/tri_v_team_countries_20260924.csv", index=False)
print(len(out), "отбора,", out.country.nunique(), "държави")
