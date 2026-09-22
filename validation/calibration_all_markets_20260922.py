"""
validation/calibration_all_markets_20260922.py - ЧАСТ Д на ZADACHA_PAZARI.md.
САМО измерване, нищо живо не се сменя.

Днес "обещахме X%, познахме Y%" (/prognozi) = evaluation.summary() -> по
ЕДНА избрана прогноза на мач (published_picks / top_pick_for_match). След
ЧАСТ Б страницата на мача показва всички публикуеми пазари. Тук: същата
калибрация, но върху ВСИЧКО, което картата на мача би показала за уредените
мачове - web/prognozi.build_market_sections() върху логнатите редове (същия
филтър: publishable, <95%, пълен пазар, сбор 97-103%).

Три изгледа:
  1. всички изходи (всеки изход на всеки показан пазар е наблюдение);
  2. по един изход на пазар - най-високият процент (фаворитът на пазара);
  3. калибрационни ленти (evaluation.DEFAULT_BANDS) - обещано срещу
     познато по ленти, общо и по група.

Внимание: доверието (policy) е ДНЕШНОТО, приложено назад - не непременно
това, което е било публикувано в деня на мача.

Употреба: venv/bin/python3 validation/calibration_all_markets_20260922.py
Пише validation/calibration_all_markets_20260922.csv
"""
import csv
import sys

sys.path.insert(0, ".")
import system_tracker as st
import prediction_policy as policy
import pick_selection as ps
import evaluation
from web.prognozi import build_market_sections


def brier(obs):
    return sum((o["pct"] / 100.0 - o["won"]) ** 2 for o in obs) / len(obs) if obs else None


def stats(obs):
    if not obs:
        return {"n": 0, "promised": None, "actual": None, "brier": None}
    return {"n": len(obs),
            "promised": sum(o["pct"] for o in obs) / len(obs),
            "actual": 100.0 * sum(o["won"] for o in obs) / len(obs),
            "brier": brier(obs)}


def main():
    rows = st.list_predictions()
    current = evaluation.summary(rows, policy)

    by_fx = {}
    for r in rows:
        by_fx.setdefault(r["fixture_id"], []).append(r)

    all_obs, fav_obs = [], []
    n_matches = 0
    for fixture_id, fx_rows in by_fx.items():
        status_by_code = {r["market_code"]: r["status"] for r in fx_rows}
        if not any(s in ("won", "lost") for s in status_by_code.values()):
            continue
        league = fx_rows[0]["league"]
        sections = build_market_sections(fx_rows, league, policy, ps.MAX_PUBLISHABLE_PCT, "домакин", "гост")
        counted = False
        for sec in sections:
            for market in sec["markets"]:
                if not all(status_by_code.get(o["code"]) in ("won", "lost") for o in market):
                    continue
                obs = [{"group": sec["title"], "code": o["code"], "pct": o["pct"],
                        "won": 1 if status_by_code[o["code"]] == "won" else 0,
                        "fixture_id": fixture_id, "league": league} for o in market]
                all_obs.extend(obs)
                fav_obs.append(max(obs, key=lambda o: o["pct"]))
                counted = True
        n_matches += counted

    groups = []
    for o in all_obs:
        if o["group"] not in groups:
            groups.append(o["group"])

    out = []
    print(f"СЕГА (/prognozi, една прогноза на мач): n={current['n_settled']}, "
          f"обещахме {current['promised_avg']:.1f}%, познахме {current['actual_pct']:.1f}%, "
          f"Brier {current['brier']:.4f}\n")
    print(f"ВСИЧКО ПУБЛИКУЕМО: {n_matches} уредени мача, {len(fav_obs)} пазара, {len(all_obs)} изхода\n")
    print(f"{'група':<26} {'изгл.':<8} {'n':>6} {'обещ.%':>7} {'позн.%':>7} {'Brier':>7}")
    for g in groups + ["ОБЩО"]:
        for view, src in (("всички", all_obs), ("фаворит", fav_obs)):
            obs = [o for o in src if g == "ОБЩО" or o["group"] == g]
            s = stats(obs)
            print(f"{g:<26} {view:<8} {s['n']:>6} {s['promised']:>7.1f} {s['actual']:>7.1f} {s['brier']:>7.4f}")
            out.append({"kind": "summary", "group": g, "view": view, "band": "", **s})

    print("\nКалибрационни ленти (фаворитът на всеки пазар / всички изходи):")
    for view, src in (("фаворит", fav_obs), ("всички", all_obs)):
        for g in ["ОБЩО"] + groups:
            obs_g = [o for o in src if g == "ОБЩО" or o["group"] == g]
            for lo, hi in evaluation.DEFAULT_BANDS:
                band = [o for o in obs_g if lo <= o["pct"] < hi]
                if not band:
                    continue
                s = stats(band)
                if g == "ОБЩО":
                    print(f"  {view:<8} {lo:>3}-{hi:<3}% n={s['n']:>5} обещ. {s['promised']:5.1f}% позн. {s['actual']:5.1f}%")
                out.append({"kind": "band", "group": g, "view": view, "band": f"{lo}-{hi}", **s})

    # сегашните ленти за сравнение
    for b in current["calibration"]:
        out.append({"kind": "band_current_top_pick", "group": "ОБЩО", "view": "топ прогноза",
                    "band": f"{b['lo']}-{b['hi']}", "n": b["n"], "promised": b["promised"],
                    "actual": b["actual"], "brier": None})
    out.append({"kind": "summary_current_top_pick", "group": "ОБЩО", "view": "топ прогноза", "band": "",
                "n": current["n_settled"], "promised": current["promised_avg"],
                "actual": current["actual_pct"], "brier": current["brier"]})

    with open("validation/calibration_all_markets_20260922.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["kind", "group", "view", "band", "n", "promised", "actual", "brier"])
        w.writeheader()
        for r in out:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
    print("\nЗаписано: validation/calibration_all_markets_20260922.csv")


if __name__ == "__main__":
    main()
