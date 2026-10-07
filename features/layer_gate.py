"""features/layer_gate.py - пазач на седмичното преобучение на слоя (ZADACHA_PAZACH, 06.10.2026, Дака).

features/layer_train.py вече НЕ сменя layer_model/current.json - обучава новата версия в нейната папка и пише layer_model/candidate.json.
Този скрипт (същият cron ред, веднага след обучението) сравнява кандидата с текущата версия и само ако мине всичко, прави
current.json = кандидата (атомарно, os.replace). Иначе current.json не се пипа -> "ОТХВЪРЛЕНА: <причина>" в layer_gate_log.txt и в
validation/pazach_<дата>.md (отчет се пише при всяко пускане).

ВЪРХУ КОИ МАЧОВЕ (ZADACHA_MODELI, ЧАСТ 1, 07.10.2026 - честна проверка). layer_train.py обучава в папката на кандидата и проверочни
модели без последните 4 седмици (дата >= meta.holdout_from): {AB,ABC}_holdout.txt (рецептата на кандидата) и {AB,ABC}_holdout_cur.txt
(рецептата на текущата версия). Ред на избор:
 1. "holdout" - ако проверочните файлове ги има (и _cur е за СЕГАШНАТА текуща) и 4-те седмици имат >= MIN_HOLDOUT мача: (б)/(в) сравняват
    двете проверочни двойки върху 4-те седмици (нито една не ги е виждала); (а) и (г) - окончателните модели върху същите мачове.
    За сведение (не блокира): проверочният кандидат срещу ядрото без слой върху същите мачове.
 2. "unseen" - иначе, изиграни мачове след trained_through и на двата окончателни модела (>= MIN_UNSEEN) - също честно.
 3. "fallback" - иначе (международна пауза) най-новите FALLBACK_WEEKS седмици, които моделите са виждали: проверките вървят, но
    кандидатът НЕ се приема автоматично - решение "ЧАКА РЕШЕНИЕ" (history.csv: ЧАКА), Дака решава от /admin/model.

ПРОВЕРКИ (за всеки от двата модела, AB и ABC):
 а) файловете се зареждат (meta.json, AB.txt, ABC.txt, league_codes = layer_lib.LEAGUE_CODES); lam'/mu' и вероятностите - крайни числа;
    сборовете по пазар (1X2, над/под 2.5, двата вкарват, отборни голове 1.5) в 99-101%; отношенията слой/ядро в RATIO_RANGE (всеки мач);
 б) Brier (11 изхода) и log-loss (1X2, над/под, двата вкарват) - разлика кандидат − текуща по мач, 95% bootstrap интервал;
    отхвърля се, ако долната граница е > 0 (значимо по-лош);
 в) коефициент на калибрация по група (база - validation/sloy_kalibraciq_base_20261001.csv, като седмичния отчет) в 0.9-1.1,
    или поне |a − 1| не по-голямо от това на текущата;
 г) брой мачове със сменена водеща прогноза (1X2, над/под, двата вкарват) - записва се, не блокира.
Без текуща версия (първо пускане) - само (а).

ВЕРСИИ. layer_model/history.csv - коя версия кога е влязла (ПРИЕТА / ОТХВЪРЛЕНА / ЧАКА / ВЪРНАТА / НАЧАЛНА). Пазят се последните KEEP папки
(по име = дата), плюс винаги текущата и тази за връщане. current.json никога не сочи липсваща папка (проверка преди запис).

Употреба:
  venv/bin/python3 features/layer_gate.py               # проверява candidate.json (crontab, след layer_train.py)
  venv/bin/python3 features/layer_gate.py --rollback    # current.json = предишната приета версия
  --model-dir DIR --report-dir DIR --log FILE           # само за тестове върху копие
  --notify-log FILE                                     # само за тестове: известията - в този файл, нищо навън

ZADACHA_PAZACH_2 (06.10.2026): при всяко пускане пише и layer_model/last_gate.json (числата от проверката за страницата /admin/model) и
праща известие (notify.py) при решение и при грешка в пазача. Ръчните действия от /admin/model (manual_rollback, manual_accept) са тук,
до логиката на версиите, и вземат същия ключ /tmp/layer_train.lock като cron реда - не се застъпват с преобучението/проверката.
"""
import csv
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(ROOT, "layer_model")
REPORT_DIR = os.path.join(ROOT, "validation")
LOG_PATH = os.path.join(ROOT, "layer_gate_log.txt")
CAL_BASE = os.path.join(ROOT, "validation", "sloy_kalibraciq_base_20261001.csv")

