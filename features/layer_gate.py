"""features/layer_gate.py - пазач на седмичното преобучение на слоя (ZADACHA_PAZACH, 06.10.2026, Дака).

features/layer_train.py вече НЕ сменя layer_model/current.json - обучава новата версия в нейната папка и пише layer_model/candidate.json.
Този скрипт (същият cron ред, веднага след обучението) сравнява кандидата с текущата версия и само ако мине всичко, прави
current.json = кандидата (атомарно, os.replace). Иначе current.json не се пипа -> "ОТХВЪРЛЕНА: <причина>" в layer_gate_log.txt и в
validation/pazach_<дата>.md (отчет се пише при всяко пускане).

ВЪРХУ КОИ МАЧОВЕ. Изиграните мачове от таблицата с признаци след trained_through и на двата модела (нито един не ги е виждал). Ако са под
MIN_UNSEEN (обичайно: при седмичното обучение кандидатът е видял всичко) - най-новите FALLBACK_WEEKS седмици от таблицата, с бележка, че
и двата модела са ги виждали (тогава проверката хваща счупен/странен модел, не пренастройване).

ПРОВЕРКИ (за всеки от двата модела, AB и ABC):
 а) файловете се зареждат (meta.json, AB.txt, ABC.txt, league_codes = layer_lib.LEAGUE_CODES); lam'/mu' и вероятностите - крайни числа;
    сборовете по пазар (1X2, над/под 2.5, двата вкарват, отборни голове 1.5) в 99-101%; отношенията слой/ядро в RATIO_RANGE (всеки мач);
 б) Brier (11 изхода) и log-loss (1X2, над/под, двата вкарват) - разлика кандидат − текуща по мач, 95% bootstrap интервал;
    отхвърля се, ако долната граница е > 0 (значимо по-лош);
 в) коефициент на калибрация по група (база - validation/sloy_kalibraciq_base_20261001.csv, като седмичния отчет) в 0.9-1.1,
    или поне |a − 1| не по-голямо от това на текущата;
 г) брой мачове със сменена водеща прогноза (1X2, над/под, двата вкарват) - записва се, не блокира.
Без текуща версия (първо пускане) - само (а).

ВЕРСИИ. layer_model/history.csv - коя версия кога е влязла (ПРИЕТА / ОТХВЪРЛЕНА / ВЪРНАТА / НАЧАЛНА). Пазят се последните KEEP папки
(по име = дата), плюс винаги текущата и тази за връщане. current.json никога не сочи липсваща папка (проверка преди запис).

Употреба:
  venv/bin/python3 features/layer_gate.py               # проверява candidate.json (crontab, след layer_train.py)
  venv/bin/python3 features/layer_gate.py --rollback    # current.json = предишната приета версия
  --model-dir DIR --report-dir DIR --log FILE           # само за тестове върху копие
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
FALLBACK_WEEKS = 8
RATIO_RANGE = (0.5, 2.0)       # същата рамка като layer_live.RATIO_RANGE
SUM_RANGE = (0.99, 1.01)
CAL_RANGE = (0.9, 1.1)
KEEP = 4
MODELS = ("AB", "ABC")
HIST_COLS = ["at_utc", "action", "version", "previous", "note"]
SETS_CURRENT = ("НАЧАЛНА", "ПРИЕТА", "ВЪРНАТА")      # действия, след които history.version е текущата
ACCEPTED = ("НАЧАЛНА", "ПРИЕТА")


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
    import lightgbm as lgb
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
        p = os.path.join(d, f"{m}.txt")
        # повреден файл кара LightGBM да убие целия процес (C++ terminate, не изключение) -> първо проба в отделен процес
        r = subprocess.run([sys.executable, "-c", "import sys, lightgbm; lightgbm.Booster(model_file=sys.argv[1])", p],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            tail = (r.stderr or r.stdout).strip().splitlines()
            raise RuntimeError(f"{m}.txt не се зарежда (код {r.returncode}): {tail[-1][:200] if tail else ''}")
        boosters[m] = lgb.Booster(model_file=p)
    return meta, boosters


def eval_set(metas):
    import pandas as pd
    from features import layer_lib as L
    t = L.load_table()
    t = t[t["hg"].notna() & t["ag"].notna()].reset_index(drop=True)
    cutoff = max(str(m["trained_through"]) for m in metas if m)
    unseen = t[t["date"] > cutoff]
    if len(unseen) >= MIN_UNSEEN:
        return unseen.reset_index(drop=True), (f"{len(unseen)} изиграни мача след {cutoff} - нито един от двата модела не ги е виждал при "
                                               f"обучение (out-of-sample).")
    start = t["d"].max() - pd.Timedelta(weeks=FALLBACK_WEEKS)
    s = t[t["d"] > start].reset_index(drop=True)
    return s, (f"**Бележка:** невидени и от двата модела са само {len(unseen)} мача (< {MIN_UNSEEN}) - сравнението е върху най-новите "
               f"{FALLBACK_WEEKS} седмици от таблицата с признаци ({len(s)} мача, {s['date'].min()} – {s['date'].max()}). И двата модела са "
               f"виждали (част от) тези мачове при обучение - проверката хваща счупен или странен модел, не пренастройване.")


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
        import pandas as pd
        from features import layer_lib as L
        t, note = eval_set([meta_c, meta_k])
        lines += ["## Мачове за проверката", "", note, ""]
        base = dict(pd.read_csv(CAL_BASE).set_index("code")["b_early"])
        for fset in MODELS:
            try:
                lam_c, mu_c, Pc = predict(t, meta_c, boost_c, fset)
            except Exception as e:
                reasons.append(f"{fset}: кандидатът не предсказва: {type(e).__name__}: {e}")
                continue
            bad, st = sanity(t, lam_c, mu_c, Pc)
            reasons += [f"{fset}: {b}" for b in bad]
            r = {"sanity": st}
            if meta_k is not None and not bad:
                _, _, Pk = predict(t, meta_k, boost_k, fset)
                bad2, cmp_ = compare(t, Pc, Pk, base)
                reasons += [f"{fset}: {b}" for b in bad2]
                r["cmp"] = cmp_
            res[fset] = r
        lines += report_tables(res, cur)
    verdict = "ПРИЕТА" if not reasons else "ОТХВЪРЛЕНА"
    if not reasons:
        try:
            write_current(model_dir, cand)
        except Exception as e:
            reasons.append(str(e))
            verdict = "ОТХВЪРЛЕНА"
    if verdict == "ПРИЕТА":
        append_history(model_dir, "ПРИЕТА", cand, cur, "пазач: всички проверки минаха")
        target = rollback_target(model_dir)
        gone = prune(model_dir, [cand, target])
        log(f"ПРИЕТА: {cand} (беше {cur}); връщане -> {target}" + (f"; изтрити стари папки: {', '.join(gone)}" if gone else ""), log_path)
        lines += ["## Решение", "", f"**ПРИЕТА** — `current.json` = `{cand}` (атомарно). Предишната `{cur}` остава в папката си; "
                  f"връщане с `venv/bin/python3 features/layer_gate.py --rollback` (-> `{target}`)." +
                  (f" Изтрити стари папки (пазят се последните {KEEP}): {', '.join(gone)}." if gone else ""), ""]
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
    os.makedirs(report_dir, exist_ok=True)
    out = os.path.join(report_dir, f"pazach_{datetime.utcnow().strftime('%Y%m%d')}.md")
    if os.path.exists(out):                       # второ пускане в същия ден - не презаписва първия отчет
        out = out[:-3] + f"_{datetime.utcnow().strftime('%H%M%S')}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("отчет:", out)
    return 0 if verdict == "ПРИЕТА" else 2


def report_tables(res, cur):
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
    print("На живо влиза при следващия цикъл на снимката/сянката (самостоятелни процеси) - без рестарт.")
    return 0


def main(argv):
    def opt(name, default):
        return argv[argv.index(name) + 1] if name in argv else default
    model_dir = opt("--model-dir", MODEL_DIR)
    log_path = opt("--log", LOG_PATH)
    if "--rollback" in argv:
        return run_rollback(model_dir, log_path)
    return run_gate(model_dir, opt("--report-dir", REPORT_DIR), log_path)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
