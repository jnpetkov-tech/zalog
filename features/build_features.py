"""features/build_features.py - таблица с признаци, един ред на мач (ZADACHA_TABLICA, стъпка 1, 01.10.2026).

ПРАВИЛО НА ВРЕМЕТО: признаците на мач M (начало ts_M) се смятат САМО от:
  (а) резултати/събития/статистика/състави на мачове със ts < ts_M (строго по-рано);
  (б) разписанието (кой с кого и кога играе) - известно предварително;
  (в) предмачова информация за самия мач M: състави (publикуват се ~1 ч преди началото), контузени по мача, съдия.
Никога: голове, събития, статистика, играчи на самия мач M, нито на по-късни мачове.
Същият код смята и проверката срещу изтичане (features/leak_check.py): отрязва данните до ts_M и смята мача наново.

Употреба: venv/bin/python3 features/build_features.py        -> features/features_table.csv.gz
Речник на признаците: features/README.md.
"""
import bisect
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

LEAGUES = ["bulgaria", "england", "germany", "spain", "france", "italy", "portugal", "champions_league", "europa_league",
           "conference_league", "france2", "spain2", "italy2", "portugal2", "bulgaria2", "england2", "germany2"]
CUPS = {"champions_league", "europa_league", "conference_league"}
FINISHED = {"FT", "AET", "PEN"}
N_SHORT, N_LONG = 5, 10
LINEUP_N = 10          # колко предишни мача с състав определят "обичайния" състав
INVOLVE_N = 20         # колко предишни мача за дела на голове+асистенции
USUAL_SHARE = 0.5      # започвал в >= 50% от последните LINEUP_N мача = обичаен титуляр
REF_MIN = 1
REST_CAP = 60.0        # дни; по-дълга пауза (нов отбор в данните, междусезоние) се реже до 60
# ZADACHA_RAZVITIE т.3 (02.10.2026): допълнителни папки със същите имена на файлове (историята 2019-2021 в hist/). Празно = както преди.
EXTRA_DIRS = []
# ТРЕНЬОР (07.10.2026): API-то дава един и същи треньор с различни id (и 0 за различни хора от /fixtures?ids=) -> фалшив coach_new и
# нулиран coach_tenure_days. True = същият по id ИЛИ по име (_same_coach); False = старото сравнение само по coach_id (за преди/след).
COACH_BY_NAME = True
_NAME_PARTICLES = {"van", "von", "der", "den", "del", "dos", "das", "bin"}


# ----------------------------------------------------------------------------------------------- зареждане
def _num(s):
    return pd.to_numeric(s.astype(str).str.replace("%", "", regex=False), errors="coerce")


def load_raw():
    def cat(pattern, **kw):
        parts = []
        for l in LEAGUES:
            for d in [""] + EXTRA_DIRS:
                f = os.path.join(d, pattern.format(l=l)) if d else pattern.format(l=l)
                if os.path.exists(f) and os.path.getsize(f) > 0:
                    parts.append(pd.read_csv(f, low_memory=False, **kw))
        return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

    fx = cat("{l}_fixtures.csv")
    fx = fx.sort_values("fetched_at").drop_duplicates("fixture_id", keep="last")
    fx = fx[fx["timestamp"].notna()].copy()
    fx["ts"] = fx["timestamp"].astype("int64")
    fx["season"] = fx["season"].astype(int)
    for c in ("ft_home", "ft_away"):
        fx[c] = pd.to_numeric(fx[c], errors="coerce")
    fx["gh"] = fx["ft_home"].where(fx["ft_home"].notna(), pd.to_numeric(fx["home_goals"], errors="coerce"))
    fx["ga"] = fx["ft_away"].where(fx["ft_away"].notna(), pd.to_numeric(fx["away_goals"], errors="coerce"))
    fx["finished"] = fx["status"].isin(FINISHED) & fx["gh"].notna() & fx["ga"].notna()
    fx = fx.sort_values(["ts", "fixture_id"]).reset_index(drop=True)

    lu = pd.concat([cat("{l}_lineups.csv")], ignore_index=True)
    lu = lu.drop(columns=["fetched_at"], errors="ignore").drop_duplicates()
    ev = pd.concat([cat("{l}_events.csv"), cat("{l}_events_pre2024.csv")], ignore_index=True).drop_duplicates()
    st = cat("{l}_stats_full.csv").drop(columns=["fetched_at"], errors="ignore").drop_duplicates(["fixture_id", "team_id"])
    for c in st.columns:
        if c not in ("fixture_id", "team_id", "team"):
            st[c] = _num(st[c])
    inj = cat("{l}_injuries.csv").drop(columns=["fetched_at"], errors="ignore").drop_duplicates()
    # "за тази лига-сезон има ли изобщо данни за контузии" - факт за наличността на данните, не за изхода на мач
    cov = {(r.league, int(r.season)) for r in inj[["league", "season"]].drop_duplicates().itertuples()}
    return {"fx": fx, "lineups": lu, "events": ev, "stats": st, "injuries": inj, "inj_cov": cov}