MIN_UNSEEN = 200               # мачове, невидени от двата модела, нужни за сравнение върху тях
MIN_HOLDOUT = 150              # мачове в 4-те проверочни седмици, нужни за честното сравнение (иначе - пауза, чака решение)
FALLBACK_WEEKS = 8
RATIO_RANGE = (0.5, 2.0)       # същата рамка като layer_live.RATIO_RANGE
SUM_RANGE = (0.99, 1.01)
CAL_RANGE = (0.9, 1.1)
KEEP = 4
MODELS = ("AB", "ABC")
LOCK_PATH = "/tmp/layer_train.lock"   # същият ключ като cron реда (flock -n) на layer_train.py + layer_gate.py
LAST_GATE = "last_gate.json"
NOTIFY_LOG = None                     # тестове: файл вместо notify_log.txt
NOTIFY_ENV = None                     # тестове: {} -> нищо не се праща навън
HIST_COLS = ["at_utc", "action", "version", "previous", "note"]
SETS_CURRENT = ("НАЧАЛНА", "ПРИЕТА", "ВЪРНАТА")      # действия, след които history.version е текущата
ACCEPTED = ("НАЧАЛНА", "ПРИЕТА")
PENDING = ("ОТХВЪРЛЕНА", "ЧАКА")                    # последен ред с тези действия -> кандидатът може да бъде приет ръчно


def notify(text):
    try:
        sys.path.insert(0, ROOT)
        import notify as N
        return N.send(text, env=NOTIFY_ENV, log_path=NOTIFY_LOG)
    except Exception as e:                    # известието никога не спира пазача
        print("известие: грешка", e)


def now_iso():
    return datetime.utcnow().isoformat(timespec="seconds")


def log(msg, path=None):
    line = f"{now_iso()} {msg}"
    print(line)
    with open(path or LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ----------------------------------------------------------------------------------------------- версии / история (само stdlib)
def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def current_version(model_dir=MODEL_DIR):
    j = read_json(os.path.join(model_dir, "current.json"))
    return j["version"] if j else None


def version_ok(model_dir, version):
    d = os.path.join(model_dir, version or "")
    return bool(version) and all(os.path.isfile(os.path.join(d, f)) for f in ("meta.json",) + tuple(f"{m}.txt" for m in MODELS))


def write_current(model_dir, version):
    """Атомарно: временен файл + os.replace. Отказва, ако папката на версията липсва/непълна."""
    if not version_ok(model_dir, version):
        raise RuntimeError(f"папката на {version} липсва или е непълна - current.json НЕ е сменен")
    tmp = os.path.join(model_dir, ".current.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": version}, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, os.path.join(model_dir, "current.json"))


def read_history(model_dir=MODEL_DIR):
    p = os.path.join(model_dir, "history.csv")
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def append_history(model_dir, action, version, previous, note=""):
    p = os.path.join(model_dir, "history.csv")
    new = not os.path.exists(p)
    with open(p, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HIST_COLS)
        if new:
            w.writeheader()
        w.writerow({"at_utc": now_iso(), "action": action, "version": version, "previous": previous or "", "note": note})


def rollback_target(model_dir=MODEL_DIR):
    """Приетата версия точно преди текущата (по реда на приемане), чиято папка съществува."""
    cur = current_version(model_dir)
    acc = []
    for r in read_history(model_dir):
        if r["action"] in ACCEPTED and r["version"] not in acc:
            acc.append(r["version"])
    if cur in acc:
        acc = acc[:acc.index(cur)]
    for v in reversed(acc):
        if v != cur and version_ok(model_dir, v):
            return v
    return None


def live_versions_between(start, end, model_dir=MODEL_DIR):
    """Кои версии са били текущи (на живо) поне за малко в [start, end) (datetime, UTC) - за седмичния отчет на сянката."""
    rows = [r for r in read_history(model_dir) if r["action"] in SETS_CURRENT]
    out = []
    for i, r in enumerate(rows):
        a = datetime.fromisoformat(r["at_utc"])
        b = datetime.fromisoformat(rows[i + 1]["at_utc"]) if i + 1 < len(rows) else datetime.max
        if a < end and b > start:
            out.append((r["version"], max(a, start), min(b, end)))
    return out


def prune(model_dir, keep_extra):
    """Пази последните KEEP папки с версии + keep_extra (текущата, тази за връщане). Връща изтритите."""
    import re
    vers = sorted(d for d in os.listdir(model_dir) if re.fullmatch(r"\d{8}_[0-9A-Za-z_]+", d) and os.path.isdir(os.path.join(model_dir, d)))
    keep = set(vers[-KEEP:]) | {v for v in keep_extra if v}
    gone = [v for v in vers if v not in keep]
    for v in gone:
        shutil.rmtree(os.path.join(model_dir, v))
    return gone


# ----------------------------------------------------------------------------------------------- сметки
def load_version(model_dir, version):
    from features import layer_lib as L
    d = os.path.join(model_dir, version)
    meta = read_json(os.path.join(d, "meta.json"))
    if meta is None:
        raise RuntimeError("липсва meta.json")
    if meta.get("league_codes") != L.LEAGUE_CODES:
        raise RuntimeError("league_codes в meta.json се различават от layer_lib.LEAGUE_CODES")
    boosters = {}
    for m in MODELS:
        if m not in meta.get("models", {}):
            raise RuntimeError(f"meta.json няма модел {m}")
        boosters[m] = load_booster(os.path.join(d, f"{m}.txt"))
    return meta, boosters


