"""
brier_vs_market.py - "Бием ли пазара" (т.1, разговор с Дака 24.08.2026).

Чист модул: работи върху вече заредени rows (списък от dict-ове, полетата на
predictions_log - league, fixture_id, match_date, market_code, pick_pct,
market_odds, status, logged_at), без БД връзка вътре в себе си - същия модел
като evaluation.py. Извиква се и от validation/vs_market_brier.py (еднократен
записан бектест), и от web/results.py (жив раздел "Резултати и ефективност") -
едно и също изчисление и на двете места, за да не се разминат числата.

Смята Brier score на нашата вероятност срещу обезвигованата пазарна, върху
едни и същи уредени изходи (status won/lost), разбито по (лига, пазар). Три
версии на "нашето" число:
  - raw    - чист модел
  - blend  - смесено 50/50 модел+пазар (_blend_with_market в match_predictor_app.py)
  - market - самият пазар като "наша" прогноза (контрола - разликата спрямо
    себе си е тривиално 0; проверка, че методологията не лъже сама себе си)

САМО за петте пазара с установено devig групиране в кода (1X2: home_win/
draw/away_win; O/У 2.5: over25/under25) - за други пазари (htft, corners,
dc_*, team totals) няма двойка/тройка коефициенти, от които да се извади
"пазарна вероятност" без vig, затова не влизат в тази проверка.

ВАЖНО (виж validation/ev_threshold_backtest.py и разговора 24.08.2026, т.3):
predictions_log.pick_pct за тези пет пазара е ЧИСТ МОДЕЛ за редове, логнати
ПРЕДИ commit 3d52ef5 (2026-08-23 19:43:52 UTC), и СМЕСЕН за редове, логнати
СЛЕД това (append-only лог, не ретроактивно). BLEND_WEIGHT е симетрично 0.5,
затова смесването е аритметично обратимо и за двата случая получаваме и
трите версии за всеки ред, без да презалитаме модела:
  - raw ред:     raw_p = pick_pct/100;  blend_p = W*market_p + (1-W)*raw_p
  - blended ред: blend_p = pick_pct/100; raw_p = (blend_p - W*market_p)/(1-W)

Правила срещу самозаблуда (Дака, 24.08.2026):
  - под MIN_N наблюдения -> статус "недостатъчно данни", точковите средни се
    показват за прозрачност, но НЕ се третират като резултат (без CI, без
    "доказано"/"кандидат").
  - всяка комбинация, преценена статистически по-добра от пазара, минава
    split-half проверка (хронологично, по match_date) - "доказано" само ако
    И ДВЕТЕ половини поотделно излизат "по-добро"; иначе "кандидат".
  - multiple_comparisons_summary() брои колко комбинации изобщо са тествани
    (n>=MIN_N) и колко биха изглеждали "значими" по чиста случайност при
    alpha=0.05 - за да не се чете точков "успех" изолирано от контекста му.
"""
import random

BLEND_CUTOFF = "2026-08-23 19:43:52"
BLEND_WEIGHT = 0.5

MARKET_GROUPS = {
    "1x2": ["home_win", "draw", "away_win"],
    "ou25": ["over25", "under25"],
}
ALL_CODES = [c for codes in MARKET_GROUPS.values() for c in codes]

MIN_N = 30
N_BOOT = 5000
SEED = 42


def devig(odds_list):
    implied = [1.0 / o for o in odds_list]
    total = sum(implied)
    return [i / total for i in implied]


def _clip01(p):
    return min(1.0, max(0.0, p))


def build_detail_rows(rows):
    """Групира по (fixture_id, пазарна група), изисква ПЪЛНА група
    (всички страни с коефициент - иначе devig е невъзможен), само уредени
    (won/lost). Връща детайл ред на кандидат-изход, с трите вероятности,
    трите Brier числа и basis (raw/blended)."""
    by_group = {}
    for r in rows:
        code = r.get("market_code")
        if code not in ALL_CODES or r.get("status") not in ("won", "lost") or not r.get("market_odds"):
            continue
        for group, codes in MARKET_GROUPS.items():
            if code in codes:
                by_group.setdefault((r["fixture_id"], group), {})[code] = r
                break

    detail = []
    for (fixture_id, group), by_code in by_group.items():
        codes = MARKET_GROUPS[group]
        if not all(c in by_code for c in codes):
            continue
        try:
            market_probs = devig([by_code[c]["market_odds"] for c in codes])
        except (ZeroDivisionError, TypeError):
            continue
        for code, market_p in zip(codes, market_probs):
            row = by_code[code]
            pick_pct = row.get("pick_pct")
            if pick_pct is None:
                continue
            logged_p = pick_pct / 100.0
            logged_at = row.get("logged_at") or ""
            basis = "blended" if logged_at >= BLEND_CUTOFF else "raw"
            if basis == "raw":
                raw_p = logged_p
                blend_p = BLEND_WEIGHT * market_p + (1 - BLEND_WEIGHT) * raw_p
            else:
                blend_p = logged_p
                raw_p = _clip01((blend_p - BLEND_WEIGHT * market_p) / (1 - BLEND_WEIGHT))
            outcome = 1 if row["status"] == "won" else 0
            detail.append({
                "league": row["league"], "fixture_id": fixture_id, "market_group": group,
                "market_code": code, "match_date": row.get("match_date"), "basis": basis,
                "outcome": outcome,
                "raw_p": raw_p, "blend_p": blend_p, "market_p": market_p,
                "raw_brier": (raw_p - outcome) ** 2,
                "blend_brier": (blend_p - outcome) ** 2,
                "market_brier": (market_p - outcome) ** 2,
            })
    return detail