def index_raw(raw):
    """Речници по мач (бързо търсене вместо филтриране на таблици): събития, статистика, състави, контузени."""
    ev_by, st_by, lu_by, inj_by = {}, {}, {}, {}
    for r in raw["events"].itertuples(index=False):
        ev_by.setdefault(r.fixture_id, []).append((r.type, r.detail, r.team_id, r.player_id, r.assist_id, r.elapsed))
    for r in raw["stats"].to_dict("records"):
        st_by.setdefault(r["fixture_id"], {})[int(r["team_id"])] = r
    for r in raw["lineups"].itertuples(index=False):
        if pd.isna(r.team_id):
            continue
        d = lu_by.setdefault(r.fixture_id, {}).setdefault(int(r.team_id), {"starters": [], "squad": [], "pos": {}, "coach_id": r.coach_id, "coach": r.coach, "formation": r.formation})
        if pd.notna(r.player_id):
            pid = int(r.player_id)
            d["squad"].append(pid)
            if r.starter == 1:
                d["starters"].append(pid)
            if pd.notna(r.pos):
                d["pos"][pid] = str(r.pos)
    for r in raw["injuries"].itertuples(index=False):
        if pd.isna(r.team_id):
            continue
        d = inj_by.setdefault(r.fixture_id, {}).setdefault(int(r.team_id), [0, 0])
        if r.type == "Missing Fixture":
            d[0] += 1
        elif r.type == "Questionable":
            d[1] += 1
    raw["idx"] = {"ev": ev_by, "st": st_by, "lu": lu_by, "inj": inj_by}
    return raw


def truncate(raw, cutoff_ts, keep_fixture):
    """Данните така, както би ги имало ПРЕДИ мача keep_fixture (начало cutoff_ts): резултати/събития/статистика/състави
    само за мачове със ts < cutoff_ts; от самия мач - само предмачовата информация (състав, контузени, съдия, час);
    разписанието (кой кога играе) остава, но без резултати."""
    fx = raw["fx"].copy()
    past = fx["ts"] < cutoff_ts
    for c in ("gh", "ga", "ft_home", "ft_away", "ht_home", "ht_away", "home_goals", "away_goals", "et_home", "et_away",
              "pen_home", "pen_away", "elapsed"):
        if c in fx:
            fx.loc[~past, c] = np.nan
    fx.loc[~past, "status"] = "NS"
    fx["finished"] = fx["status"].isin(FINISHED) & fx["gh"].notna() & fx["ga"].notna()
    ids_past = set(fx.loc[past, "fixture_id"])
    ix = raw["idx"]
    return {"fx": fx, "inj_cov": raw["inj_cov"],
            "idx": {"ev": {k: v for k, v in ix["ev"].items() if k in ids_past},
                    "st": {k: v for k, v in ix["st"].items() if k in ids_past},
                    "lu": {k: v for k, v in ix["lu"].items() if k in ids_past or k == keep_fixture},
                    "inj": {k: v for k, v in ix["inj"].items() if k in ids_past or k == keep_fixture}}}