def load_booster(p):
    import lightgbm as lgb
    # повреден файл кара LightGBM да убие целия процес (C++ terminate, не изключение) -> първо проба в отделен процес
    r = subprocess.run([sys.executable, "-c", "import sys, lightgbm; lightgbm.Booster(model_file=sys.argv[1])", p],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout).strip().splitlines()
        raise RuntimeError(f"{os.path.basename(p)} не се зарежда (код {r.returncode}): {tail[-1][:200] if tail else ''}")
    return lgb.Booster(model_file=p)


def load_holdout(model_dir, version, meta, cur):
    """Проверочните модели на кандидата -> ({m: booster}, {m: booster} на текущата рецепта или None, бележка). None, ако ги няма/не важат."""
    d = os.path.join(model_dir, version)
    h = meta.get("holdout") or {}
    if not meta.get("holdout_from") or not all(os.path.isfile(os.path.join(d, f"{m}_holdout.txt")) for m in MODELS):
        return None, None, "кандидатът няма проверочни модели (обучен преди ЧАСТ 1 или ръчно)"
    if cur and (h.get("current_version") != cur or not all(os.path.isfile(os.path.join(d, f"{m}_holdout_cur.txt")) for m in MODELS)):
        return None, None, (f"проверочните модели на текущата рецепта са за {h.get('current_version')}, а текущата сега е {cur} "
                            f"(или липсват)")
    hc = {m: load_booster(os.path.join(d, f"{m}_holdout.txt")) for m in MODELS}
    hk = {m: load_booster(os.path.join(d, f"{m}_holdout_cur.txt")) for m in MODELS} if cur else None
    return hc, hk, ""


def load_played():
    from features import layer_lib as L
    t = L.load_table()
    return t[t["hg"].notna() & t["ag"].notna()].reset_index(drop=True)


def eval_set(t, metas, meta_c=None, has_holdout=False):
    """-> (режим, мачове, бележка). Режим: holdout / unseen / fallback (виж най-горе)."""
    import pandas as pd
    hold = None
    if has_holdout:
        hf, tt = meta_c["holdout_from"], str(meta_c["trained_through"])
        hold = t[(t["date"] >= hf) & (t["date"] <= tt)].reset_index(drop=True)
        if len(hold) >= MIN_HOLDOUT:
            h = meta_c.get("holdout") or {}
            same = (" Рецептата на текущата = рецептата на кандидата -> двете проверочни двойки са еднакви (същите данни), разликата в (б)/(в) "
                    "е 0 по построение; проверката тогава хваща главно счупени данни/признаци (през (а)) - виж и сравнението с ядрото без "
                    "слой по-долу." if h.get("same_recipe") else "")
            return "holdout", hold, (f"Честна проверка: {len(hold)} изиграни мача от {hf} до {tt} (последните 4 седмици). (б)/(в) сравняват "
                                     f"ПРОВЕРОЧНИТЕ модели на кандидата и на рецептата на текущата, обучени без тези мачове "
                                     f"({h.get('n_train_matches', '?')} мача до {hf}) - нито един не ги е виждал. (а) и (г) - окончателните "
                                     f"модели върху същите мачове." + same)
    cutoff = max(str(m["trained_through"]) for m in metas if m)
    unseen = t[t["date"] > cutoff]
    if len(unseen) >= MIN_UNSEEN:
        return "unseen", unseen.reset_index(drop=True), (f"{len(unseen)} изиграни мача след {cutoff} - нито един от двата модела не ги е "
                                                         f"виждал при обучение (out-of-sample).")
    start = t["d"].max() - pd.Timedelta(weeks=FALLBACK_WEEKS)
    s = t[t["d"] > start].reset_index(drop=True)
    why = (f"в 4-те проверочни седмици има само {len(hold)} мача (< {MIN_HOLDOUT}, пауза)" if hold is not None else
           "кандидатът няма важащи проверочни модели")
    return "fallback", s, (f"**Бележка:** {why}, а невидени и от двата модела са само {len(unseen)} мача (< {MIN_UNSEEN}) - сравнението е "
                           f"върху най-новите {FALLBACK_WEEKS} седмици от таблицата с признаци ({len(s)} мача, {s['date'].min()} – "
                           f"{s['date'].max()}). И двата модела са виждали (част от) тези мачове при обучение - проверката хваща счупен или "
                           f"странен модел, не по-лош. **Затова кандидатът НЕ се приема автоматично - чака решение на Дака (/admin/model).**")


