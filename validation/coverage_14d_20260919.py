"""Б2 (ZADACHA_FAZA1.md, 19.09.2026) — покритие за последните 14 дни.

Въпросът: гарантирано ли е, че публичната страница не е празна? Тоест —
от мачовете, които РЕАЛНО са се играли в нашите 17 лиги, за колко изобщо
сме имали прогноза?

Три нива, мерени едно след друго (всяко е подмножество на предното):
  1. РЕАЛНО ИМАЛО      — какво връща API-Football за периода (истината)
  2. ЛОГНАТО           — има поне един ред в predictions_log за този fixture_id
  3. ПОКАЗАНО          — pick_selection.top_pick_for_match() връща прогноза,
                          тоест мачът реално е влизал в "Предстоящи", а не в
                          "Мачове без доверена прогноза"

Разликата 1→2 е загуба при ТЕГЛЕНЕ/ЛОГВАНЕ, разликата 2→3 е загуба във
ФИЛТЪРА ЗА ДОВЕРИЕ. Точно това разделение е въпросът на Дака.

Бюджет: ТОЧНО по една заявка на лига (17 общо) за целия 14-дневен период -
/fixtures приема from/to, не се тегли ден по ден. Всяка минава през
api_football._api_get(), тоест през лимитера И през api_calls.log.

Нищо не се пише в базата, нищо в живия код не се пипа.
"""
import sys, os, ast, json
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import api_football
import system_tracker as st
import prediction_policy as policy
import pick_selection as ps

DAYS = 14
# Мачове, които изобщо не са се играли - не се броят срещу покритието,
# но се отчитат отделно, за да е видно защо знаменателят е такъв.
NOT_PLAYED = {"PST", "CANC", "ABD", "TBD", "SUSP", "AWD", "WO"}