# ----------------------------------------------------------------------------------------------- записи по отбор-мач
def _goal_events(evs, home_id, away_id):
    """[(минута, 'h'|'a')] на головете на мача, по ред; автогол - за противника; пропуснат дузпа - не е гол."""
    out = []
    for typ, detail, team_id, _p, _a, elapsed in evs:
        if typ != "Goal" or detail == "Missed Penalty":
            continue
        side = "h" if team_id == home_id else "a" if team_id == away_id else None
        if side is None:
            continue
        if detail == "Own Goal":
            side = "a" if side == "h" else "h"
        minute = float(elapsed) if pd.notna(elapsed) else np.nan
        out.append((minute, side))
    out.sort(key=lambda x: (np.inf if np.isnan(x[0]) else x[0]))
    return out


def _lead_minutes(goals, side):
    """(минути водене, минути изоставане, на ниво) в 0..90 от гледна точка на side."""
    lead = trail = level = 0.0
    t, diff = 0.0, 0
    for m, s in goals:
        m = min(max(m, 0.0), 90.0) if not np.isnan(m) else 90.0
        seg = m - t
        if diff > 0: lead += seg
        elif diff < 0: trail += seg
        else: level += seg
        t = m
        diff += 1 if s == side else -1
    seg = 90.0 - t
    if diff > 0: lead += seg
    elif diff < 0: trail += seg
    else: level += seg
    return lead, trail, level


STAT_KEYS = ("Total_Shots", "Shots_on_Goal", "Shots_insidebox", "expected_goals", "Corner_Kicks", "Ball_Possession",
             "Yellow_Cards", "Red_Cards", "Fouls")


def team_match_records(raw):
    """Един ред на (мач, отбор) за ИЗИГРАНИТЕ мачове: какво се е случило - ползва се само от по-късни мачове."""
    fx = raw["fx"]
    fin = fx[fx["finished"]]
    ix = raw["idx"]
    recs = []
    for r in fin.itertuples():
        evf = ix["ev"].get(r.fixture_id)
        if evf is not None:
            goals = _goal_events(evf, r.home_id, r.away_id)
        elif r.gh + r.ga == 0:
            goals = []          # 0-0 без нито едно събитие (нито картон) - API-то не връща редове
        else:
            goals = None        # има голове, но няма събития = липсват данни
        reds = {"h": 0, "a": 0}
        pens = {"h": 0, "a": 0}
        if evf is not None:
            for typ, detail, team_id, _p, _a, _el in evf:
                side = "h" if team_id == r.home_id else "a" if team_id == r.away_id else None
                if side is None:
                    continue
                if typ == "Card" and detail in ("Red Card", "Second Yellow card"):
                    reds[side] += 1
                if (typ == "Goal" and detail == "Penalty") or detail == "Missed Penalty":
                    pens[side] += 1
        stf = ix["st"].get(r.fixture_id, {})
        luf = ix["lu"].get(r.fixture_id, {})
        for side, tid, oid, gf, ga in (("h", r.home_id, r.away_id, r.gh, r.ga), ("a", r.away_id, r.home_id, r.ga, r.gh)):
            tid, oid = int(tid), int(oid)
            o = "a" if side == "h" else "h"
            rec = {"fixture_id": r.fixture_id, "ts": r.ts, "league": r.league, "season": r.season, "team_id": tid,
                   "opp_id": oid, "is_home": side == "h", "gf": float(gf), "ga": float(ga),
                   "pts": 3.0 if gf > ga else 1.0 if gf == ga else 0.0}
            if goals is not None:
                gf_b = [0, 0, 0]
                ga_b = [0, 0, 0]
                for m, s in goals:
                    b = 0 if (not np.isnan(m) and m <= 30) else 1 if (not np.isnan(m) and m <= 60) else 2
                    (gf_b if s == side else ga_b)[b] += 1
                lead, trail, level = _lead_minutes(goals, side)
                first = (1.0 if goals[0][1] == side else 0.0) if goals else np.nan
                rec.update({"gf_b0": gf_b[0], "gf_b1": gf_b[1], "gf_b2": gf_b[2], "ga_b0": ga_b[0], "ga_b1": ga_b[1],
                            "ga_b2": ga_b[2], "lead": lead, "trail": trail, "level": level, "first_goal": first,
                            "red_for": float(reds[side]), "red_against": float(reds[o]),
                            "pen_for": float(pens[side]), "pen_against": float(pens[o]), "has_events": True})
                inv = {}
                for typ, detail, team_id, pid, aid, _el in (evf or []):
                    if typ == "Goal" and detail not in ("Missed Penalty", "Own Goal") and team_id == tid:
                        if pd.notna(pid): inv[int(pid)] = inv.get(int(pid), 0) + 1
                        if pd.notna(aid): inv[int(aid)] = inv.get(int(aid), 0) + 1
                rec["involve"] = inv
            else:
                rec["has_events"] = False
            if tid in stf and oid in stf:
                a, b = stf[tid], stf[oid]
                rec.update({"sh_for": a["Total_Shots"], "sh_ag": b["Total_Shots"], "sot_for": a["Shots_on_Goal"],
                            "sot_ag": b["Shots_on_Goal"], "box_for": a["Shots_insidebox"], "box_ag": b["Shots_insidebox"],
                            "xg_for": a["expected_goals"], "xg_ag": b["expected_goals"], "cor_for": a["Corner_Kicks"],
                            "pos_for": a["Ball_Possession"], "has_stats": True,
                            "m_yellow": a["Yellow_Cards"] + b["Yellow_Cards"], "m_red": a["Red_Cards"] + b["Red_Cards"],
                            "m_fouls": a["Fouls"] + b["Fouls"]})
            else:
                rec["has_stats"] = False
            t = luf.get(tid)
            if t is not None:
                rec.update({"starters": tuple(t["starters"]), "squad": tuple(t["squad"]), "pos": t["pos"],
                            "has_lineup": len(t["starters"]) >= 9, "coach_id": t["coach_id"], "coach": t["coach"],
                            "formation": t["formation"]})
            else:
                rec["has_lineup"] = False
            recs.append(rec)
    recs.sort(key=lambda d: (d["ts"], d["fixture_id"], not d["is_home"]))
    return recs