def predict(t, meta, boosters, fset):
    import numpy as np
    from features import layer_lib as L
    lam1, mu1 = L.predict_corrected(boosters[fset], fset, t, meta["models"][fset]["shrink"])
    with np.errstate(all="ignore"):
        P = L.probs(lam1, mu1, t["rho"])
    return np.asarray(lam1, float), np.asarray(mu1, float), P


def sanity(t, lam1, mu1, P):
    """Проверка (а) -> (списък с причини за отказ, речник с числа)."""
    import numpy as np
    from features import layer_lib as L
    bad = []
    p = P.to_numpy()
    fin = np.isfinite(lam1).all() and np.isfinite(mu1).all() and np.isfinite(p).all()
    if not fin:
        n = int((~np.isfinite(lam1) | ~np.isfinite(mu1) | ~np.isfinite(p).all(1)).sum())
        bad.append(f"нечислови стойности в {n} мача")
    rh, ra = lam1 / t["lam"].to_numpy(), mu1 / t["mu"].to_numpy()
    r = np.concatenate([rh, ra])
    with np.errstate(invalid="ignore"):
        out_r = int((~((r >= RATIO_RANGE[0]) & (r <= RATIO_RANGE[1]))).sum())
    if out_r:
        bad.append(f"отношение слой/ядро извън {RATIO_RANGE[0]}-{RATIO_RANGE[1]} в {out_r} стойности")
    sums = {"1x2": ["home_win", "draw", "away_win"], "ou25": ["over25", "under25"], "btts": ["btts_yes", "btts_no"],
            "home15": ["home_over15", "home_under15"], "away15": ["away_over15", "away_under15"]}
    smin, smax = {}, {}
    for g, cs in sums.items():
        s = P[cs].sum(axis=1).to_numpy()
        smin[g], smax[g] = float(np.nanmin(s)) if np.isfinite(s).any() else float("nan"), float(np.nanmax(s)) if np.isfinite(s).any() else float("nan")
        with np.errstate(invalid="ignore"):
            n_out = int((~((s >= SUM_RANGE[0]) & (s <= SUM_RANGE[1]))).sum())
        if n_out:
            bad.append(f"сбор {g} извън 99-101% в {n_out} мача")
    stats = {"ratio_min": float(np.nanmin(r)) if np.isfinite(r).any() else float("nan"),
             "ratio_max": float(np.nanmax(r)) if np.isfinite(r).any() else float("nan"), "sum_min": smin, "sum_max": smax}
    return bad, stats


def compare(t, Pc, Pk, base):
    """(б), (в), (г): кандидат Pc срещу текуща Pk -> (причини за отказ, числа)."""
    import numpy as np
    from features import layer_lib as L
    Y = L.y_matrix(t["hg"], t["ag"])
    bad = []
    bc, bk = L.brier_match(Pc, Y), L.brier_match(Pk, Y)
    lc = np.mean(list(L.logloss_match(Pc, Y).values()), axis=0)
    lk = np.mean(list(L.logloss_match(Pk, Y).values()), axis=0)
    dB, dL = L.boot_ci(bc - bk), L.boot_ci(lc - lk)
    if dB[1] > 0:
        bad.append(f"Brier значимо по-лош ({dB[0]:+.5f} [{dB[1]:+.5f}; {dB[2]:+.5f}])")
    if dL[1] > 0:
        bad.append(f"log-loss значимо по-лош ({dL[0]:+.5f} [{dL[1]:+.5f}; {dL[2]:+.5f}])")
    ac, ak = L.calib_coef(Pc, Y, base), L.calib_coef(Pk, Y, base)
    dcal = calib_dist_ci(Pc, Pk, Y, base)
    for g in L.GROUPS:
        if not (CAL_RANGE[0] <= ac[g] <= CAL_RANGE[1]) and dcal[g][1] > 0:
            bad.append(f"калибрация {g} {ac[g]:.3f} извън 0.9-1.1 и значимо по-далеч от 1 от текущата ({ak[g]:.3f}; "
                       f"|a−1| разлика {dcal[g][0]:+.3f} [{dcal[g][1]:+.3f}; {dcal[g][2]:+.3f}])")
    top = {}
    for g, cs in (("1X2", ["home_win", "draw", "away_win"]), ("над/под 2.5", ["over25", "under25"]), ("двата вкарват", ["btts_yes", "btts_no"])):
        top[g] = int((Pc[cs].to_numpy().argmax(1) != Pk[cs].to_numpy().argmax(1)).sum())
    return bad, {"brier": (float(bk.mean()), float(bc.mean()), dB), "logloss": (float(lk.mean()), float(lc.mean()), dL),
                 "cal": (ak, ac), "dcal": dcal, "top": top}