def bootstrap_ci(diffs, n_boot=N_BOOT, seed=SEED):
    """Paired bootstrap на средната разлика (market_brier - нашия_brier) -
    положително = нашето число е по-точно (по-нисък Brier). None ако n<5
    (безсмислено да се бутстрапва)."""
    n = len(diffs)
    if n < 5:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        s = 0.0
        for _ in range(n):
            s += diffs[rng.randrange(n)]
        means.append(s / n)
    means.sort()
    lo = means[int(0.025 * n_boot)]
    hi = means[min(n_boot - 1, int(0.975 * n_boot))]
    return lo, hi


def _verdict(ci):
    if ci is None:
        return None
    lo, hi = ci
    if lo > 0:
        return "по-добро"
    if hi < 0:
        return "по-лошо"
    return "шум"


def split_half_check(items, which, n_boot=N_BOOT, seed=SEED):
    """Хронологично разполовяване по match_date - проверява дали "по-добро"
    находката се повтаря поотделно и в двете половини, не е артефакт на
    целия период/на един подпериод. И двете половини под MIN_N -> replicates
    остава False (не можем да твърдим нищо за половина без достатъчно данни,
    а недоказаното НЕ брои като потвърждение)."""
    ordered = sorted(items, key=lambda d: d["match_date"] or "")
    mid = len(ordered) // 2
    key = "raw_brier" if which == "raw" else "blend_brier"

    def half_result(half):
        if len(half) < MIN_N:
            return {"n": len(half), "ci": None, "verdict": None}
        diffs = [d["market_brier"] - d[key] for d in half]
        ci = bootstrap_ci(diffs, n_boot, seed)
        return {"n": len(half), "ci": ci, "verdict": _verdict(ci)}

    r1, r2 = half_result(ordered[:mid]), half_result(ordered[mid:])
    return {"first": r1, "second": r2, "replicates": r1["verdict"] == "по-добро" and r2["verdict"] == "по-добро"}


def summarize_by_league_market(detail, min_n=MIN_N, n_boot=N_BOOT, seed=SEED, do_split_half=True):
    combos = {}
    for d in detail:
        combos.setdefault((d["league"], d["market_code"]), []).append(d)

    out = []
    for (league, market_code), items in combos.items():
        n = len(items)
        raw_mean = sum(d["raw_brier"] for d in items) / n
        blend_mean = sum(d["blend_brier"] for d in items) / n
        market_mean = sum(d["market_brier"] for d in items) / n
        n_blended = sum(1 for d in items if d["basis"] == "blended")

        combo = {
            "league": league, "market_code": market_code, "n": n,
            "n_basis_raw": n - n_blended, "n_basis_blended": n_blended,
            "raw_brier": raw_mean, "blend_brier": blend_mean, "market_brier": market_mean,
            "diff_raw": market_mean - raw_mean, "diff_blend": market_mean - blend_mean,
            "diff_control": 0.0,
        }
        if n < min_n:
            combo.update(status="недостатъчно данни", ci_raw=None, ci_blend=None,
                         verdict_raw=None, verdict_blend=None, split_half=None)
            out.append(combo)
            continue

        ci_raw = bootstrap_ci([d["market_brier"] - d["raw_brier"] for d in items], n_boot, seed)
        ci_blend = bootstrap_ci([d["market_brier"] - d["blend_brier"] for d in items], n_boot, seed)
        v_raw, v_blend = _verdict(ci_raw), _verdict(ci_blend)

        split = None
        if do_split_half and (v_raw == "по-добро" or v_blend == "по-добро"):
            split = split_half_check(items, "raw" if v_raw == "по-добро" else "blend", n_boot, seed)

        if v_raw == "по-добро" or v_blend == "по-добро":
            status = "доказано" if (split and split["replicates"]) else "кандидат"
        elif v_raw == "по-лошо" and v_blend == "по-лошо":
            status = "по-зле от пазара"
        else:
            status = "шум"

        combo.update(status=status, ci_raw=ci_raw, ci_blend=ci_blend,
                     verdict_raw=v_raw, verdict_blend=v_blend, split_half=split)
        out.append(combo)

    out.sort(key=lambda c: (c["league"], c["market_code"]))
    return out


def multiple_comparisons_summary(combos, alpha=0.05):
    tested = [c for c in combos if c["n"] >= MIN_N]
    k = len(tested)
    flagged = sum(1 for c in tested if c["status"] in ("доказано", "кандидат"))
    return {"tested": k, "expected_false_positives": round(k * alpha, 1), "actual_flagged": flagged}