class History:
    """Историята на отборите: prior(team, ts) -> записите със ts < ts (строго), по ред."""

    def __init__(self, recs):
        self.by_team = {}
        for r in recs:
            self.by_team.setdefault(r["team_id"], []).append(r)
        self.ts = {t: [r["ts"] for r in lst] for t, lst in self.by_team.items()}

    def prior(self, team, ts):
        lst = self.by_team.get(team)
        if not lst:
            return []
        return lst[:bisect.bisect_left(self.ts[team], ts)]


# ----------------------------------------------------------------------------------------------- блокове
def _mean(vals):
    v = [x for x in vals if x is not None and not (isinstance(x, float) and np.isnan(x))]
    return float(np.mean(v)) if v else np.nan


def block_rest(prior, ts, euro_future):
    out = {}
    last = prior[-1]["ts"] if prior else None
    out["rest_days"] = min((ts - last) / 86400.0, REST_CAP) if last else np.nan
    out["n_last7"] = float(sum(1 for r in prior if ts - r["ts"] <= 7 * 86400))
    out["n_last14"] = float(sum(1 for r in prior if ts - r["ts"] <= 14 * 86400))
    out["euro_prev4"] = float(any(r["league"] in CUPS and ts - r["ts"] <= 4 * 86400 for r in prior))
    out["euro_next4"] = float(euro_future)
    return out