def calib_dist_ci(Pc, Pk, Y, base, n=2000, seed=42):
    """По група: |a_кандидат − 1| − |a_текуща − 1| и 95% bootstrap интервал (по мач, едни и същи извадки за двата модела).
    a = sum (p-b)(y-b) / sum (p-b)^2 (като layer_lib.calib_coef). Положително = кандидатът е по-далеч от 1."""
    import numpy as np
    from features import layer_lib as L
    rng = np.random.default_rng(seed)
    m = len(Y)
    W = np.stack([np.bincount(rng.integers(0, m, m), minlength=m) for _ in range(n)]).astype(float)   # тегла = брой повторения на мача
    out = {}
    for g in L.GROUPS:
        idx = [i for i, c in enumerate(L.CODES) if L.GROUP_OF[c] == g]
        b = np.array([base[L.CODES[i]] for i in idx])
        res = []
        for P in (Pc, Pk):
            d = P.to_numpy()[:, idx] - b
            num, den = (d * (Y[:, idx] - b)).sum(1), (d * d).sum(1)
            res.append((num.sum() / den.sum(), (W @ num) / (W @ den)))
        full = abs(res[0][0] - 1) - abs(res[1][0] - 1)
        bs = np.abs(res[0][1] - 1) - np.abs(res[1][1] - 1)
        out[g] = (float(full), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5)))
    return out


# ----------------------------------------------------------------------------------------------- главно
def vs_core(t, P):
    """За сведение: проверочният кандидат срещу ядрото без слой (Brier 11 изхода, log-loss) върху същите мачове."""
    import numpy as np
    from features import layer_lib as L
    Y = L.y_matrix(t["hg"], t["ag"])
    with np.errstate(all="ignore"):
        P0 = L.probs(t["lam"].to_numpy(), t["mu"].to_numpy(), t["rho"])
    b1, b0 = L.brier_match(P, Y), L.brier_match(P0, Y)
    l1 = np.mean(list(L.logloss_match(P, Y).values()), axis=0)
    l0 = np.mean(list(L.logloss_match(P0, Y).values()), axis=0)
    return {"brier": (float(b0.mean()), float(b1.mean()), L.boot_ci(b1 - b0)), "logloss": (float(l0.mean()), float(l1.mean()), L.boot_ci(l1 - l0))}


