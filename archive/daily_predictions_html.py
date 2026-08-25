import sys
import requests
import numpy as np
import pandas as pd
from scipy.stats import poisson
import football_lib as fl
from production_pipeline import fit_ht_2h_models, predict_ht_ft

API_KEY = os.environ.get("API_FOOTBALL_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"
headers = {"x-apisports-key": API_KEY}

LEAGUE_IDS = {
    "bulgaria": 172, "england": 39, "germany": 78, "spain": 140, "france": 61,
}
LEAGUE_NAMES = {
    "bulgaria": "Първа лига България", "england": "Английска Висша лига",
    "germany": "Бундеслига", "spain": "Ла Лига", "france": "Лига 1 Франция",
}
DAYS_AHEAD = 7

TEAM_NAME_BG = {
    "Levski Sofia": "Левски (София)",
    "CSKA Sofia": "ЦСКА (София)",
    "CSKA 1948": "ЦСКА 1948",
    "Ludogorets": "Лудогорец",
    "Botev Vratsa": "Ботев (Враца)",
    "Botev Plovdiv": "Ботев (Пловдив)",
    "Lokomotiv Plovdiv": "Локомотив (Пловдив)",
    "Lokomotiv Sofia": "Локомотив (София)",
    "Slavia Sofia": "Славия (София)",
    "Spartak Varna": "Спартак (Варна)",
    "Cherno More Varna": "Черно море (Варна)",
    "Dunav Ruse": "Дунав (Русе)",
    "Arda Kardzhali": "Арда (Кърджали)",
    "Septemvri Sofia": "Септември (София)",
}

def bg_name(name):
    return TEAM_NAME_BG.get(name, name)


def get_team_rest_info(team_id, match_date_iso, days_back=10):
    from datetime import datetime, timedelta
    match_dt = datetime.fromisoformat(match_date_iso[:19])
    from_date = (match_dt - timedelta(days=days_back)).date().isoformat()
    to_date = (match_dt - timedelta(days=1)).date().isoformat()
    url = f"{BASE_URL}/fixtures"
    params = {"team": team_id, "from": from_date, "to": to_date}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        data = r.json()
    except Exception:
        return {"rest_days": None, "matches_week": 0, "played_europe": False, "last_league": ""}

    fixtures = data.get("response", [])
    if not fixtures:
        return {"rest_days": None, "matches_week": 0, "played_europe": False, "last_league": ""}

    fixtures.sort(key=lambda x: x["fixture"]["date"])
    last = fixtures[-1]
    last_dt = datetime.fromisoformat(last["fixture"]["date"][:19])
    rest_days = (match_dt.date() - last_dt.date()).days
    matches_week = sum(
        1 for x in fixtures
        if (match_dt.date() - datetime.fromisoformat(x["fixture"]["date"][:19]).date()).days <= 7
    )
    league_name = last.get("league", {}).get("name", "")
    played_europe = any(kw in league_name for kw in ("UEFA", "Europa", "Conference League", "Champions League"))
    return {
        "rest_days": rest_days,
        "matches_week": matches_week,
        "played_europe": played_europe,
        "last_league": league_name,
    }


def fetch_upcoming_fixtures(league_id, days_ahead=7):
    from datetime import date, timedelta
    today = date.today()
    to_date = today + timedelta(days=days_ahead)
    url = f"{BASE_URL}/fixtures"
    params = {
        "league": league_id,
        "season": today.year if today.month >= 7 else today.year - 1,
        "from": today.isoformat(),
        "to": to_date.isoformat(),
    }
    r = requests.get(url, headers=headers, params=params)
    data = r.json()
    if data.get("errors"):
        print(f"Грешка: {data['errors']}")
        return []
    return data.get("response", [])


def build_reasoning(pick_label, home, away, lam, mu, pct):
    home_short = home.split()[0]
    away_short = away.split()[0]
    diff = lam - mu

    if "печели" in pick_label and home in pick_label:
        if diff > 1.5:
            return (f"{home} е категоричен фаворит в тази среща. Разликата в класата "
                     f"личи ясно от очакваната голова листа – около {lam:.1f} срещу {mu:.1f} "
                     f"за {away_short}. Труден мач за изненада откъм гостите.")
        else:
            return (f"{home} влиза с известно предимство, подкрепено и от терена си. "
                     f"Очакваме по-скоро контролирана победа, отколкото разгром – "
                     f"{away_short} все пак имат с какво да отговорят.")

    if "печели" in pick_label and away in pick_label:
        return (f"Въпреки че играят на чужд терен, {away_short} изглеждат по-стабилният "
                 f"отбор в момента – формата им говори повече от домакинския фактор тук.")

    if pick_label == "Равен":
        return (f"Двата отбора са прекалено близки по сила, за да очакваме ясен победител. "
                 f"{home_short} и {away_short} вървят паралелно във формата си – равенство "
                 f"изглежда логичният изход.")

    if "Над 2.5" in pick_label:
        return (f"И двата отбора генерират достатъчно положения за гол – комбинираната им "
                 f"голова продукция ({lam:.1f} + {mu:.1f}) сочи открит, атрактивен двубой. "
                 f"Малко вероятно е да останем без голове тук.")

    if "Под 2.5" in pick_label:
        return (f"Затворен, тактически двубой се очертава – нито {home_short}, нито "
                 f"{away_short} са особено голови в скорошните си мачове. "
                 f"Залагаме на предпазлива игра от двете страни.")

    if "над 1.5" in pick_label and home_short in pick_label:
        return (f"{home_short} у дома обикновено намират пътя към вратата на съперника "
                 f"без особен проблем – очакваме поне два гола от тях в тази среща.")

    if "под 1.5" in pick_label and home_short in pick_label:
        return (f"{away_short} играят компактно в защита, а и {home_short} невинаги "
                 f"реализират наличните си положения – скромна голова продукция от "
                 f"домакините изглежда по-вероятна.")

    if "почивка" in pick_label.lower():
        return (f"Очакваме динамика между двете полувремета – резултатът може да се "
                 f"размърда осезаемо след почивката, съдейки по темпото, което двата "
                 f"отбора обичайно налагат.")

    return (f"Изчисленията сочат {lam:.1f} срещу {mu:.1f} очаквани гола за двата отбора, "
             f"от което този пазар излиза като най-стабилният избор.")


def fatigue_note(home_team, away_team, home_info, away_info):
    notes = []
    for team_label, info in ((home_team, home_info), (away_team, away_info)):
        if not info:
            continue
        if info.get("played_europe") and info.get("rest_days") is not None and info["rest_days"] <= 4:
            notes.append(
                f"{team_label} излизат само {info['rest_days']} дни след евромач "
                f"({info.get('last_league') or 'евротурнир'}) — натоварването трудно се игнорира."
            )
        elif info.get("matches_week", 0) >= 3:
            notes.append(
                f"{team_label} играят трети мач за седмица — натоварен график, който може "
                f"да се усети във втората част на срещата."
            )
    if not notes:
        return ""
    return " " + " ".join(notes)


def select_best_pick(lam, mu, home_team, away_team, ht_ft_probs=None, home_info=None, away_info=None):
    max_g = 10
    pm = np.outer(poisson.pmf(range(max_g), lam), poisson.pmf(range(max_g), mu))
    home_win = np.sum(np.tril(pm, -1))
    draw = np.sum(np.diag(pm))
    away_win = np.sum(np.triu(pm, 1))

    btts_p, ou_p = fl.btts_ou_probs(lam, mu)
    extra = fl.extra_markets_probs(lam, mu)

    candidates = {
        f"{home_team} печели": home_win,
        "Равен": draw,
        f"{away_team} печели": away_win,
        "Над 2.5 гола": ou_p,
        "Под 2.5 гола": 1 - ou_p,
        f"{home_team} над 1.5 гола": extra["home_over15"],
        f"{home_team} под 1.5 гола": 1 - extra["home_over15"],
    }
    if ht_ft_probs:
        best_htft = max(ht_ft_probs.items(), key=lambda x: x[1])
        candidates[f"Резултат почивка/край {best_htft[0]}"] = best_htft[1]

    best_label, best_pct = max(candidates.items(), key=lambda x: x[1])
    reasoning = build_reasoning(best_label, home_team, away_team, lam, mu, best_pct * 100)
    reasoning += fatigue_note(home_team, away_team, home_info, away_info)
    return best_label, best_pct * 100, reasoning


def build_html(rows, league_name):
    cards = ""
    for r in rows:
        conf_color = "#0F6E56" if r["confidence"] >= 60 else "#185FA5" if r["confidence"] >= 50 else "#5F5E5A"
        cards += f"""
        <div class="card">
          <div class="card-header">
            <span class="teams">{r['home']} <span class="vs">vs</span> {r['away']}</span>
            <span class="date">{r['date']}</span>
          </div>
          <div class="pick-row" style="background:{conf_color}15;">
            <span class="pick-label" style="color:{conf_color};">{r['pick']}</span>
            <span class="pick-pct" style="color:{conf_color};">{r['confidence']:.1f}%</span>
          </div>
          <p class="reasoning">{r['reasoning']}</p>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="bg">
<head>
<meta charset="UTF-8">
<title>Прогнози - {league_name}</title>
<style>
  body {{ font-family: -apple-system, sans-serif; background: #F1EFE8; margin: 0; padding: 24px; }}
  .container {{ max-width: 640px; margin: 0 auto; }}
  h1 {{ font-size: 20px; font-weight: 500; margin-bottom: 4px; }}
  .subtitle {{ color: #5F5E5A; font-size: 14px; margin-bottom: 24px; }}
  .card {{ background: white; border: 0.5px solid #D3D1C7; border-radius: 12px;
           padding: 16px 20px; margin-bottom: 12px; }}
  .card-header {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 12px; }}
  .teams {{ font-size: 15px; font-weight: 500; }}
  .vs {{ color: #888780; font-weight: 400; }}
  .date {{ font-size: 12px; color: #888780; }}
  .pick-row {{ display: flex; justify-content: space-between; align-items: center;
               border-radius: 8px; padding: 10px 14px; margin-bottom: 10px; }}
  .pick-label {{ font-size: 14px; font-weight: 500; }}
  .pick-pct {{ font-size: 18px; font-weight: 500; }}
  .reasoning {{ font-size: 13px; color: #5F5E5A; line-height: 1.5; margin: 0; }}
</style>
</head>
<body>
<div class="container">
  <h1>Прогнози - {league_name}</h1>
  <div class="subtitle">Следващите {DAYS_AHEAD} дни · {len(rows)} мача</div>
  {cards}
</div>
</body>
</html>"""
    return html


def main():
    league = sys.argv[1] if len(sys.argv) > 1 else "bulgaria"
    if league not in LEAGUE_IDS:
        print(f"Непозната лига: {league}. Налични: {list(LEAGUE_IDS.keys())}")
        sys.exit(1)

    print(f"Тегля предстоящи мачове за {league}...")
    fixtures = fetch_upcoming_fixtures(LEAGUE_IDS[league], DAYS_AHEAD)
    print(f"Намерени {len(fixtures)} предстоящи мача.\n")

    if not fixtures:
        print("Няма предстоящи мачове в този период.")
        return

    print("Зареждам и тренирам моделите...")
    df = fl.load_league_data(league)
    teams, n, team_idx = fl.get_team_index(df)
    ref_date = df["date"].max()

    ft_model = fl.fit_goals_model(df, ref_date, team_idx, n)
    ht_model, h2_model = fit_ht_2h_models(df, team_idx, n)
    print("Готово.\n")

    rows = []
    for f in fixtures:
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]
        match_date = f["fixture"]["date"][:16].replace("T", " ")

        if home not in team_idx or away not in team_idx:
            continue

        lam, mu = fl.get_lambdas(ft_model, team_idx, home, away)
        lam_ht, mu_ht = fl.get_lambdas(ht_model, team_idx, home, away)
        lam_2h, mu_2h = fl.get_lambdas(h2_model, team_idx, home, away)
        ht_ft_probs = predict_ht_ft(lam_ht, mu_ht, lam_2h, mu_2h)

        home_id = f["teams"]["home"]["id"]
        away_id = f["teams"]["away"]["id"]
        match_date_iso = f["fixture"]["date"]
        home_info = get_team_rest_info(home_id, match_date_iso)
        away_info = get_team_rest_info(away_id, match_date_iso)

        pick, pct, reasoning = select_best_pick(
            lam, mu, bg_name(home), bg_name(away), ht_ft_probs, home_info, away_info
        )

        rows.append({
            "date": match_date, "home": bg_name(home), "away": bg_name(away),
            "pick": pick, "confidence": pct, "reasoning": reasoning,
        })

    rows.sort(key=lambda r: -r["confidence"])

    html = build_html(rows, LEAGUE_NAMES.get(league, league))
    output_path = f"predictions_{league}.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"HTML страница записана в {output_path}")


if __name__ == "__main__":
    main()