def block_form(prior):
    out = {}
    for n, tag in ((N_SHORT, "5"), (N_LONG, "10")):
        p = prior[-n:]
        out[f"pts{tag}"] = _mean([r["pts"] for r in p])
        out[f"gf{tag}"] = _mean([r["gf"] for r in p])
        out[f"ga{tag}"] = _mean([r["ga"] for r in p])
    p = prior[-N_LONG:]
    pe = [r for r in p if r["has_events"]]
    out["n_ev10"] = float(len(pe))
    if pe:
        gf = [sum(r[f"gf_b{b}"] for r in pe) for b in range(3)]
        ga = [sum(r[f"ga_b{b}"] for r in pe) for b in range(3)]
        out["gf_late_share10"] = gf[2] / sum(gf) if sum(gf) else np.nan
        out["gf_early_share10"] = gf[0] / sum(gf) if sum(gf) else np.nan
        out["ga_late_share10"] = ga[2] / sum(ga) if sum(ga) else np.nan
        out["ga_early_share10"] = ga[0] / sum(ga) if sum(ga) else np.nan
        out["lead_share10"] = sum(r["lead"] for r in pe) / (90.0 * len(pe))
        out["trail_share10"] = sum(r["trail"] for r in pe) / (90.0 * len(pe))
        fg = [r["first_goal"] for r in pe if not np.isnan(r["first_goal"])]
        out["first_goal_rate10"] = float(np.mean(fg)) if fg else np.nan
        out["red_for10"] = _mean([r["red_for"] for r in pe])
        out["red_against10"] = _mean([r["red_against"] for r in pe])
        out["pen_for10"] = _mean([r["pen_for"] for r in pe])
        out["pen_against10"] = _mean([r["pen_against"] for r in pe])
    else:
        for k in ("gf_late_share10", "gf_early_share10", "ga_late_share10", "ga_early_share10", "lead_share10", "trail_share10",
                  "first_goal_rate10", "red_for10", "red_against10", "pen_for10", "pen_against10"):
            out[k] = np.nan
    for n, tag in ((N_SHORT, "5"), (N_LONG, "10")):
        ps = [r for r in prior[-n:] if r["has_stats"]]
        out[f"n_st{tag}"] = float(len(ps))
        for k in ("sh_for", "sh_ag", "sot_for", "sot_ag", "xg_for", "xg_ag"):
            out[f"{k}{tag}"] = _mean([r[k] for r in ps])
    ps = [r for r in prior[-N_LONG:] if r["has_stats"]]
    for k in ("box_for", "box_ag", "cor_for", "pos_for"):
        out[f"{k}10"] = _mean([r[k] for r in ps])
    return out


def _name_tokens(name):
    import unicodedata
    n = "".join(c for c in unicodedata.normalize("NFKD", str(name).lower()) if not unicodedata.combining(c))
    return n.replace(".", " ").replace("-", " ").replace("'", " ").split()


def _coach_known(cid, name):
    return (pd.notna(cid) and cid != 0) or (isinstance(name, str) and name.strip() != "")


def _same_coach(a, b):
    """a, b = (coach_id, coach). Един и същи: еднакъв ненулев id; или еднакво име без ударения; или обща фамилия (>= 3 букви, не
    "van"/"del"..., не първото име на многословно име - "Daniel Ramos"/"Daniel Sousa" са различни) при съвместим инициал на първото име
    ("M. Carrick"/"Michael Carrick", "G. Gasperini"/"Piero Gasperini Gian"; не "Filipe Martins"/"Vitor Martins")."""
    (ia, na), (ib, nb) = a, b
    if not COACH_BY_NAME:
        return ia == ib
    if pd.notna(ia) and pd.notna(ib) and ia != 0 and ia == ib:
        return True
    if not (isinstance(na, str) and isinstance(nb, str)):
        return False
    ta, tb = _name_tokens(na), _name_tokens(nb)
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    first = ({ta[0]} if len(ta) > 1 else set()) | ({tb[0]} if len(tb) > 1 else set())
    shared = {t for t in ta if len(t) >= 3 and t not in _NAME_PARTICLES} & set(tb) - first
    if not shared:
        return False
    return ta[0][0] in {t[0] for t in tb} or tb[0][0] in {t[0] for t in ta}