def run_gate(model_dir, report_dir, log_path):
    sys.path.insert(0, ROOT)
    cand_j = read_json(os.path.join(model_dir, "candidate.json"))
    if not cand_j:
        log("няма кандидат (layer_model/candidate.json) - нищо за проверка", log_path)
        return 0
    cand = cand_j["version"]
    cur = current_version(model_dir)
    lines = [f"# Пазач на слоя — {datetime.utcnow().strftime('%d.%m.%Y %H:%M')} UTC", "",
             f"Скрипт: `features/layer_gate.py`. Кандидат: **{cand}**; текуща (на живо): **{cur or '— няма —'}**.", ""]
    reasons = []
    res = {}
    meta_c = meta_k = None
    hold_c = hold_k = None
    eval_note, n_eval, mode = "", 0, None
    try:
        meta_c, boost_c = load_version(model_dir, cand)
    except Exception as e:
        reasons.append(f"кандидатът не се зарежда: {type(e).__name__}: {e}")
    if cur and not reasons:
        try:
            meta_k, boost_k = load_version(model_dir, cur)
        except Exception as e:
            log(f"внимание: текущата {cur} не се зарежда ({e}) - сравнение само по (а)", log_path)
            cur_note = f"Текущата версия не се зарежда ({type(e).__name__}: {e}) - направена е само проверка (а)."
            lines += [cur_note, ""]
            meta_k = None
    if not reasons:
        try:
            hold_c, hold_k, hnote = load_holdout(model_dir, cand, meta_c, cur if meta_k is not None else None)
        except Exception as e:
            reasons.append(f"проверочните модели на кандидата не се зареждат: {type(e).__name__}: {e}")
            hnote = ""
        if hnote:
            lines += [f"Проверочни модели: {hnote}.", ""]
    if not reasons:
        import pandas as pd
        t_all = load_played()
        mode, t, note = eval_set(t_all, [meta_c, meta_k], meta_c, hold_c is not None)
        eval_note, n_eval = note, len(t)
        lines += ["## Мачове за проверката", "", note, ""]
        base = dict(pd.read_csv(CAL_BASE).set_index("code")["b_early"])
        for fset in MODELS:
            try:
                lam_c, mu_c, Pc = predict(t, meta_c, boost_c, fset)
            except Exception as e:
                reasons.append(f"{fset}: кандидатът не предсказва: {type(e).__name__}: {e}")
                continue
            bad, st = sanity(t, lam_c, mu_c, Pc)
            r = {"sanity": st}
            Ph = None
            if mode == "holdout":
                try:
                    lam_h, mu_h, Ph = predict(t, meta_c, hold_c, fset)
                    bad_h, _ = sanity(t, lam_h, mu_h, Ph)
                    bad += [f"проверочен модел: {b}" for b in bad_h]
                except Exception as e:
                    bad.append(f"проверочният модел не предсказва: {type(e).__name__}: {e}")
            reasons += [f"{fset}: {b}" for b in bad]
            r["bad"] = bad
            if meta_k is not None and not bad:
                _, _, Pk = predict(t, meta_k, boost_k, fset)
                if mode == "holdout":
                    _, _, Pkh = predict(t, meta_k, hold_k, fset)
                    bad2, cmp_ = compare(t, Ph, Pkh, base)
                    cmp_["top"] = compare(t, Pc, Pk, base)[1]["top"]          # (г) - окончателните модели
                else:
                    bad2, cmp_ = compare(t, Pc, Pk, base)
                reasons += [f"{fset}: {b}" for b in bad2]
                r["cmp"] = cmp_
                r["bad_cmp"] = bad2
            if Ph is not None:
                r["vs_core"] = vs_core(t, Ph)
            res[fset] = r
        lines += report_tables(res, cur, mode)
    if reasons:
        verdict = "ОТХВЪРЛЕНА"
    elif mode == "fallback" and meta_k is not None:
        verdict = "ЧАКА РЕШЕНИЕ"
    else:
        verdict = "ПРИЕТА"
        try:
            write_current(model_dir, cand)
        except Exception as e:
            reasons.append(str(e))
            verdict = "ОТХВЪРЛЕНА"
    if verdict == "ПРИЕТА":
        append_history(model_dir, "ПРИЕТА", cand, cur, "пазач: всички проверки минаха" + (" (честна проверка върху 4 невидени седмици)"
                                                                                          if mode == "holdout" else ""))
        target = rollback_target(model_dir)
        gone = prune(model_dir, [cand, target])
        log(f"ПРИЕТА: {cand} (беше {cur}); връщане -> {target}" + (f"; изтрити стари папки: {', '.join(gone)}" if gone else ""), log_path)
        lines += ["## Решение", "", f"**ПРИЕТА** — `current.json` = `{cand}` (атомарно). Предишната `{cur}` остава в папката си; "
                  f"връщане с `venv/bin/python3 features/layer_gate.py --rollback` (-> `{target}`)." +
                  (f" Изтрити стари папки (пазят се последните {KEEP}): {', '.join(gone)}." if gone else ""), ""]
    elif verdict == "ЧАКА РЕШЕНИЕ":
        why = ("пауза - малко изиграни мачове за честна проверка; проверките върху виждани мачове минаха, но не доказват, че кандидатът не е "
               "по-лош - решава Дака от /admin/model")
        append_history(model_dir, "ЧАКА", cand, cur, why)
        target = rollback_target(model_dir)
        gone = prune(model_dir, [cur, target, cand])
        log(f"ЧАКА РЕШЕНИЕ: {cand}: {why} (current.json непроменен: {cur})", log_path)
        lines += ["## Решение", "", f"**ЧАКА РЕШЕНИЕ: {why}.**", "", f"`current.json` НЕ е пипан — на живо остава `{cur}`. Кандидатът може да "
                  f"бъде приет ръчно от `/admin/model` („Приеми кандидата“).", ""]
    else:
        why = "; ".join(reasons)
        append_history(model_dir, "ОТХВЪРЛЕНА", cand, cur, why)
        target = rollback_target(model_dir)
        gone = prune(model_dir, [cur, target, cand])
        log(f"ОТХВЪРЛЕНА: {cand}: {why} (current.json непроменен: {cur})", log_path)
        lines += ["## Решение", "", f"**ОТХВЪРЛЕНА: {why}**", "", f"`current.json` НЕ е пипан — на живо остава `{cur}`. Папката на кандидата "
                  f"остава за преглед.", ""]
    try:
        os.remove(os.path.join(model_dir, "candidate.json"))
    except FileNotFoundError:
        pass
    write_last_gate(model_dir, {"at_utc": now_iso(), "candidate": cand, "current_before": cur, "verdict": verdict, "reasons": reasons,
                                "eval_note": eval_note, "n_matches": n_eval, "mode": mode,
                                "holdout_from": (meta_c or {}).get("holdout_from"),
                                "same_recipe": ((meta_c or {}).get("holdout") or {}).get("same_recipe"), "models": res})
    if verdict == "ПРИЕТА":
        notify(f"Модел: приет нов {cand} (беше {cur or 'няма'}) - пазачът: всички проверки минаха. Сайтът минава на него до 30 мин.")
    elif verdict == "ЧАКА РЕШЕНИЕ":
        notify(f"Модел: кандидат {cand} ЧАКА твоето решение (пауза - малко мачове за честна проверка); на живо остава {cur}. Виж /admin/model.")
    else:
        notify(f"Модел: ОТХВЪРЛЕН кандидат {cand}, остава {cur or 'няма'} - {'; '.join(reasons)}")
    os.makedirs(report_dir, exist_ok=True)
    out = os.path.join(report_dir, f"pazach_{datetime.utcnow().strftime('%Y%m%d')}.md")
    if os.path.exists(out):                       # второ пускане в същия ден - не презаписва първия отчет
        out = out[:-3] + f"_{datetime.utcnow().strftime('%H%M%S')}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("отчет:", out)
    return 0 if verdict == "ПРИЕТА" else 2


