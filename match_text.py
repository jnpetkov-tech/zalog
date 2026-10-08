"""match_text.py — текст на мача от НАШИТЕ данни (ZADACHA_TEKST, Дака 06.10.2026).

Нищо не се пише от езиков модел и нищо не се измисля: всяко изречение е шаблон, попълнен с числа от СЪЩИТЕ данни и СЪЩИЯ код като таблицата
с признаци (features/build_features.py: load_raw/index_raw/team_match_records/History/block_rest/block_absent и правилото на времето - само
мачове преди началото), плюс процентите на модела от predictions_snapshot (същите, които сайтът показва). Ако някое парче данни липсва,
изречението просто го няма.

Всяко изречение пази `facts` - числата, с които е попълнено (за автоматичната проверка validation/tekst_proverka_20261006.py: всяко число в
текста трябва да е сред тях, а те - да съвпадат с независимо пресметнатото от суровите CSV и от снимката).

Две половини (както layer_live.py):
  refresh(fixture_ids) - САМО от самостоятелните build_predictions_snapshot.py (пълната) и snapshot_final.py (бързата, след съставите):
                         зарежда данните, смята изреченията и ги пише в таблица match_text (predictions.db). Никога не хвърля.
  get_texts(ids)       - от Flask: само sqlite. Грешка/изключен превключвател -> {} (страницата е като преди).
Превключвател MATCH_TEXT в .env (0/липсва = нищо не се смята и нищо не се показва).

Забранени думи (тест в проверката): букмейкъри, коефициенти, "пазар", съвети за залог, "сигурно", "гарантирано".

ZADACHA_EZIK (08.10.2026): всяко изречение има и английски вариант "text_en" (+ "names_en" - имената в него, за проверката на числата),
смятан в същата функция от същите facts. Българският "text" не се променя. get_texts(..., lang="en") чете "text_en".
Забранени думи и на английски: bookmaker, odds, market, bet, wager, stake, sure, certain, guarantee.
"""
import json
import math
import os
import sqlite3
import time
from datetime import datetime, timedelta

import config

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "predictions.db")
LOG_PATH = os.path.join(ROOT, "match_text_log.txt")

MAX_SENTENCES = 5
MIN_SENTENCES = 3            # ако има толкова; при по-малко данни - колкото има (липсващите изречения ги няма)
FORM_N = 5                   # форма: последните 5 мача
MIN_FORM = 3                 # под 3 мача история - няма изречение за формата
USUAL_N = 10                 # титуляр: по минутите в последните 10 мача със състав (виж USUAL_MIN)
MIN_TABLE_PLAYED = 3         # класиране - само след поне 3 изиграни мача и на двата отбора
MIN_REF = 5                  # съдия - поне 5 предишни мача в базата
NEW_COACH_MAX = 5            # "нов треньор" - начело от най-много 5 мача (по съставите), а преди него е имало друг
EURO_DAYS = 4                # евромач до 4 дни преди/след (= build_features.block_rest)
NAMES_MAX = 4                # колко имена на отсъстващи се изреждат

CUP_NAMES = {"champions_league": "Шампионската лига", "europa_league": "Лига Европа", "conference_league": "Лигата на конференциите"}
CUPS = set(CUP_NAMES)
BG_LEAGUES = {"bulgaria", "bulgaria2"}
USUAL_MIN = 45               # ZADACHA_TEKST_2: титуляр = средно >= 45 мин. на мач в последните USUAL_N мача със състав (отсъствията - 0)
MIN_SCORER = 2               # "голмайсторът на отбора" - най-много голове (сам) в същите мачове, поне 2, при събития за всичките

BANNED = ["букмейк", "коефициент", "пазар", "залог", "залага", "заложи", "сигурн", "гарантира"]

DDL = """
CREATE TABLE IF NOT EXISTS match_text (
    fixture_id INTEGER PRIMARY KEY,
    league TEXT, match_date TEXT, computed_at TEXT NOT NULL,
    has_lineups INTEGER,        -- 1 = смятан след обявяване на съставите на двата отбора
    sentences TEXT,             -- JSON [{"kind", "score", "text", "facts", "text_en", "names_en"}], най-интересните първи
    model_pre TEXT              -- JSON {"home_win", "draw", "away_win"} - процентите преди съставите (за "какво се промени")
)"""


def enabled():
    return bool(getattr(config, "MATCH_TEXT", False))


def log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{datetime.utcnow().isoformat(timespec='seconds')} {msg}\n")
    except Exception:
        pass


def _connect(db_path=DB_PATH):
    con = sqlite3.connect(db_path, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    return con


# ----------------------------------------------------------------------------------------------- Flask (само sqlite)
def page_order(sentences):
    """ZADACHA_TEKST_2, т.2: за страницата на мача - изречението за модела ("Моделът дава ...") винаги последно, като извод;
    останалите - по интересност, както са записани. Картата в списъка ползва записания ред (първото = най-силното)."""
    return [s for s in sentences if s.get("kind") != "model"] + [s for s in sentences if s.get("kind") == "model"]


def get_texts(fixture_ids, db_path=None, page=False, lang="bg"):
    """-> {fixture_id: [изречение, ...]} (най-интересните първи; page=True - изречението за модела последно).
    Изключено/грешка/няма таблица -> {}.
    lang="en" (ZADACHA_EZIK): "text_en"; изречение без него (стари редове) не се показва; без нито едно - мачът няма текст."""
    key = "text_en" if lang == "en" else "text"
    if not enabled() or not fixture_ids:
        return {}
    try:
        con = _connect(db_path or DB_PATH)
        try:
            ids = [int(f) for f in fixture_ids]
            out = {}
            for i in range(0, len(ids), 500):
                part = ids[i:i + 500]
                q = f"SELECT fixture_id, sentences FROM match_text WHERE fixture_id IN ({','.join('?' * len(part))})"
                for fid, js in con.execute(q, part):
                    ss = json.loads(js or "[]")
                    texts = [s[key] for s in (page_order(ss) if page else ss) if s.get(key)]
                    if texts:
                        out[int(fid)] = texts
            return out
        finally:
            con.close()
    except Exception as e:
        log(f"get_texts: {type(e).__name__}: {e}")
        return {}


# ----------------------------------------------------------------------------------------------- граматика
def fmt1(x):
    """1.45 -> "1,5" (десетична запетая, един знак)."""
    return f"{x:.1f}".replace(".", ",")


def r1(x):
    return round(float(x) + 1e-9, 1)


def noun(n, one, many):
    return f"{n} {one if n == 1 else many}"


def pts_phrase(p):
    return "без точки" if p == 0 else f"с {noun(p, 'точка', 'точки')}"


def ordinal(n):
    """Пореден номер в среден род (за "място"): 1-во, 2-ро, 3-то, 7-мо, 11-то, 21-во."""
    n = int(n)
    if 11 <= n % 100 <= 19:
        suf = "то"
    else:
        suf = {1: "во", 2: "ро", 7: "мо", 8: "мо"}.get(n % 10, "то")
    return f"{n}-{suf}"


def join_and(parts):
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " и " + parts[-1]


def cap(s):
    return s[:1].upper() + s[1:] if s else s


# ZADACHA_EZIK (08.10.2026): английският вариант на всяко изречение ("text_en") - шаблони от СЪЩИТЕ facts, до българския.
# Числата - с десетична точка; имената на хората и отборите - оригиналните от API-то (clean_name), не на кирилица.
CUP_NAMES_EN = {"champions_league": "the Champions League", "europa_league": "the Europa League",
                "conference_league": "the Conference League"}
CUP_SHORT_EN = {"champions_league": "Champions League", "europa_league": "Europa League", "conference_league": "Conference League"}
COUNT_EN = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}