def block_absent(prior, squad_today, starters_today, coach_today, ts):
    """Отсъстващи спрямо обичайния състав. Нужни: състав на ТОЗИ мач (предмачов) + предишни мачове."""
    out = {k: np.nan for k in ("n_usual", "n_absent", "absent_weight", "gk_absent", "def_absent", "mid_absent", "fwd_absent",
                               "absent_involve_share", "xi_changes", "xi_experience", "coach_new", "coach_tenure_days")}
    pl = [r for r in prior if r["has_lineup"]]
    if len(pl) < 3 or squad_today is None:
        return out
    last = pl[-LINEUP_N:]
    starts = {}
    pos_votes = {}
    for r in last:
        for p in r["starters"]:
            starts[p] = starts.get(p, 0) + 1
        for p, s in r["pos"].items():
            pos_votes.setdefault(p, {}).setdefault(s, 0)
            pos_votes[p][s] += 1
    n = float(len(last))
    share = {p: c / n for p, c in starts.items()}
    usual = [p for p, s in share.items() if s >= USUAL_SHARE]
    sq = set(squad_today)
    absent = [p for p in usual if p not in sq]
    pos_of = {p: max(v.items(), key=lambda kv: (kv[1], kv[0]))[0] for p, v in pos_votes.items()}
    out["n_usual"] = float(len(usual))
    out["n_absent"] = float(len(absent))
    out["absent_weight"] = float(sum(share[p] for p in absent))
    out["gk_absent"] = float(any(pos_of.get(p) == "G" for p in absent))
    out["def_absent"] = float(sum(1 for p in absent if pos_of.get(p) == "D"))
    out["mid_absent"] = float(sum(1 for p in absent if pos_of.get(p) == "M"))
    out["fwd_absent"] = float(sum(1 for p in absent if pos_of.get(p) == "F"))
    inv = {}
    for r in [x for x in prior if x["has_events"]][-INVOLVE_N:]:
        for p, c in r.get("involve", {}).items():
            inv[p] = inv.get(p, 0) + c
    tot = sum(inv.values())
    out["absent_involve_share"] = float(sum(inv.get(p, 0) for p in absent) / tot) if tot else np.nan
    if starters_today is not None:
        prev = pl[-1]
        out["xi_changes"] = float(sum(1 for p in starters_today if p not in set(prev["starters"])))
        out["xi_experience"] = float(np.mean([starts.get(p, 0) for p in starters_today])) if starters_today else np.nan
    # треньор: нов ли е спрямо предишния мач и колко дни е на този пост (по състави)
    # coach_today = (coach_id, coach); при COACH_BY_NAME=False - старото: само id, 0 се брои за известен
    if coach_today is not None and (_coach_known(*coach_today) if COACH_BY_NAME else pd.notna(coach_today[0])):
        prev = (pl[-1]["coach_id"], pl[-1].get("coach"))
        prev_known = _coach_known(*prev) if COACH_BY_NAME else pd.notna(prev[0])
        out["coach_new"] = float(prev_known and not _same_coach(prev, coach_today))
        first_ts = ts
        for r in reversed(pl):
            if _same_coach((r["coach_id"], r.get("coach")), coach_today):
                first_ts = r["ts"]
            else:
                break
        out["coach_tenure_days"] = min((ts - first_ts) / 86400.0, 1000.0)
    return out


def standings_features(fx_ls, ts, home_id, away_id):
    """Класиране към ts от резултатите на мачове със ts < ts в същата лига и сезон (само вътрешни първенства)."""
    out = {}
    teams = set(fx_ls["home_id"]) | set(fx_ls["away_id"])
    n_teams = len(teams)
    tab = {t: [0, 0, 0, 0] for t in teams}     # played, pts, gf, ga
    past = fx_ls[(fx_ls["ts"] < ts) & fx_ls["finished"]]
    for r in past.itertuples():
        h, a, gh, ga = r.home_id, r.away_id, r.gh, r.ga
        tab[h][0] += 1; tab[a][0] += 1
        tab[h][2] += gh; tab[h][3] += ga; tab[a][2] += ga; tab[a][3] += gh
        if gh > ga: tab[h][1] += 3
        elif gh == ga: tab[h][1] += 1; tab[a][1] += 1
        else: tab[a][1] += 3
    order = sorted(tab, key=lambda t: (-tab[t][1], -(tab[t][2] - tab[t][3]), -tab[t][2], t))
    rank = {t: i + 1 for i, t in enumerate(order)}
    pts_at = lambda k: tab[order[min(max(k, 1), n_teams) - 1]][1]
    total_games = 2 * (n_teams - 1)
    for side, t in (("h", home_id), ("a", away_id)):
        pl, pt, gf, ga = tab[t]
        out[f"{side}_rank"] = float(rank[t])
        out[f"{side}_ppg"] = pt / pl if pl else np.nan
        out[f"{side}_gd_pg"] = (gf - ga) / pl if pl else np.nan
        out[f"{side}_season_frac"] = min(pl / total_games, 1.0) if total_games else np.nan
        out[f"{side}_pts_to_first"] = float(pts_at(1) - pt)
        out[f"{side}_pts_to_top4"] = float(pts_at(4) - pt) if n_teams >= 8 else np.nan
        out[f"{side}_pts_over_drop"] = float(pt - pts_at(n_teams - 3)) if n_teams >= 8 else np.nan
        out[f"{side}_games_left"] = float(max(total_games - pl, 0))
    out["n_teams"] = float(n_teams)
    return out