def write_last_gate(model_dir, d):
    """layer_model/last_gate.json - числата от последната проверка (за /admin/model). Атомарно."""
    tmp = os.path.join(model_dir, ".last_gate.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1, default=float)
    os.replace(tmp, os.path.join(model_dir, LAST_GATE))


def report_tables(res, cur, mode=None):
    from features import layer_lib as L
    out = []
    for fset, r in res.items():
        st = r["sanity"]
        out += [f"## Модел {fset}", "",
                f"(а) отношение слой/ядро: {st['ratio_min']:.3f} – {st['ratio_max']:.3f} (рамка {RATIO_RANGE[0]}–{RATIO_RANGE[1]}); сборове по пазар: " +
                "; ".join(f"{g} {st['sum_min'][g] * 100:.2f}–{st['sum_max'][g] * 100:.2f}%" for g in st["sum_min"]) + ".", ""]
        if "cmp" in r:
            c = r["cmp"]
            sg = lambda d: "значимо по-лош" if d[1] > 0 else "значимо по-добър" if d[2] < 0 else "в рамките на шума"
            out += ["| мярка | текуща | кандидат | разлика (кандидат − текуща) | 95% | |", "|---|---|---|---|---|---|",
                    f"| (б) Brier, 11 изхода | {c['brier'][0]:.5f} | {c['brier'][1]:.5f} | {c['brier'][2][0]:+.5f} | "
                    f"[{c['brier'][2][1]:+.5f}; {c['brier'][2][2]:+.5f}] | {sg(c['brier'][2])} |",
                    f"| (б) log-loss | {c['logloss'][0]:.5f} | {c['logloss'][1]:.5f} | {c['logloss'][2][0]:+.5f} | "
                    f"[{c['logloss'][2][1]:+.5f}; {c['logloss'][2][2]:+.5f}] | {sg(c['logloss'][2])} |", "",
                    "(в) калибрация (рамка 0.9–1.1; текуща → кандидат; в скоби |a−1| кандидат − текуща, 95%): " +
                    "; ".join(f"{g} {c['cal'][0][g]:.3f} → {c['cal'][1][g]:.3f} ({c['dcal'][g][0]:+.3f} [{c['dcal'][g][1]:+.3f}; {c['dcal'][g][2]:+.3f}])"
                              for g in L.GROUPS) + ". Отказ само ако е извън рамката И значимо по-далеч от 1 от текущата.",
                    "", "(г) мачове със сменена водеща прогноза (не блокира): " + "; ".join(f"{g} {n}" for g, n in c["top"].items()) + ".", ""]
        elif not cur:
            out += ["Няма текуща версия — само проверка (а).", ""]
        if "vs_core" in r:
            v = r["vs_core"]
            out += [f"За сведение (не блокира): проверочният кандидат срещу ядрото без слой върху същите мачове — Brier {v['brier'][0]:.5f} → "
                    f"{v['brier'][1]:.5f} ({v['brier'][2][0]:+.5f} [{v['brier'][2][1]:+.5f}; {v['brier'][2][2]:+.5f}]); log-loss "
                    f"{v['logloss'][0]:.5f} → {v['logloss'][1]:.5f} ({v['logloss'][2][0]:+.5f} [{v['logloss'][2][1]:+.5f}; "
                    f"{v['logloss'][2][2]:+.5f}]).", ""]
    if mode == "holdout":
        out += ["(б)/(в) в таблиците: проверочният кандидат срещу проверочната текуща рецепта (без 4-те седмици); (а) — и окончателният, и "
                "проверочният кандидат; (г) — окончателният кандидат срещу окончателната текуща.", ""]
    return out


def run_rollback(model_dir, log_path):
    cur = current_version(model_dir)
    target = rollback_target(model_dir)
    if not target:
        log(f"--rollback: няма предишна приета версия с налична папка (текуща {cur}) - нищо не е сменено", log_path)
        return 1
    write_current(model_dir, target)
    append_history(model_dir, "ВЪРНАТА", target, cur, "ръчно: layer_gate.py --rollback")
    log(f"ВЪРНАТА: {target} (беше {cur})", log_path)
    notify(f"Модел: ВЪРНАТА версия {target} (беше {cur}) - ръчно с --rollback. Сайтът минава на нея до 30 мин.")
    print("На живо влиза при следващия цикъл на снимката/сянката (самостоятелни процеси) - без рестарт.")
    return 0


# ----------------------------------------------------------------------------------------------- ръчно от /admin/model (ZADACHA_PAZACH_2)
class Busy(Exception):
    pass


def _locked(fn):
    """Изпълнява fn() под /tmp/layer_train.lock (неблокиращо). Зает -> Busy (тече преобучението или проверката)."""
    import fcntl
    fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o664)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy("в момента тече седмичното преобучение/проверка - опитай пак след няколко минути")
        return fn()
    finally:
        os.close(fd)