def fmt1_en(x):
    """1.45 -> "1.5" (десетична точка, един знак)."""
    return f"{x:.1f}"


def plural(n, one, many):
    """1 match / 2 matches."""
    return f"{n} {one if n == 1 else many}"


def ordinal_en(n):
    """1st, 2nd, 3rd, 4th, 11th, 12th, 13th, 21st, 22nd."""
    n = int(n)
    suf = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def join_and_en(parts):
    """"a, b and c"."""
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def pts_phrase_en(p):
    return "with no points" if p == 0 else f"with {plural(p, 'point', 'points')}"


BANNED_EN_RE = {"bookmaker": r"bookmakers?", "odds": r"odds", "market": r"markets?", "bet": r"bet(?:s|ting|tor|tors)?",
                "wager": r"wager\w*", "stake": r"stakes?", "sure": r"sure(?:ly)?", "certain": r"certain(?:ly|ty)?",
                "guarantee": r"guarantee\w*"}


def banned_en(text, names=()):
    """Забранените думи в английския текст - цели думи, след като имената (отбори, хора) са махнати ("Real Betis" не е "bet")."""
    import re
    t = text
    for nm in sorted((n for n in names if n), key=len, reverse=True):
        t = t.replace(nm, " ")
    return [w for w, rx in BANNED_EN_RE.items() if re.search(rf"\b{rx}\b", t, flags=re.I)]


# ----------------------------------------------------------------------------------------------- данни
def clean_name(name):
    """Някои имена идват от API-то двойно кодирани ("VÃ­ctor Moreno") - връщаме ги ("Víctor Moreno"); иначе - без промяна."""
    if not isinstance(name, str):
        return name
    name = name.strip()
    if "Ã" in name or "Â" in name:
        try:
            return name.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return name
    return name


class Data:
    """Суровите данни (същите като таблицата с признаци) + индекси за текста. Тежко (~17 с) - само в самостоятелните скриптове."""

    def __init__(self, raw=None, names_raw=None):
        """names_raw: откъде са имената на играчите/треньорите и списъкът с контузени (за проверката на минали мачове - пълните данни,
        докато raw е отрязан с build_features.truncate, който не пази таблиците)."""
        from features import build_features as bf
        self.bf = bf
        self.raw = raw if raw is not None else bf.index_raw(bf.load_raw())
        self.recs = bf.team_match_records(self.raw)
        self.hist = bf.History(self.recs)
        fx = self.raw["fx"]
        self.fx = fx
        self.fx_by_id = fx.set_index("fixture_id")
        self.sched = {}
        for r in fx.itertuples():
            for t in (r.home_id, r.away_id):
                self.sched.setdefault(int(t), []).append((int(r.ts), r.league, int(r.fixture_id)))
        for t in self.sched:
            self.sched[t].sort()
        nr = names_raw if names_raw is not None else self.raw
        lu = nr["lineups"]
        self.player_name = {}
        self.coach_at = {}          # (мач, отбор) -> име на треньора; по id не става: API-то дава различни id (вкл. 0) за един и същи човек
        if len(lu):
            for pid, name in zip(lu["player_id"], lu["player"]):
                if pid == pid and isinstance(name, str):
                    self.player_name[int(pid)] = clean_name(name)
            for fid, tid, cid, name in zip(lu["fixture_id"], lu["team_id"], lu["coach_id"], lu["coach"]):
                if tid == tid and isinstance(name, str) and name.strip():
                    self.coach_at[(int(fid), int(tid))] = (clean_name(name), int(cid) if cid == cid else None)
        # ZADACHA_TEKST_2: българските отбори (играли в bulgaria/bulgaria2) - хората им се пишат на кирилица (bg_names.person_to_cyrillic)
        self.bg_teams = {int(t) for c in ("home_id", "away_id") for t in fx.loc[fx["league"].isin(BG_LEAGUES), c]}
        # пълното име от събитията ("Dominik Kajzer" вместо "D. Kajzer") - само за българските отбори (за по-добра транслитерация)
        self.player_full = {}
        ev = nr.get("events")
        if ev is not None and len(ev):
            for pid, nm in list(zip(ev["player_id"], ev["player"])) + list(zip(ev["assist_id"], ev["assist"])):
                if pid == pid and isinstance(nm, str) and "." not in nm and nm.strip():
                    self.player_full[int(pid)] = clean_name(nm)
        self.name_log = {}           # латиница -> (кирилица, източник) за прегледа на Дака (validation/tekst2_imena_*)
        # минути и голове по (мач, отбор) - от съставите + смените/червените картони (събитията); без събития - титулярите по 90
        self.mins, self.goals = {}, {}
        ix = self.raw["idx"]
        for fid, teams in ix["lu"].items():
            evs = ix["ev"].get(fid)
            for tid, t in teams.items():
                self.mins[(fid, tid)] = (minutes_from(t["starters"], evs, tid), evs is not None)
            for typ, detail, team_id, pid, _a, _el in (evs or []):
                if typ == "Goal" and detail not in ("Missed Penalty", "Own Goal") and team_id == team_id and pid == pid:
                    g = self.goals.setdefault((fid, int(team_id)), {})
                    g[int(pid)] = g.get(int(pid), 0) + 1
        inj = nr["injuries"]
        self.inj_by = {}
        if len(inj):
            for r in inj.itertuples(index=False):
                if r.type == "Missing Fixture" and r.team_id == r.team_id and r.player_id == r.player_id:
                    self.inj_by.setdefault(int(r.fixture_id), {}).setdefault(int(r.team_id), {})[int(r.player_id)] = clean_name(r.player)
        # съдии: същият индекс като build_features.build (изиграни мачове, по ts)
        st_by, pens_by = {}, {}
        for r in self.recs:
            if r["has_stats"] and r["is_home"]:
                st_by[r["fixture_id"]] = (r["m_yellow"], r["m_red"], r["m_fouls"])
            if r["has_events"] and r["is_home"]:
                pens_by[r["fixture_id"]] = r["pen_for"] + r["pen_against"]
        self.ref_idx = bf.build_referee_index(fx, st_by, pens_by)
        self.fx_ls = {k: g for k, g in fx.groupby(["league", "season"])}


    def add_upcoming_injuries(self, db_path):
        """Контузените/наказаните за предстоящите мачове (injuries_upcoming.py -> таблица injuries_players) - само "Missing Fixture".
        За мач, който го има там, важи този списък (по-пресен от {лига}_injuries.csv). Няма таблица/грешка -> нищо."""
        try:
            con = _connect(db_path)
            try:
                rows = con.execute("SELECT fixture_id, team_id, player_id, player, type FROM injuries_players").fetchall()
            finally:
                con.close()
        except Exception:
            return 0
        fresh = {}
        for fid, tid, pid, name, typ in rows:
            d = fresh.setdefault(int(fid), {})
            if typ == "Missing Fixture" and tid is not None and pid is not None:
                d.setdefault(int(tid), {})[int(pid)] = clean_name(name)
        self.inj_by.update(fresh)
        return len(fresh)

    def person(self, name, tid, pid=None):
        """Име на играч/треньор за текста: за българските отбори - на кирилица (bg_names), иначе както е."""
        if not name or tid is None or int(tid) not in self.bg_teams:
            return name
        if pid is not None and pid in self.player_full:
            full = self.player_full[pid]
            if _name_tokens(full) and (_name_tokens(full) & _name_tokens(name)):
                name = full
        from bg_names import person_to_cyrillic
        cyr, src = person_to_cyrillic(name)
        self.name_log[name] = (cyr, src)
        return cyr

    def player(self, pid, tid):
        nm = self.player_name.get(pid)
        return self.person(nm, tid, pid) if nm else None