def build_referee_index(fx, st_by_fixture, ev_by_fixture):
    """Съдия -> списък (ts, мач-метрики) на ИЗИГРАНИТЕ мачове; ползва се само с ts < ts на целевия мач."""
    idx = {}
    for r in fx[fx["finished"] & fx["referee"].notna()].itertuples():
        key = str(r.referee).strip().lower()
        s = st_by_fixture.get(r.fixture_id)
        m = {"ts": r.ts, "goals": r.gh + r.ga, "home_win": float(r.gh > r.ga),
             "yellow": s[0] if s else np.nan, "red": s[1] if s else np.nan, "fouls": s[2] if s else np.nan,
             "pens": ev_by_fixture.get(r.fixture_id, np.nan)}
        idx.setdefault(key, []).append(m)
    for k in idx:
        idx[k].sort(key=lambda m: m["ts"])
    return idx


# ----------------------------------------------------------------------------------------------- основно
def build(core, raw, progress=False):
    """core: DataFrame (fixture_id, league, date, hg, ag, lam, mu, rho); raw: load_raw()/truncate(). -> DataFrame."""
    fx = raw["fx"]
    recs = team_match_records(raw)
    hist = History(recs)
    fx_by_id = fx.set_index("fixture_id")
    # разписание на отбор (за "евромач следва")
    sched = {}
    for r in fx.itertuples():
        for t in (r.home_id, r.away_id):
            sched.setdefault(int(t), []).append((r.ts, r.league))
    for t in sched:
        sched[t].sort()
    # съдии
    st_by = {}
    for r in recs:
        if r["has_stats"] and r["is_home"]:
            st_by[r["fixture_id"]] = (r["m_yellow"], r["m_red"], r["m_fouls"])
    pens_by = {}
    for r in recs:
        if r["has_events"] and r["is_home"]:
            pens_by[r["fixture_id"]] = r["pen_for"] + r["pen_against"]
    ref_idx = build_referee_index(fx, st_by, pens_by)
    ref_ts = {k: [m["ts"] for m in v] for k, v in ref_idx.items()}
    fx_ls = {k: g for k, g in fx.groupby(["league", "season"])}
    lu_by = raw["idx"]["lu"]
    inj_by = raw["idx"]["inj"]
    inj_cov = raw["inj_cov"]
    rows = []
    for i, c in enumerate(core.itertuples()):
        if c.fixture_id not in fx_by_id.index:
            continue
        f = fx_by_id.loc[c.fixture_id]
        ts, league, season = int(f["ts"]), f["league"], int(f["season"])
        hid, aid = int(f["home_id"]), int(f["away_id"])
        row = {"fixture_id": c.fixture_id, "league": league, "season": season, "date": c.date, "ts": ts,
               "hg": c.hg, "ag": c.ag, "lam": c.lam, "mu": c.mu, "rho": c.rho, "is_cup": float(league in CUPS)}
        dt = pd.Timestamp(ts, unit="s")
        row.update({"kick_hour": float(dt.hour), "weekday": float(dt.weekday()), "month": float(dt.month)})
        rn = pd.to_numeric(pd.Series([str(f["round"]).split("-")[-1].strip()]), errors="coerce").iloc[0]
        row["round_no"] = float(rn) if pd.notna(rn) else np.nan
        lu = lu_by.get(c.fixture_id)
        for side, tid, oid in (("h", hid, aid), ("a", aid, hid)):
            prior = hist.prior(tid, ts)
            euro_future = any(lg in CUPS and ts < t2 <= ts + 4 * 86400 for t2, lg in sched.get(tid, [])[
                bisect.bisect_right([x[0] for x in sched.get(tid, [])], ts):][:6])
            pre = {f"{side}_{k}": v for k, v in block_rest(prior, ts, euro_future).items()}
            row.update(pre)
            row.update({f"{side}_{k}": v for k, v in block_form(prior).items()})
            squad = starters = coach = None
            t = lu.get(tid) if lu is not None else None
            if t is not None:
                squad, starters, coach = t["squad"], t["starters"], (t["coach_id"], t["coach"])
            row.update({f"{side}_{k}": v for k, v in block_absent(prior, squad, starters, coach, ts).items()})
            # контузени по мача (предмачова информация); NaN, ако за лигата-сезона няма записи изобщо
            if (league, season) in inj_cov:
                gi = (inj_by.get(c.fixture_id) or {}).get(tid)
                row[f"{side}_inj_missing"] = float(gi[0]) if gi is not None else 0.0
                row[f"{side}_inj_quest"] = float(gi[1]) if gi is not None else 0.0
            else:
                row[f"{side}_inj_missing"] = row[f"{side}_inj_quest"] = np.nan
        if league not in CUPS and (league, season) in fx_ls:
            row.update(standings_features(fx_ls[(league, season)], ts, hid, aid))
        # съдия
        ref = f["referee"]
        keys = ["ref_n", "ref_yellow", "ref_red", "ref_fouls", "ref_pens", "ref_goals", "ref_home_win"]
        if pd.notna(ref) and str(ref).strip():
            k = str(ref).strip().lower()
            # (поправено при проверката срещу изтичане: преди това "има ли съдията изобщо мачове в данните" зависеше и от БЪДЕЩИ мачове)
            prior_m = ref_idx.get(k, [])[:bisect.bisect_left(ref_ts.get(k, []), ts)]
            row["ref_n"] = float(len(prior_m))
            for name in ("yellow", "red", "fouls", "pens", "goals", "home_win"):
                row[f"ref_{name}"] = _mean([m[name] for m in prior_m])
        else:
            row.update({k: np.nan for k in keys})
        if "h_rest_days" in row:
            row["rest_diff"] = row["h_rest_days"] - row["a_rest_days"] if pd.notna(row["h_rest_days"]) and pd.notna(row["a_rest_days"]) else np.nan
        rows.append(row)
        if progress and i % 2000 == 0:
            print(i, flush=True)
    return pd.DataFrame(rows)


def main():
    core = pd.read_csv(os.path.join(ROOT, "features", "core_lam_mu.csv"))
    out = os.path.join(ROOT, "features", "features_table.csv.gz")
    if "--hist" in sys.argv:
        # ZADACHA_RAZVITIE т.3: таблица САМО за мачовете от удълженото назад ядро (features/core_lam_mu_hist.csv), с данните от hist/
        # отгоре на живите. Сегашната таблица не се пипа.
        EXTRA_DIRS.append(os.path.join(ROOT, "hist"))
        core = pd.read_csv(os.path.join(ROOT, "features", "core_lam_mu_hist.csv"))
        out = os.path.join(ROOT, "features", "features_table_hist.csv.gz")
    raw = index_raw(load_raw())
    print("данни:", {k: len(v) for k, v in raw.items() if hasattr(v, "__len__") and k != "idx"}, flush=True)
    tab = build(core, raw, progress=True)
    tab.to_csv(out, index=False)
    print(len(tab), "реда,", len(tab.columns), "колони ->", out)


if __name__ == "__main__":
    main()