def status(model_dir=MODEL_DIR):
    """Всичко за страницата /admin/model (само четене, само stdlib)."""
    hist = read_history(model_dir)
    cur = current_version(model_dir)
    since = None
    for r in hist:
        if r["action"] in SETS_CURRENT and r["version"] == cur:
            since = r                                  # последният ред, който е направил текущата текуща
    last = hist[-1] if hist else None
    rejected = None
    if last and last["action"] in PENDING and last["version"] != cur and last.get("previous", "") == (cur or ""):
        rejected = dict(last, folder_ok=version_ok(model_dir, last["version"]))
    gate = read_json(os.path.join(model_dir, LAST_GATE))
    return {"current": cur, "since": since, "last": last, "rejected": rejected, "rollback_to": rollback_target(model_dir),
            "history": list(reversed(hist)), "gate": gate}


def manual_rollback(model_dir=MODEL_DIR, expected_current=None, log_path=LOG_PATH, who="ръчно от Дака (бутон на /admin/model)"):
    def do():
        cur = current_version(model_dir)
        if expected_current is not None and cur != expected_current:
            raise RuntimeError(f"текущата версия вече е {cur}, не {expected_current} - презареди страницата")
        target = rollback_target(model_dir)
        if not target:
            raise RuntimeError("няма предишна приета версия с налична папка - нищо не е сменено")
        write_current(model_dir, target)
        append_history(model_dir, "ВЪРНАТА", target, cur, who)
        log(f"ВЪРНАТА: {target} (беше {cur}) - {who}", log_path)
        notify(f"Модел: ВЪРНАТА версия {target} (беше {cur}) - {who}. Сайтът минава на нея до 30 мин.")
        return target, cur
    return _locked(do)


def manual_accept(model_dir=MODEL_DIR, version=None, expected_current=None, log_path=LOG_PATH, who="ръчно от Дака (бутон на /admin/model)"):
    """Приема последния ОТХВЪРЛЕН или ЧАКАЩ кандидат. Само ако: последният ред в history.csv е неговото отхвърляне/чакане спрямо текущата,
    папката е пълна и моделите се зареждат (проба в отделен процес)."""
    def do():
        st = status(model_dir)
        cur, rej = st["current"], st["rejected"]
        if expected_current is not None and cur != expected_current:
            raise RuntimeError(f"текущата версия вече е {cur}, не {expected_current} - презареди страницата")
        if not rej or rej["version"] != version:
            raise RuntimeError(f"{version} не е последният отхвърлен/чакащ кандидат - нищо не е сменено")
        if not rej["folder_ok"]:
            raise RuntimeError(f"папката на {version} липсва или е непълна - нищо не е сменено")
        for m in MODELS:
            p = os.path.join(model_dir, version, f"{m}.txt")
            r = subprocess.run([sys.executable, "-c", "import sys, lightgbm; lightgbm.Booster(model_file=sys.argv[1])", p],
                               capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                raise RuntimeError(f"{m}.txt на {version} не се зарежда - не може да влезе на живо, нищо не е сменено")
        write_current(model_dir, version)
        how = "след като пазачът го остави да чака (пауза)" if rej["action"] == "ЧАКА" else "въпреки отказа на пазача"
        append_history(model_dir, "ПРИЕТА", version, cur, f"{who}, {how} ({rej['note'][:300]})")
        log(f"ПРИЕТА: {version} (беше {cur}) - {who}, {how}", log_path)
        notify(f"Модел: приет нов {version} (беше {cur}) - {who}, {how}. Сайтът минава на него до 30 мин.")
        return version, cur
    return _locked(do)


def main(argv):
    global NOTIFY_LOG
    def opt(name, default):
        return argv[argv.index(name) + 1] if name in argv else default
    model_dir = opt("--model-dir", MODEL_DIR)
    log_path = opt("--log", LOG_PATH)
    NOTIFY_LOG = opt("--notify-log", NOTIFY_LOG)
    if "--rollback" in argv:
        return run_rollback(model_dir, log_path)
    try:
        return run_gate(model_dir, opt("--report-dir", REPORT_DIR), log_path)
    except Exception as e:                    # грешка в пазача - не тихо: лог + известие; current.json остава какъвто е
        import traceback
        traceback.print_exc()
        log(f"ГРЕШКА в пазача: {type(e).__name__}: {e} (current.json непроменен)", log_path)
        notify(f"Модел: ГРЕШКА в пазача - {type(e).__name__}: {e}. На живо остава {current_version(model_dir)}; виж layer_gate_cron.log")
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