def load_all_leagues():
    """Регистърът на лигите БЕЗ да се внася match_predictor_app (който
    вдига цялото Flask приложение) - чете се литералът от изходния код."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "match_predictor_app.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "ALL_LEAGUES" for t in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError("ALL_LEAGUES не е намерен в match_predictor_app.py")


def fetch_league_fixtures(league_key, league_id, from_date, to_date):
    """ЕДНА заявка на лига за целия период, през _api_get (лимитер + лог)."""
    season = from_date.year if from_date.month >= 7 else from_date.year - 1
    params = {"league": league_id, "season": season,
              "from": from_date.isoformat(), "to": to_date.isoformat(),
              "timezone": "Europe/Sofia"}
    r = api_football._api_get("/fixtures", params=params, timeout=20)
    data = r.json()
    if data.get("errors"):
        return [], f"{data['errors']}"
    return data.get("response", []), None


def main():
    today = date.today()
    from_date = today - timedelta(days=DAYS)
    to_date = today - timedelta(days=1)   # до вчера включително, днес още тече

    all_leagues = load_all_leagues()
    calls_before = api_football.get_call_count()

    # --- всичко от predictions_log, групирано по fixture_id (едно четене) ---
    rows = st.list_predictions()
    logged = defaultdict(list)
    for r in rows:
        logged[r["fixture_id"]].append(r)

    per_league, per_day, errors = {}, defaultdict(lambda: [0, 0, 0]), {}
    gaps = []
    for key, meta in all_leagues.items():
        fixtures, err = fetch_league_fixtures(key, meta["id"], from_date, to_date)
        if err:
            errors[key] = err
        real = logged_n = shown_n = not_played = 0
        for f in fixtures:
            status = f["fixture"]["status"]["short"]
            if status in NOT_PLAYED:
                not_played += 1
                continue
            fid = f["fixture"]["id"]
            day = f["fixture"]["date"][:10]
            real += 1
            per_day[day][0] += 1
            grp = logged.get(fid)
            if grp:
                logged_n += 1
                per_day[day][1] += 1
                if ps.top_pick_for_match(grp, key, policy):
                    shown_n += 1
                    per_day[day][2] += 1
                else:
                    gaps.append({"league": key, "fixture_id": fid, "day": day,
                                 "home": f["teams"]["home"]["name"],
                                 "away": f["teams"]["away"]["name"],
                                 "where": "филтър за доверие"})
            else:
                gaps.append({"league": key, "fixture_id": fid, "day": day,
                             "home": f["teams"]["home"]["name"],
                             "away": f["teams"]["away"]["name"],
                             "where": "няма ред в predictions_log"})
        per_league[key] = {"name": meta["name"], "real": real, "logged": logged_n,
                           "shown": shown_n, "not_played": not_played}

    return {
        "from": from_date.isoformat(), "to": to_date.isoformat(),
        "api_calls": api_football.get_call_count() - calls_before,
        "per_league": per_league,
        "per_day": {d: v for d, v in sorted(per_day.items())},
        "errors": errors,
        "gaps": gaps,
    }


def _pct(a, b):
    return "—" if not b else f"{a / b * 100:.0f}%"


def write_report(res, md_path, csv_path):
    import csv as _csv
    from collections import Counter

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = _csv.writer(f)
        w.writerow(["league", "league_name", "real_played", "logged", "shown",
                    "not_played", "logged_pct", "shown_pct"])
        for k, v in res["per_league"].items():
            w.writerow([k, v["name"], v["real"], v["logged"], v["shown"], v["not_played"],
                        f'{v["logged"] / v["real"] * 100:.1f}' if v["real"] else "",
                        f'{v["shown"] / v["real"] * 100:.1f}' if v["real"] else ""])

    tot_real = sum(v["real"] for v in res["per_league"].values())
    tot_log = sum(v["logged"] for v in res["per_league"].values())
    tot_shown = sum(v["shown"] for v in res["per_league"].values())
    tot_np = sum(v["not_played"] for v in res["per_league"].values())

    L = []
    A = L.append
    A(f"# Б2 — покритие за последните 14 дни ({res['from']} – {res['to']})")
    A("")
    A("**САМО ИЗМЕРВАНЕ.** Нищо в живия код не е пипано, нищо не е записано в базата.")
    A("")
    A(f"Изтеглени **{res['api_calls']} API заявки** — точно по една на лига за целия "
      "период (`/fixtures` с `from`/`to`), през `api_football._api_get()`, тоест през "
      "лимитера и записани в `api_calls.log`.")
    A("")
    A("Честно за бюджета: скриптът е пускан **два пъти** (19.09.2026, 06:15 и 06:2x UTC) "
      "— веднъж за самото измерване и втори път, за да се добави разделът с извода — "
      "тоест **34 заявки общо**, в рамките на очакваното от задачата (17-34). Двата "
      "пъти дадоха еднакви числа. Суровият отговор е запазен в "
      "`coverage_14d_20260919_raw.json`, така че докладът се преправя с "
      "`python validation/coverage_14d_20260919.py --from-cache` — нула нови заявки.")
    A("")
    A("## Как се чете таблицата")
    A("")
    A("| ниво | значение |")
    A("|---|---|")
    A("| **играни** | мачове, които API-Football дава за периода, без отложените/отменените |")
    A("| **логнати** | от тях имат поне един ред в `predictions_log` |")
    A("| **показани** | от тях `top_pick_for_match()` е върнал прогноза, тоест мачът реално е бил в „Предстоящи“, а не в „без доверена прогноза“ |")
    A("")
    A("## Покритие по лига")
    A("")
    A("| лига | играни | логнати | показани | логнати % | показани % | неиграни |")
    A("|---|---|---|---|---|---|---|")
    for k, v in sorted(res["per_league"].items(), key=lambda kv: kv[1]["real"], reverse=True):
        A(f"| {v['name']} (`{k}`) | {v['real']} | {v['logged']} | {v['shown']} | "
          f"{_pct(v['logged'], v['real'])} | {_pct(v['shown'], v['real'])} | {v['not_played']} |")
    A(f"| **ОБЩО** | **{tot_real}** | **{tot_log}** | **{tot_shown}** | "
      f"**{_pct(tot_log, tot_real)}** | **{_pct(tot_shown, tot_real)}** | **{tot_np}** |")
    A("")
    A("## Покритие по ден")
    A("")
    A("| ден | играни | логнати | показани | показани % |")
    A("|---|---|---|---|---|")
    for d, (real, log_, shown) in res["per_day"].items():
        A(f"| {d} | {real} | {log_} | {shown} | {_pct(shown, real)} |")
    A("")
    A("## Къде точно се губят мачовете")
    A("")
    lost_fetch = tot_real - tot_log
    lost_trust = tot_log - tot_shown
    A(f"| етап | изгубени мача | дял от всички играни |")
    A("|---|---|---|")
    A(f"| теглене / логване (няма ред в `predictions_log`) | {lost_fetch} | {_pct(lost_fetch, tot_real)} |")
    A(f"| филтър за доверие (логнат, но без публикуема прогноза) | {lost_trust} | {_pct(lost_trust, tot_real)} |")
    A(f"| **стигат до витрината** | **{tot_shown}** | **{_pct(tot_shown, tot_real)}** |")
    A("")
    by_league_gap = Counter((g["league"], g["where"]) for g in res["gaps"])
    if by_league_gap:
        A("### Най-големите дупки (лига × причина)")
        A("")
        A("| лига | причина | брой мача |")
        A("|---|---|---|")
        for (lg, where), n in by_league_gap.most_common(15):
            A(f"| {lg} | {where} | {n} |")
        A("")
    if res["errors"]:
        A("### Лиги, върнали грешка от API-то")
        A("")
        for k, v in res["errors"].items():
            A(f"- `{k}`: {v}")
        A("")
    A("Пълният списък непокрити мачове е в `coverage_14d_20260919.csv` "
      "(обобщено по лига) — детайлът по мач е в `coverage_14d_20260919_gaps.csv`.")
    A("")
    A("## Изводът с едно изречение")
    A("")
    A("**Мачовете НЕ се губят нито в тегленето, нито в логването — губят се във "
      "филтъра за доверие, и то почти изцяло в три лиги.**")
    A("")
    A("Разгърнато:")
    A("")
    A("1. **Тегленето и логването работят на практика безупречно: 314 от 322 играни "
      "мача (98%) имат ред в `predictions_log`.** Осемте изключения са всичките в "
      "евротурнирите (5 Лига Европа, 3 Шампионска лига) — квалификационни/плейоф "
      "двойки, влезли в календара късно.")
    A("2. **Целият реален пропуск е филтърът за доверие: 71 мача.** От тях **71 от 71** "
      "са в три лиги, при които НИТО ЕДИН мач не стига до витрината:")
    A("   - `england2` (Чемпиъншип, 36 мача) и `germany2` (Втора Бундеслига, 18 мача) — "
      "всички пазари са `UNVERIFIED`: тези лиги изобщо ги няма в ръчната `TRUST_MATRIX`, "
      "а изведената от данни (`trust_derived`) не им дава статус. Това е точно "
      "„затвореният кръг“, описан в `validation/trust_circle_sim_20260902.md` (НОЩ2, "
      "т.4) — лигата не получава статус, защото няма публикувани прогнози, и няма "
      "публикувани прогнози, защото няма статус. **Чака решение на Дака оттогава.**")
    A("   - `portugal2` (Сегунда Лига, 17 мача) — различен случай: всички пазари са "
      "изрично `REJECTED` в ръчната `TRUST_MATRIX`, тоест това е **съзнателно старо "
      "решение**, не дупка. Ако е предвидено да е така, лигата просто не бива да стои "
      "в списъка на обещаните 17.")
    A("3. **Празна страница не е риск за големите първенства.** Всяка от десетте водещи "
      "лиги (Англия, Испания, Италия, Германия, Франция, Португалия, България + вторите "
      "дивизии на Испания/Италия/Франция) е на **100% показани**. Публиката, за която е "
      "сайтът, вижда прогноза за всеки изигран мач.")
    A("4. **Лигата на конференциите върна 0 мача за периода** — не е грешка, турнирът "
      "просто няма мачове между 05 и 18.09.2026.")
    A("5. Затова общото „75% покритие“ е подвеждащо число само по себе си: **без трите "
      "лиги без статус покритието е 243 от 251 играни мача, тоест 97%.**")
    A("")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    with open(csv_path.replace(".csv", "_gaps.csv"), "w", newline="", encoding="utf-8") as f:
        w = _csv.writer(f)
        w.writerow(["league", "day", "fixture_id", "home", "away", "where"])
        for g in sorted(res["gaps"], key=lambda g: (g["league"], g["day"])):
            w.writerow([g["league"], g["day"], g["fixture_id"], g["home"], g["away"], g["where"]])


RAW_PATH = "validation/coverage_14d_20260919_raw.json"

if __name__ == "__main__":
    # --from-cache преправя доклада от вече изтеглените сурови данни, БЕЗ нито
    # една нова API заявка (правило 8 от CLAUDE.md: числото трябва да е в git;
    # суровият отговор се пази, за да е проверимо, а не да се тегли пак).
    if "--from-cache" in sys.argv and os.path.exists(RAW_PATH):
        res = json.load(open(RAW_PATH, encoding="utf-8"))
        print(f"(от кеша {RAW_PATH}, нула API заявки)")
    else:
        res = main()
        with open(RAW_PATH, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    write_report(res, "validation/coverage_14d_20260919.md",
                 "validation/coverage_14d_20260919.csv")
    print(json.dumps({k: v for k, v in res.items() if k not in ("gaps", "per_day")},
                     ensure_ascii=False, indent=2, default=str))
    print(f"дупки: {len(res['gaps'])}")
