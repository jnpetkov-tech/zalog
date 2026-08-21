import ast

with open("match_predictor_app.py") as f:
    content = f.read()

old_block = '''def index_home():
    predictions = st.list_predictions()
    won = sum(1 for p in predictions if p["status"] == "won")
    lost = sum(1 for p in predictions if p["status"] == "lost")
    pending = sum(1 for p in predictions if p["status"] == "pending")
    total_settled = won + lost
    win_rate = (won / total_settled * 100) if total_settled else None
    overall = {"won": won, "lost": lost, "pending": pending, "win_rate": win_rate}
    today_str = date.today().isoformat()
    today_preds = [p for p in predictions if p["status"] == "pending" and str(p["match_date"])[:10] == today_str]
    match_groups = {}
    for p in today_preds:
        key = (p["match_date"], p["home_team"], p["away_team"], p["league"])
        match_groups.setdefault(key, []).append(p)
    top_matches = []
    for (mdate, home, away, league), preds in match_groups.items():
        ranked = ps.rank_logged_rows(preds, league, policy, n=1)
        if not ranked:
            continue
        top_pred = ranked[0]
        top_matches.append({"date": mdate, "home": home, "away": away, "league": league, "top_pred": top_pred})
    top_matches.sort(key=lambda m: -m["top_pred"]["pick_pct"])
    top_matches = top_matches[:5]
    return render_template_string(INDEX_TEMPLATE, active_page='home', overall=overall,
                                    top_matches=top_matches, cyrillic=to_cyrillic)'''

new_block = '''def index_home():
    predictions = st.list_predictions()
    won = sum(1 for p in predictions if p["status"] == "won")
    lost = sum(1 for p in predictions if p["status"] == "lost")
    pending = sum(1 for p in predictions if p["status"] == "pending")
    total_settled = won + lost
    win_rate = (won / total_settled * 100) if total_settled else None
    overall = {"won": won, "lost": lost, "pending": pending, "win_rate": win_rate}
    # Фаза I.3: честна метрика само върху ПУБЛИКУВАНИТЕ прогнози (виж
    # evaluation.py, Фаза I.2) - връща плочката, скрита в Фаза H.2.
    eval_summary = evaluation.summary(predictions, policy)
    today_str = date.today().isoformat()
    today_preds = [p for p in predictions if p["status"] == "pending" and str(p["match_date"])[:10] == today_str]
    match_groups = {}
    for p in today_preds:
        key = (p["match_date"], p["home_team"], p["away_team"], p["league"])
        match_groups.setdefault(key, []).append(p)
    top_matches = []
    for (mdate, home, away, league), preds in match_groups.items():
        ranked = ps.rank_logged_rows(preds, league, policy, n=1)
        if not ranked:
            continue
        top_pred = ranked[0]
        top_matches.append({"date": mdate, "home": home, "away": away, "league": league, "top_pred": top_pred})
    top_matches.sort(key=lambda m: -m["top_pred"]["pick_pct"])
    top_matches = top_matches[:5]
    return render_template_string(INDEX_TEMPLATE, active_page='home', overall=overall,
                                    top_matches=top_matches, cyrillic=to_cyrillic,
                                    promised_avg=eval_summary["promised_avg"],
                                    actual_pct=eval_summary["actual_pct"],
                                    n_settled=eval_summary["n_settled"])'''

count = content.count(old_block)
assert count == 1, f"index_home anchor count: {count} (очаквано 1)"
content = content.replace(old_block, new_block, 1)

ast.parse(content)

with open("match_predictor_app.py", "w") as f:
    f.write(content)

print("OK - index_home() вече изчислява честната метрика (Фаза I.3)")