def minutes_from(starters, evs, tid):
    """{player_id: изиграни минути (0-90)}: титулярите от 0, влезлите от минутата на смяната; излиза при смяна или червен картон.
    Смяна в API-то: player_id = излизащият, assist_id = влизащият. Без събития -> титулярите по 90."""
    on = {int(p): 0.0 for p in starters}
    off = {}
    for typ, detail, team_id, pid, aid, el in (evs or []):
        if team_id != team_id or int(team_id) != int(tid):
            continue
        e = min(max(float(el), 0.0), 90.0) if el == el and el is not None else 90.0
        if typ == "subst":
            if pid == pid and pid is not None and int(pid) in on and int(pid) not in off:
                off[int(pid)] = e
            if aid == aid and aid is not None and int(aid) not in on:
                on[int(aid)] = e
        elif typ == "Card" and detail in ("Red Card", "Second Yellow card") and pid == pid and pid is not None:
            if int(pid) in on and int(pid) not in off:
                off[int(pid)] = e
    return {p: max(0.0, off.get(p, 90.0) - t) for p, t in on.items()}


def _is_nan(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


def table_at(fx_ls, ts):
    """Класиране към ts (резултатите на мачовете в същата лига-сезон със ts < ts) - като build_features.standings_features.
    -> (order [team_id], tab {team_id: [изиграни, точки, вкарани, допуснати]})."""
    teams = set(fx_ls["home_id"]) | set(fx_ls["away_id"])
    tab = {int(t): [0, 0, 0, 0] for t in teams}
    past = fx_ls[(fx_ls["ts"] < ts) & fx_ls["finished"]]
    for r in past.itertuples():
        h, a, gh, ga = int(r.home_id), int(r.away_id), int(r.gh), int(r.ga)
        tab[h][0] += 1; tab[a][0] += 1
        tab[h][2] += gh; tab[h][3] += ga; tab[a][2] += ga; tab[a][3] += gh
        if gh > ga: tab[h][1] += 3
        elif gh == ga: tab[h][1] += 1; tab[a][1] += 1
        else: tab[a][1] += 3
    order = sorted(tab, key=lambda t: (-tab[t][1], -(tab[t][2] - tab[t][3]), -tab[t][2], t))
    return order, tab


def usual_by_minutes(D, tid, prior):
    """ZADACHA_TEKST_2: титулярите по минути в последните USUAL_N мача със състав (същото правило на времето - само минали мачове).
    -> None (под 3 мача) или {"n", "n_ev", "avg" {играч: средно мин.}, "goals" {играч: голове}, "pos" {играч: G/D/M/F}, "scorer"}."""
    pl = [r for r in prior if r["has_lineup"]][-USUAL_N:]
    if len(pl) < 3:
        return None
    n = len(pl)
    tot, goals, pos_votes, n_ev = {}, {}, {}, 0
    for r in pl:
        mins, _exact = D.mins.get((r["fixture_id"], int(tid)), ({}, False))
        for p, m in mins.items():
            tot[p] = tot.get(p, 0.0) + m
        if r["has_events"]:
            n_ev += 1
            for p, g in D.goals.get((r["fixture_id"], int(tid)), {}).items():
                goals[p] = goals.get(p, 0) + g
        for p, ps in r["pos"].items():
            if ps in ("G", "D", "M", "F"):
                pos_votes.setdefault(p, {}).setdefault(ps, 0)
                pos_votes[p][ps] += 1
    avg = {p: int(round(t / n)) for p, t in tot.items() if t / n >= USUAL_MIN}
    pos_of = {p: max(v.items(), key=lambda kv: (kv[1], kv[0]))[0] for p, v in pos_votes.items()}
    scorer = None
    if n_ev == n and goals:
        top = max(goals.values())
        best = [p for p, g in goals.items() if g == top]
        if top >= MIN_SCORER and len(best) == 1:
            scorer = best[0]
    return {"n": n, "n_ev": n_ev, "avg": avg, "goals": goals, "pos": pos_of, "scorer": scorer}


# ----------------------------------------------------------------------------------------------- изречения
def _team_ctx(D, tid, ts):
    return D.hist.prior(int(tid), ts)


def s_form(H, A, ph, pa, en=None):
    n = min(FORM_N, len(ph), len(pa))
    if n < MIN_FORM:
        return None
    He, Ae = en or (H, A)
    facts = {"n": n}
    phrases, streak = [], False
    pts, phrases_en = [], []
    for tag, T, Te, p in (("h", H, He, ph), ("a", A, Ae, pa)):
        last = p[-n:]
        w = sum(1 for r in last if r["pts"] == 3)
        d = sum(1 for r in last if r["pts"] == 1)
        l = n - w - d
        gf = int(sum(r["gf"] for r in last))
        ga = int(sum(r["ga"] for r in last))
        facts.update({f"{tag}_w": w, f"{tag}_d": d, f"{tag}_l": l, f"{tag}_gf": gf, f"{tag}_ga": ga})
        pts.append(3 * w + d)
        goals = f"голове {gf}:{ga}"
        goals_en = f"{gf} scored, {ga} conceded"
        if w == n:
            ph_ = f"{T} спечели всичките си последни {n} мача ({goals})"
            pe = f"{Te} has won all of its last {n} matches ({goals_en})"
            streak = True
        elif l == n:
            ph_ = f"{T} загуби последните си {n} мача ({goals})"
            pe = f"{Te} has lost its last {n} matches ({goals_en})"
            streak = True
        elif w == 0:
            wl = join_and([noun(d, 'равенство', 'равенства') if d else '', noun(l, 'загуба', 'загуби') if l else ''])
            ph_ = f"{T} е без победа в последните си {n} мача ({wl}, {goals})"
            wle = join_and_en([plural(d, 'draw', 'draws') if d else '', plural(l, 'defeat', 'defeats') if l else ''])
            pe = f"{Te} is without a win in its last {n} matches ({wle}; {goals_en})"
            streak = True
        else:
            wl = join_and([noun(w, 'победа', 'победи'), noun(d, 'равенство', 'равенства') if d else '', noun(l, 'загуба', 'загуби') if l else ''])
            ph_ = f"{T} има {wl} в последните {n} мача ({goals})"
            wle = join_and_en([plural(w, 'win', 'wins'), plural(d, 'draw', 'draws') if d else '', plural(l, 'defeat', 'defeats') if l else ''])
            pe = f"{Te} has {wle} in its last {n} matches ({goals_en})"
        phrases.append(ph_)
        phrases_en.append(pe)
    score = 30 + 2.5 * abs(pts[0] - pts[1]) + (20 if streak else 0)
    return {"kind": "form", "score": score, "text": f"{phrases[0]}, а {phrases[1]}.", "facts": facts,
            "text_en": f"{phrases_en[0]}, while {phrases_en[1]}."}


def s_venue(H, A, ph, pa, en=None):
    hh = [r for r in ph if r["is_home"]][-FORM_N:]
    aa = [r for r in pa if not r["is_home"]][-FORM_N:]
    if len(hh) < MIN_FORM or len(aa) < MIN_FORM:
        return None
    He, Ae = en or (H, A)
    wh = sum(1 for r in hh if r["pts"] == 3)
    wa = sum(1 for r in aa if r["pts"] == 3)
    nh, na = len(hh), len(aa)
    facts = {"h_n": nh, "h_w": wh, "a_n": na, "a_w": wa}
    p1 = (f"У дома {H} спечели {wh} от последните си {nh} домакинства" if wh else
          f"У дома {H} няма победа в последните си {nh} домакинства")
    p2 = (f"{A} спечели {wa} от последните си {na} гостувания" if wa else
          f"{A} няма победа в последните си {na} гостувания")
    e1 = (f"At home, {He} has won {wh} of its last {nh} home matches" if wh else
          f"At home, {He} has not won any of its last {nh} home matches")
    e2 = (f"{Ae} has won {wa} of its last {na} away matches" if wa else
          f"{Ae} has not won any of its last {na} away matches")
    extreme = wh in (0, nh) or wa in (0, na)
    score = 20 + 25 * abs(wh / nh - wa / na) + (15 if extreme else 0)
    return {"kind": "venue", "score": score, "text": f"{p1}, а {p2}.", "facts": facts, "text_en": f"{e1}, while {e2}."}


def s_table(D, league, season, ts, hid, aid, H, A, name_of, en=None, name_of_en=None):
    if league in CUPS or (league, season) not in D.fx_ls:
        return None
    order, tab = table_at(D.fx_ls[(league, season)], ts)
    n_teams = len(order)
    if n_teams < 8 or hid not in tab or aid not in tab:
        return None
    if tab[hid][0] < MIN_TABLE_PLAYED or tab[aid][0] < MIN_TABLE_PLAYED:
        return None
    rank = {t: i + 1 for i, t in enumerate(order)}
    leader, second = order[0], order[1]
    He, Ae = en or (H, A)
    name_of_en = name_of_en or name_of
    facts = {"n_teams": n_teams}
    phrases, score = [], 25
    mentioned, mentioned_en, phrases_en = [], [], []

    def nm(tid):
        mentioned.append(name_of(tid))
        mentioned_en.append(name_of_en(tid))
        return mentioned[-1]
    for tag, T, Te, tid in (("h", H, He, hid), ("a", A, Ae, aid)):
        rk, pts = rank[tid], tab[tid][1]
        facts.update({f"{tag}_rank": rk, f"{tag}_pts": pts})
        if rk == 1:
            gap = pts - tab[second][1]
            facts[f"{tag}_gap"] = gap
            ph_ = f"{T} води класирането {pts_phrase(pts)}"
            ph_ += (f", с {noun(gap, 'точка', 'точки')} пред {nm(second)}" if gap > 0 else f", наравно по точки с {nm(second)}")
            pe = f"{Te} leads the table {pts_phrase_en(pts)}"
            pe += (f", {plural(gap, 'point', 'points')} ahead of {mentioned_en[-1]}" if gap > 0 else
                   f", level on points with {mentioned_en[-1]}")
            score += 20
        else:
            gap = tab[leader][1] - pts
            facts[f"{tag}_gap"] = gap
            ph_ = f"{T} е на {ordinal(rk)} място {pts_phrase(pts)}"
            pe = f"{Te} is {ordinal_en(rk)} {pts_phrase_en(pts)}"
            if rk <= 4:
                ph_ += (f", на {noun(gap, 'точка', 'точки')} от лидера {nm(leader)}" if gap > 0 else
                        f", наравно по точки с лидера {nm(leader)}")
                pe += (f", {plural(gap, 'point', 'points')} behind the leader, {mentioned_en[-1]}" if gap > 0 else
                       f", level on points with the leader, {mentioned_en[-1]}")
                score += 10
            elif rk <= 8:
                g4 = tab[order[3]][1] - pts
                facts[f"{tag}_gap4"] = g4
                facts["place4"] = 4
                ph_ += (f", на {noun(g4, 'точка', 'точки')} от {ordinal(4)} място" if g4 > 0 else f", наравно по точки с {ordinal(4)} място")
                pe += (f", {plural(g4, 'point', 'points')} behind {ordinal_en(4)} place" if g4 > 0 else
                       f", level on points with {ordinal_en(4)} place")
            elif rk >= n_teams - 2:
                ph_ += f" (от {n_teams} отбора)"
                pe += f" (of {n_teams} teams)"
                score += 15
        phrases.append(ph_)
        phrases_en.append(pe)
    if rank[hid] <= 4 and rank[aid] <= 4:
        score += 25
    return {"kind": "table", "score": score, "text": f"{cap(phrases[0])}, а {phrases[1]}.", "facts": facts, "names": mentioned,
            "text_en": f"{cap(phrases_en[0])}, while {phrases_en[1]}.", "names_en": mentioned_en}


def s_shots(H, A, ph, pa, en=None):
    He, Ae = en or (H, A)
    out = {}
    for tag, p in (("h", ph), ("a", pa)):
        ps = [r for r in p[-FORM_N:] if r["has_stats"]]
        out[tag] = ps
    if len(out["h"]) < 4 or len(out["a"]) < 4:
        return None
    full = len(out["h"]) == FORM_N and len(out["a"]) == FORM_N
    when = f"в последните {FORM_N} мача" if full else "в последните си мачове"
    when_en = f"in the last {FORM_N} matches" if full else "in recent matches"

    def mean(ps, k):
        v = [r[k] for r in ps if not _is_nan(r.get(k))]
        return (sum(v) / len(v)) if len(v) >= 4 else None

    xg = {t: (mean(out[t], "xg_for"), mean(out[t], "xg_ag")) for t in ("h", "a")}
    facts = {"n": FORM_N} if full else {}
    if all(v is not None for t in ("h", "a") for v in xg[t]):
        hf, hg_, af, ag_ = (r1(xg["h"][0]), r1(xg["h"][1]), r1(xg["a"][0]), r1(xg["a"][1]))
        facts.update({"h_xg_for": hf, "h_xg_ag": hg_, "a_xg_for": af, "a_xg_ag": ag_})
        d = (hf - hg_) - (af - ag_)
        text = (f"По очакваните голове (xG) {when} {H} си създава средно {fmt1(hf)} и допуска {fmt1(hg_)} на мач, "
                f"а {A} — {fmt1(af)} и {fmt1(ag_)}.")
        text_en = (f"By expected goals (xG) {when_en}, {He} creates {fmt1_en(hf)} per match on average and concedes {fmt1_en(hg_)}, "
                   f"while {Ae} creates {fmt1_en(af)} and concedes {fmt1_en(ag_)}.")
        return {"kind": "xg", "score": 15 + 15 * abs(d), "text": text, "facts": facts, "text_en": text_en}
    sh = {t: (mean(out[t], "sh_for"), mean(out[t], "sot_for"), mean(out[t], "sh_ag")) for t in ("h", "a")}
    if not all(v is not None for t in ("h", "a") for v in sh[t]):
        return None
    hs, hsot, hsa = (r1(x) for x in sh["h"])
    as_, asot, asa = (r1(x) for x in sh["a"])
    facts.update({"h_sh": hs, "h_sot": hsot, "h_sh_ag": hsa, "a_sh": as_, "a_sot": asot, "a_sh_ag": asa})
    d = (hs - hsa) - (as_ - asa)
    text = (f"{cap(when)} {H} отправя средно {fmt1(hs)} удара на мач ({fmt1(hsot)} във вратата) и допуска {fmt1(hsa)}, "
            f"а {A} — {fmt1(as_)} ({fmt1(asot)} във вратата) и {fmt1(asa)}.")
    text_en = (f"{cap(when_en)}, {He} averages {fmt1_en(hs)} shots per match ({fmt1_en(hsot)} on target) and allows {fmt1_en(hsa)}, "
               f"while {Ae} averages {fmt1_en(as_)} ({fmt1_en(asot)} on target) and allows {fmt1_en(asa)}.")
    return {"kind": "shots", "score": 15 + 1.5 * abs(d), "text": text, "facts": facts, "text_en": text_en}


def _days(a_ts, b_ts):
    return int(round(abs(a_ts - b_ts) / 86400.0))


def s_rest(D, ts, hid, aid, H, A, ph, pa, en=None):
    """Почивка (дни от предишния мач) и евромач до EURO_DAYS дни преди/след. Почивката се казва само ако има евромач преди мача или
    разлика >= 3 дни при поне един отбор с <= 7 дни почивка; евромачът след срещата - винаги."""
    if not ph or not pa:
        return None
    He, Ae = en or (H, A)
    names_en = {"h": He, "a": Ae}
    facts, rest, prev_cup = {}, {}, {}
    for tag, p in (("h", ph), ("a", pa)):
        last = p[-1]
        rest[tag] = _days(ts, last["ts"])
        prev_cup[tag] = last["league"] if (last["league"] in CUPS and ts - last["ts"] <= EURO_DAYS * 86400) else None
    diff = abs(rest["h"] - rest["a"])
    say_rest = max(rest.values()) <= 30 and (any(prev_cup.values()) or (diff >= 3 and min(rest.values()) <= 7))
    parts, parts_en = [], []
    if say_rest:
        for tag, T in (("h", H), ("a", A)):
            facts[f"{tag}_rest"] = rest[tag]
            dd = noun(rest[tag], "ден", "дни")
            dde = plural(rest[tag], "day", "days")
            Te = names_en[tag]
            if prev_cup[tag]:
                parts.append(f"{T} излиза {dd} след мача си в {CUP_NAMES[prev_cup[tag]]}")
                parts_en.append(f"{Te} plays {dde} after its {CUP_SHORT_EN[prev_cup[tag]]} match")
            elif tag == "h" or prev_cup["h"]:
                parts.append(f"{T} има {dd} почивка")
                parts_en.append(f"{Te} has had {dde} of rest")
            else:
                parts.append(f"{T} — {dd}")
                parts_en.append(f"{Te} has had {dde}")
    nxt = {}
    for tag, tid in (("h", hid), ("a", aid)):
        for t2, lg, _f in D.sched.get(int(tid), []):
            if ts < t2 <= ts + EURO_DAYS * 86400 and lg in CUPS:
                nxt[tag] = (_days(t2, ts), lg)
                facts[f"{tag}_next"] = nxt[tag][0]
                break
    if not parts and not nxt:
        return None
    text = f"{parts[0]}, а {parts[1]}." if parts else ""
    text_en = f"{parts_en[0]}, while {parts_en[1]}." if parts_en else ""
    if len(nxt) == 2 and nxt["h"] == nxt["a"]:
        k, lg = nxt["h"]
        text += f" {noun(k, 'ден', 'дни')} след тази среща и двата отбора играят в {CUP_NAMES[lg]}."
        text_en += f" Both teams play in {CUP_NAMES_EN[lg]} {plural(k, 'day', 'days')} after this match."
    else:
        for tag, T in (("h", H), ("a", A)):
            if tag in nxt:
                k, lg = nxt[tag]
                text += f" {noun(k, 'ден', 'дни')} след тази среща {T} играе в {CUP_NAMES[lg]}."
                text_en += f" {names_en[tag]} plays in {CUP_NAMES_EN[lg]} {plural(k, 'day', 'days')} after this match."
    score = 20 + 15 * bool(nxt or any(prev_cup.values())) + (4 * min(diff, 6) if say_rest else 0)
    return {"kind": "rest", "score": score, "text": text.strip(), "facts": facts, "text_en": text_en.strip()}


def s_referee(D, f, ts):
    ref = f["referee"]
    if _is_nan(ref) or not str(ref).strip():
        return None
    k = str(ref).strip().lower()
    prior_m = [m for m in D.ref_idx.get(k, []) if m["ts"] < ts]
    if len(prior_m) < MIN_REF:
        return None
    n = len(prior_m)
    hw = round(100 * sum(m["home_win"] for m in prior_m) / n)
    ys = [m["yellow"] for m in prior_m if not _is_nan(m["yellow"])]
    facts = {"ref_n": n, "ref_hw": hw}
    text = f"Съдия на мача е {clean_name(str(ref))}: в предишните му {n} мача в нашата база домакините са печелили {hw}%"
    text_en = (f"The referee is {clean_name(str(ref))}: in the {n} previous matches with this referee in our database, "
               f"home teams won {hw}%")
    score = 10 + (10 if hw >= 60 or hw <= 35 else 0)
    if len(ys) >= MIN_REF:
        y = r1(sum(ys) / len(ys))
        facts["ref_y"] = y
        text += f", а жълтите картони са средно {fmt1(y)} на мач"
        text_en += f", with {fmt1_en(y)} yellow cards per match on average"
        score += 10 if (y >= 5.5 or y <= 3.0) else 0
    return {"kind": "ref", "score": score, "text": text + ".", "facts": facts, "names": [clean_name(str(ref))],
            "text_en": text_en + ".", "names_en": [clean_name(str(ref))]}


def _name_tokens(name):
    import unicodedata
    n = "".join(c for c in unicodedata.normalize("NFKD", name.lower()) if not unicodedata.combining(c))
    return {t for t in n.replace(".", " ").replace("-", " ").split() if len(t) >= 3}


def same_coach(a, b):
    """API-то дава един и същи треньор с различни id (вкл. 0 за различни хора) и различно изписване ("L. Spalletti" / "Luciano Spalletti",
    "Piero Gasperini Gian" / "G. Gasperini", "Rubén Albés" / "Ruben Albes"). Един и същи: еднакъв ненулев id ИЛИ обща дума от името (>= 3 букви)."""
    if not a or not b:
        return None
    (na, ia), (nb, ib) = a, b
    if ia and ib and ia == ib:
        return True
    return bool(_name_tokens(na) & _name_tokens(nb))


def s_coach(D, T, tid, prior, today, Te=None):
    Te = Te or T
    pl = [r for r in prior if r["has_lineup"]]
    if len(pl) < 3:
        return None
    seq = [D.coach_at.get((int(r["fixture_id"]), int(tid))) for r in pl]
    if today:
        if seq[-1] and same_coach(today, seq[-1]) is False:
            nm = D.person(today[0], tid)
            return {"kind": "coach", "score": 70, "text": f"На пейката на {T} днес е нов треньор — {nm}.", "facts": {},
                    "names": [nm], "tid": int(tid),
                    "text_en": f"{Te} has a new coach on the bench today: {today[0]}.", "names_en": [today[0]]}
        return None
    if not seq[-1]:
        return None
    k = 0
    for c in reversed(seq):
        if c and same_coach(c, seq[-1]):
            k += 1
        else:
            break
    if k > NEW_COACH_MAX or k == len(seq) or not seq[-k - 1]:
        return None                            # от началото на данните или без запис за предишния - не знаем дали е нов
    name = D.person(seq[-1][0], tid)
    text = (f"В последния мач начело на {T} беше {name} — различен треньор от предишните мачове." if k == 1 else
            f"{T} е с нов треньор: {name} води отбора от {k} мача насам.")
    ne = seq[-1][0]
    text_en = (f"In its last match {Te} was led by {ne}, a different coach from the previous matches." if k == 1 else
               f"{Te} has a new coach: {ne} has been in charge for the last {k} matches.")
    return {"kind": "coach", "score": 55 if k <= 3 else 35, "facts": {"coach_k": k}, "names": [name], "text": text, "tid": int(tid),
            "text_en": text_en, "names_en": [ne]}


COUNT_M = {1: "един", 2: "двама", 3: "трима", 4: "четирима", 5: "петима"}
ROLE = {"D": ("защитник", "защитници"), "M": ("полузащитник", "полузащитници"), "F": ("нападател", "нападатели"),
        None: ("играч", "играчи")}


def _roles_phrase(absent, U):
    """Кого губи отборът, с думи: "титулярния вратар, голмайстора на отбора и двама основни защитници". -> (фраза, facts)."""
    parts, facts = [], {}
    gk = [p for p in absent if U["pos"].get(p) == "G"]
    if len(gk) == 1:
        parts.append("титулярния вратар")
    elif gk:
        parts.append(f"{COUNT_M.get(len(gk), str(len(gk)))} титулярни вратари")
    if U["scorer"] in absent and U["scorer"] not in gk:
        parts.append("голмайстора на отбора")
    for code in ("D", "M", "F", None):
        k = len([p for p in absent if p not in gk and p != U["scorer"] and (U["pos"].get(p) if U["pos"].get(p) in ("D", "M", "F") else None) == code])
        if not k:
            continue
        one, many = ROLE[code]
        if k > 5:
            facts[f"role_{code or 'x'}"] = k
        parts.append(f"{COUNT_M.get(k, str(k))} основен {one}" if k == 1 else f"{COUNT_M.get(k, str(k))} основни {many}")
    return join_and(parts), facts


ROLE_EN = {"D": ("defender", "defenders"), "M": ("midfielder", "midfielders"), "F": ("forward", "forwards"), None: ("player", "players")}


def _roles_phrase_en(absent, U):
    """Английският вариант на _roles_phrase - същото броене: "the first-choice goalkeeper, the team's top scorer and two first-choice
    defenders"."""
    parts = []
    gk = [p for p in absent if U["pos"].get(p) == "G"]
    if len(gk) == 1:
        parts.append("the first-choice goalkeeper")
    elif gk:
        parts.append(f"{COUNT_EN.get(len(gk), str(len(gk)))} first-choice goalkeepers")
    if U["scorer"] in absent and U["scorer"] not in gk:
        parts.append("the team's top scorer")
    for code in ("D", "M", "F", None):
        k = len([p for p in absent if p not in gk and p != U["scorer"] and (U["pos"].get(p) if U["pos"].get(p) in ("D", "M", "F") else None) == code])
        if not k:
            continue
        one, many = ROLE_EN[code]
        parts.append(f"{COUNT_EN.get(k, str(k))} first-choice {one if k == 1 else many}")
    return join_and_en(parts)


def s_absent(D, T, tag, tid, prior, missing_ids, after_lineups, Te=None):
    """ZADACHA_TEKST_2. Отсъстващи титуляри (по минути в последните мачове) и колко е важен всеки (вратар/защитник/голмайстор, минути, голове).
    След съставите - не са в групата за мача; преди - в списъка на контузените/наказаните за мача (където API-то го дава)."""
    U = usual_by_minutes(D, tid, prior)
    if not U or not U["avg"]:
        return None
    absent = [p for p in U["avg"] if p in missing_ids]
    if not absent:
        return None
    absent.sort(key=lambda p: (U["pos"].get(p) != "G", p != U["scorer"], -U["avg"][p], D.player_name.get(p, "")))
    shown = [p for p in absent if D.player_name.get(p)][:NAMES_MAX]
    if not shown:
        return None
    roles, facts = _roles_phrase(absent, U)
    roles_en = _roles_phrase_en(absent, U)
    Te = Te or T
    n = U["n"]
    facts["usual_n"] = n
    with_goals = U["n_ev"] == n
    items, names, items_en, names_en = [], [], [], []
    for i, p in enumerate(shown):
        nm = D.player(p, tid)
        names.append(nm)
        ne = D.player_name.get(p)
        names_en.append(ne)
        facts[f"min_{i}"] = U["avg"][p]
        g = U["goals"].get(p, 0) if with_goals else 0
        gtxt = gtxt_en = ""
        if g:
            facts[f"goals_{i}"] = g
            gtxt = f", {noun(g, 'гол', 'гола')}"
            gtxt_en = f", {plural(g, 'goal', 'goals')}"
        items.append(f"{nm} (средно {U['avg'][p]} мин. на мач{gtxt})" if i == 0 else f"{nm} ({U['avg'][p]} мин.{gtxt})")
        items_en.append(f"{ne} (avg. {U['avg'][p]} min per match{gtxt_en})" if i == 0 else f"{ne} ({U['avg'][p]} min{gtxt_en})")
    rest = len(absent) - len(shown)
    if rest:
        facts["more"] = rest
        items.append(f"още {rest}")
        items_en.append(f"{rest} more")
    lst = join_and(items)
    lst_en = join_and_en(items_en)
    if after_lineups:
        text = f"В групата на {T} за мача няма {roles}: {lst} — по последните {n} мача"
        text_en = f"{Te}'s squad for this match is without {roles_en}: {lst_en}, based on the last {n} matches"
    else:
        text = f"Според списъка на отсъстващите {T} ще е без {roles}: {lst} — по последните {n} мача"
        text_en = f"According to the absence list, {Te} will be without {roles_en}: {lst_en}, based on the last {n} matches"
        others = len([p for p in missing_ids if p not in U["avg"]])
        if others:
            facts["others"] = others
            text += f"; в списъка има още {noun(others, 'играч', 'играчи')}"
            text_en += f"; the list includes {plural(others, 'more player', 'more players')}"
    gk = any(U["pos"].get(p) == "G" for p in absent)
    weight = sum(U["avg"][p] / 90.0 for p in absent)
    score = 40 + 15 * weight + (15 if gk else 0) + (10 if U["scorer"] in absent else 0)
    return {"kind": f"absent_{tag}", "score": score, "text": text + ".", "facts": facts, "names": names, "pids": shown, "tid": int(tid),
            "text_en": text_en + ".", "names_en": names_en}


MODEL_EXP_EN = "The model (experimental for this league)"


def s_model(H, A, pcts, exp, en=None):
    if not pcts or any(pcts.get(k) is None for k in ("home_win", "draw", "away_win")):
        return None
    He, Ae = en or (H, A)
    h, d, a = (int(round(pcts[k])) for k in ("home_win", "draw", "away_win"))
    facts = {"m_h": h, "m_d": d, "m_a": a}
    who = "Моделът (експериментално за тази лига)" if exp else "Моделът"
    text = f"{who} дава {h}% за победа на {H}, {d}% за равенство и {a}% за победа на {A}"
    text_en = f"{MODEL_EXP_EN if exp else 'The model'} gives: {He} win {h}%, draw {d}%, {Ae} win {a}%"
    if pcts.get("over25") is not None:
        o = int(round(pcts["over25"]))
        facts.update({"m_o": o, "line": 2.5})
        text += f"; за над 2,5 гола — {o}%"
        text_en += f"; over 2.5 goals {o}%"
    return {"kind": "model", "score": 45, "text": text + ".", "facts": facts, "text_en": text_en + "."}


def s_lineups(H, A, pcts, model_pre, absent_any, xi_changes, en=None):
    """След съставите - какво се промени: оценката на модела (преди -> сега), промени в титулярите; ако няма отсъстващи - казва го."""
    He, Ae = en or (H, A)
    parts, facts, parts_en = [], {}, []
    if model_pre and pcts and all(model_pre.get(k) is not None and pcts.get(k) is not None for k in ("home_win", "draw", "away_win")):
        before = {k: int(round(model_pre[k])) for k in ("home_win", "draw", "away_win")}
        now = {k: int(round(pcts[k])) for k in ("home_win", "draw", "away_win")}
        changed = [k for k in ("home_win", "draw", "away_win") if before[k] != now[k]]
        if changed:
            label = {"home_win": f"победа на {H}", "draw": "равенство", "away_win": f"победа на {A}"}
            tag = {"home_win": "h", "draw": "d", "away_win": "a"}
            label_en = {"home_win": f"{He} win", "draw": "draw", "away_win": f"{Ae} win"}
            for k in changed:
                facts.update({f"pre_{tag[k]}": before[k], f"now_{tag[k]}": now[k]})
            parts.append("моделът промени оценката си — " + ", ".join(f"{label[k]} от {before[k]}% на {now[k]}%" for k in changed))
            parts_en.append("the model changed its estimate: " + ", ".join(f"{label_en[k]} from {before[k]}% to {now[k]}%" for k in changed))
        else:
            parts.append("оценката на модела остана същата")
            parts_en.append("the model's estimate did not change")
    for tag, T, Te in (("h", H, He), ("a", A, Ae)):
        k = xi_changes.get(tag)
        if k is not None and k >= 3:
            facts[f"{tag}_xi"] = k
            parts.append(f"{T} прави {noun(k, 'промяна', 'промени')} в титулярите спрямо предишния си мач")
            parts_en.append(f"{Te} makes {plural(k, 'change', 'changes')} to its starting line-up from its previous match")
    clean = [T for tag, T in (("h", H), ("a", A)) if not absent_any.get(tag)]
    clean_en = [Te for tag, Te in (("h", He), ("a", Ae)) if not absent_any.get(tag)]
    if len(clean) == 2:
        parts.append(f"всички обичайни титуляри на {H} и {A} са в групата за мача")
        parts_en.append(f"all the usual starters of {He} and {Ae} are in the squad for the match")
    elif clean:
        parts.append(f"всички обичайни титуляри на {clean[0]} са в групата за мача")
        parts_en.append(f"all the usual starters of {clean_en[0]} are in the squad for the match")
    if not parts:
        return None
    return {"kind": "lineups", "score": 100, "text": "След обявяването на съставите " + "; ".join(parts) + ".", "facts": facts,
            "text_en": "After the line-ups were announced, " + "; ".join(parts_en) + "."}


def compose(cands):
    """Най-интересните първи, най-много MAX_SENTENCES; изречението за модела е винаги вътре (ако го има)."""
    cands = [c for c in cands if c]
    cands.sort(key=lambda c: -c["score"])
    model = [c for c in cands if c["kind"] == "model"]
    out = cands[:MAX_SENTENCES]
    if model and model[0] not in out:
        out = out[:MAX_SENTENCES - 1] + model
        out.sort(key=lambda c: -c["score"])
    return out


# ----------------------------------------------------------------------------------------------- един мач
def build_for_fixture(D, fid, pcts, names, exp, model_pre=None, cut_ts=None, names_en=None):
    """-> (sentences, has_lineups) или None, ако мачът го няма в данните.
    pcts: {код: % от снимката}; names: (дом., гост) за показване (кирилица, където има); exp: 1X2 не е проверено в лигата.
    cut_ts: само за проверката на минали мачове (данните са вече отрязани с build_features.truncate).
    names_en (ZADACHA_EZIK): (дом., гост) за "text_en" - оригиналните имена от API-то; None -> имената от данните (fx)."""
    if fid not in D.fx_by_id.index:
        return None
    f = D.fx_by_id.loc[fid]
    ts = int(f["ts"]) if cut_ts is None else int(cut_ts)
    hid, aid = int(f["home_id"]), int(f["away_id"])
    league, season = f["league"], int(f["season"])
    H, A = names
    ph, pa = _team_ctx(D, hid, ts), _team_ctx(D, aid, ts)
    team_name = {hid: H, aid: A}
    if names_en is None:
        names_en = (clean_name(str(f["home"])), clean_name(str(f["away"])))
    He, Ae = names_en
    en = (He, Ae)
    team_name_en = {hid: He, aid: Ae}

    def name_of_en(tid):
        if tid in team_name_en:
            return team_name_en[tid]
        row = D.fx[(D.fx["home_id"] == tid)].tail(1)
        return clean_name(str(row["home"].iloc[0])) if len(row) else str(tid)

    def name_of(tid):
        if tid in team_name:
            return team_name[tid]
        from bg_names import to_cyrillic
        row = D.fx[(D.fx["home_id"] == tid)].tail(1)
        nm = row["home"].iloc[0] if len(row) else str(tid)
        return to_cyrillic(nm, league)

    lu = D.raw["idx"]["lu"].get(fid) or {}
    lh, la = lu.get(hid), lu.get(aid)
    has_lineups = bool(lh and la and len(lh["starters"]) >= 9 and len(la["starters"]) >= 9)
    cands = [s_form(H, A, ph, pa, en), s_venue(H, A, ph, pa, en),
             s_table(D, league, season, ts, hid, aid, H, A, name_of, en, name_of_en),
             s_shots(H, A, ph, pa, en), s_rest(D, ts, hid, aid, H, A, ph, pa, en), s_referee(D, f, ts),
             s_model(H, A, pcts, exp, en)]
    absent_any, xi = {}, {}
    for tag, T, Te, tid, prior, lt in (("h", H, He, hid, ph, lh), ("a", A, Ae, aid, pa, la)):
        cands.append(s_coach(D, T, tid, prior, D.coach_at.get((int(fid), int(tid))) if has_lineups else None, Te))
        if has_lineups:
            sq = set(lt["squad"])
            U = usual_by_minutes(D, tid, prior)
            missing = {p for p in (U["avg"] if U else {}) if p not in sq}
            pl = [r for r in prior if r["has_lineup"]]
            if pl:
                xi[tag] = sum(1 for p in lt["starters"] if p not in set(pl[-1]["starters"]))
        else:
            missing = set((D.inj_by.get(fid) or {}).get(tid, {}))
        s = s_absent(D, T, tag, tid, prior, missing, has_lineups, Te)
        absent_any[tag] = bool(s)
        cands.append(s)
    if has_lineups:
        cands.append(s_lineups(H, A, pcts, model_pre, absent_any, xi, en))
    for c in cands:
        if c:
            c["facts"]["_names"] = [H, A] + c.pop("names", [])
            c["names_en"] = [He, Ae] + [x for x in c.get("names_en", []) if x]     # за проверката на числата в "text_en"
    return compose(cands), has_lineups


# ----------------------------------------------------------------------------------------------- снимката
def _snapshot_pcts(con, fids):
    out, meta = {}, {}
    for i in range(0, len(fids), 500):
        part = fids[i:i + 500]
        q = ("SELECT fixture_id, league, match_date, home_team, away_team, market_code, pick_pct FROM predictions_snapshot "
             f"WHERE fixture_id IN ({','.join('?' * len(part))}) AND market_code IN ('home_win','draw','away_win','over25')")
        for fid, lg, md, ht, at, code, pct in con.execute(q, part):
            out.setdefault(int(fid), {})[code] = pct
            meta[int(fid)] = (lg, md, ht, at)
    return out, meta


def team_name(name, league):
    """Отбор за текста: на кирилица по bg_names; българският отбор в евротурнир - също (ZADACHA_TEKST_2)."""
    from bg_names import to_cyrillic, BULGARIA_NAMES
    return to_cyrillic(name, "bulgaria" if league in CUPS and name in BULGARIA_NAMES else league)


def x12_ok(pcts, max_pct=95.0, tol=3.0):
    """Трите числа 1/X/2 стават за показване: всичките налични, под прага за артефакт, сбор 100±3 (като web/prognozi.build_market_sections)."""
    v = [pcts.get(k) for k in ("home_win", "draw", "away_win")] if pcts else [None]
    return all(p is not None and p < max_pct for p in v) and abs(sum(v) - 100.0) <= tol


def refresh(fixture_ids=None, db_path=DB_PATH, data=None):
    """Смята текста за мачовете (None = всички предстоящи в снимката) и го записва. Никога не хвърля. -> (записани, секунди)."""
    t0 = time.time()
    if not enabled():
        return 0, 0.0
    n = 0
    try:
        import prediction_policy as policy
        con = _connect(db_path)
        try:
            con.execute(DDL)
            con.commit()
            if fixture_ids is None:
                now_s = datetime.now().strftime("%Y-%m-%d %H:%M")
                fixture_ids = [r[0] for r in con.execute("SELECT DISTINCT fixture_id FROM predictions_snapshot WHERE match_date >= ?",
                                                         (now_s[:10],))]
            fids = sorted({int(f) for f in fixture_ids})
            if not fids:
                return 0, time.time() - t0
            pcts, meta = _snapshot_pcts(con, fids)
            pre = {int(r[0]): (json.loads(r[1]) if r[1] else None)
                   for r in con.execute(f"SELECT fixture_id, model_pre FROM match_text WHERE fixture_id IN ({','.join('?' * len(fids))})", fids)}
        finally:
            con.close()
        if not any(f in meta for f in fids):
            return 0, time.time() - t0               # нито един от мачовете не е в снимката - без тежкото зареждане
        D = data or Data()
        D.add_upcoming_injuries(db_path)
        stamp = datetime.utcnow().isoformat(timespec="seconds")
        rows = []
        for fid in fids:
            if fid not in meta:
                continue
            league, md, ht, at = meta[fid]
            try:
                p = pcts.get(fid, {})
                exp = not all(policy.is_publishable(league, c) for c in ("home_win", "draw", "away_win"))
                model_p = p if x12_ok(p) else {}
                res = build_for_fixture(D, fid, model_p, (team_name(ht, league), team_name(at, league)), exp, pre.get(fid),
                                        names_en=(clean_name(ht), clean_name(at)))
                if res is None:
                    continue
                sentences, has_lu = res
                bad = [w for s in sentences for w in BANNED if w in s["text"].lower()]
                if bad:
                    log(f"мач {fid}: забранена дума {bad} - текстът не е записан")
                    continue
                for s in sentences:                 # ZADACHA_EZIK: забранена дума в английския - само английското изречение отпада
                    bad_en = banned_en(s.get("text_en", ""), s.get("names_en", []))
                    if bad_en:
                        log(f"мач {fid}: забранена дума {bad_en} в text_en - английското изречение не е записано")
                        s.pop("text_en", None)
                cur = {k: p.get(k) for k in ("home_win", "draw", "away_win")} if model_p else None
                mp = pre.get(fid) if has_lu else cur
                rows.append((fid, league, md, stamp, int(has_lu), json.dumps(sentences, ensure_ascii=False),
                             json.dumps(mp) if mp else None))
            except Exception as e:
                log(f"мач {fid}: {type(e).__name__}: {e}")
        con = _connect(db_path)
        try:
            con.executemany("INSERT OR REPLACE INTO match_text (fixture_id, league, match_date, computed_at, has_lineups, sentences, model_pre) "
                            "VALUES (?,?,?,?,?,?,?)", rows)
            con.execute("DELETE FROM match_text WHERE match_date < ?", ((datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"),))
            con.commit()
        finally:
            con.close()
        n = len(rows)
    except Exception as e:
        log(f"refresh: грешка, текстът не е обновен: {type(e).__name__}: {e}")
    secs = time.time() - t0
    log(f"refresh: {n} мача, {secs:.1f} с")
    return n, secs
