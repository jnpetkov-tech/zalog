"""ZADACHA_XG.md, ЧАСТ А (23.09.2026) - преброяване на наличните данни по лига.

Само чете {лига}_merged_full.csv - нула API заявки.

Броим върху ЗАВЪРШЕНИТЕ мачове (home_goals и away_goals не са празни - същият
критерий като fl.fit_goals_model()). Поле се брои като "попълнено" в даден мач,
ако И ДВЕТЕ колони home_/away_ имат стойност.

Особеност на червените картони: API-Football връща null (не 0), когато
отборът няма червен картон. Затова "red_raw" (суровото попълване) почти винаги
е ниско, дори когато статистиката за мача е пълна. Показваме и
"red_if_stats" - % мачове, за които има статистика (yellow или shots попълнени),
т.е. за които празното red може да се чете като 0. ЧАСТ В решава кое от двете
важи - тук само броим.

Изход: validation/data_inventory_20260923.csv и .md
"""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEAGUES = ["bulgaria", "england", "germany", "spain", "france", "champions_league",
           "europa_league", "conference_league", "italy", "portugal", "france2", "spain2",
           "italy2", "portugal2", "bulgaria2", "england2", "germany2"]
FIELDS = ["xg", "shots", "shots_on_goal", "possession", "fouls", "yellow", "red",
          "offsides", "corners", "injuries"]
TAG = "20260923"


def both(df, f):
    h, a = f"home_{f}", f"away_{f}"
    if h not in df.columns or a not in df.columns:
        return pd.Series(False, index=df.index)
    return df[h].notna() & df[a].notna()


def any_side(df, f):
    h, a = f"home_{f}", f"away_{f}"
    if h not in df.columns or a not in df.columns:
        return pd.Series(False, index=df.index)
    return df[h].notna() | df[a].notna()


def main():
    rows = []
    for lg in LEAGUES:
        df = pd.read_csv(os.path.join(ROOT, f"{lg}_merged_full.csv"))
        df["date"] = pd.to_datetime(df["date"].astype(str).str[:10])
        fin = df.dropna(subset=["home_goals", "away_goals"])
        n = len(fin)
        r = {"league": lg, "matches": n,
             "first_date": fin["date"].min().date() if n else None,
             "last_date": fin["date"].max().date() if n else None}
        for f in FIELDS:
            r[f"{f}_pct"] = round(100 * both(fin, f).mean(), 1) if n else 0.0
        stats_row = both(fin, "yellow") | both(fin, "shots")
        r["red_any_pct"] = round(100 * any_side(fin, "red").mean(), 1) if n else 0.0
        r["red_if_stats_pct"] = round(100 * stats_row.mean(), 1) if n else 0.0
        xg_ok = both(fin, "xg")
        r["xg_first_date"] = fin.loc[xg_ok, "date"].min().date() if xg_ok.any() else None
        # покритие на xG от първата дата, на която е наличен, нататък
        if xg_ok.any():
            since = fin[fin["date"] >= fin.loc[xg_ok, "date"].min()]
            r["xg_pct_since_first"] = round(100 * both(since, "xg").mean(), 1)
        else:
            r["xg_pct_since_first"] = 0.0
        r["has_injuries_col"] = "home_injuries" in df.columns
        rows.append(r)

    out = pd.DataFrame(rows)
    csv_path = os.path.join(ROOT, "validation", f"data_inventory_{TAG}.csv")
    out.to_csv(csv_path, index=False)

    lines = [f"# Преброяване на данните по лига - {TAG}", "",
             "ZADACHA_XG.md, ЧАСТ А. Генерирано от `validation/data_inventory_20260923.py`",
             "(само чете `{лига}_merged_full.csv`, нула API заявки).", "",
             "Всички проценти са от **завършените** мачове (голове попълнени). Поле се брои",
             "като попълнено, ако и домакинът, и гостът имат стойност.", "",
             "- `red` = сурово попълване (и двете страни). API-Football връща празно вместо 0,",
             "  когато няма червен картон, затова е ниско дори при пълна статистика.",
             "- `red_any` = поне едната страна попълнена (= в мача ИМА червен картон, по данни).",
             "- `стат.` = % мачове с налична статистика (жълти или удари) - за тях празното red",
             "  може да се чете като 0.",
             "- `xG от` = първата дата с xG; `xG след` = % покритие с xG от тази дата нататък.", ""]
    hdr = ["лига", "мачове", "xG", "удари", "в целта", "владение", "фалове", "жълти", "red",
           "red_any", "стат.", "засади", "корнери", "контузии", "xG от", "xG след"]
    lines.append("| " + " | ".join(hdr) + " |")
    lines.append("|" + "---|" * len(hdr))
    for r in rows:
        lines.append("| " + " | ".join(str(x) for x in [
            r["league"], r["matches"], r["xg_pct"], r["shots_pct"], r["shots_on_goal_pct"],
            r["possession_pct"], r["fouls_pct"], r["yellow_pct"], r["red_pct"], r["red_any_pct"],
            r["red_if_stats_pct"], r["offsides_pct"], r["corners_pct"], r["injuries_pct"],
            r["xg_first_date"], r["xg_pct_since_first"]]) + " |")
    md_path = os.path.join(ROOT, "validation", f"data_inventory_{TAG}.md")
    with open(md_path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
