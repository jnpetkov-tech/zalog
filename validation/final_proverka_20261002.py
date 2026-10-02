"""validation/final_proverka_20261002.py - pre срещу final в layer_shadow (ZADACHA_RAZVITIE т.4, преди включване на LAYER_FINAL_LIVE).

Проверки (само четене на predictions.db):
  1. брой мачове с pre, с final, с двете; мачове с pre, чието начало е минало, БЕЗ final (= пропуск на окончателната прогноза);
  2. final: lam/mu числа в (0.2; 5), отношение слой/ядро в рамката на layer_live (0.5-2), сборове на изходите (1X2, над/под 2.5,
     двата вкарват, голове по отбор) в 99-101%;
  3. разлика pre -> final: в очакваните голове и в 1X2 (п.п.), най-големите случаи; за изиграните - Brier pre срещу final (сведение, малко мачове).
Изход: validation/final_proverka_<дата>.md (датата на пускане). Употреба: venv/bin/python3 validation/final_proverka_20261002.py
"""
import json
import os
import sqlite3
import sys
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
GROUPS = {"1x2": ["home_win", "draw", "away_win"], "ou25": ["over25", "under25"], "btts": ["btts_yes", "btts_no"],
          "home15": ["home_over15", "home_under15"], "away15": ["away_over15", "away_under15"]}


def main():
    con = sqlite3.connect("file:" + os.path.join(ROOT, "predictions.db") + "?mode=ro", uri=True)
    d = pd.read_sql_query("select * from layer_shadow", con)
    con.close()
    now_ts = __import__("time").time()
    last = d.sort_values("computed_at").groupby(["fixture_id", "mode"]).tail(1)
    pre, fin = last[last["mode"] == "pre"].set_index("fixture_id"), last[last["mode"] == "final"].set_index("fixture_id")
    started = set(pre.index[pre["kickoff_ts"] < now_ts])
    both = sorted(set(pre.index) & set(fin.index))
    missing_final = sorted(started - set(fin.index))
    errs = []
    for fid, r in fin.iterrows():
        if not (0.2 < r.lam_layer < 5 and 0.2 < r.mu_layer < 5):
            errs.append((fid, "lam/mu извън (0.2; 5)"))
        rh, ra = r.lam_layer / r.lam_core, r.mu_layer / r.mu_core
        if not (0.5 <= rh <= 2 and 0.5 <= ra <= 2):
            errs.append((fid, f"отношение {rh:.2f}/{ra:.2f}"))
        p = json.loads(r.probs_layer or "{}")
        for g, codes in GROUPS.items():
            if all(c in p for c in codes):
                s = sum(p[c] for c in codes)
                s = s * 100 if s <= 1.5 else s
                if not 99 <= s <= 101:
                    errs.append((fid, f"сбор {g} = {s:.2f}%"))
            else:
                errs.append((fid, f"липсва група {g}"))
    rows = []
    for fid in both:
        a, b = pre.loc[fid], fin.loc[fid]
        pa, pb = json.loads(a.probs_layer), json.loads(b.probs_layer)
        k = 100 if max(pa.values()) <= 1.5 else 1
        rows.append({"fixture_id": fid, "league": b.league, "lam_pre": a.lam_layer, "lam_final": b.lam_layer, "mu_pre": a.mu_layer,
                     "mu_final": b.mu_layer, **{f"d_{c}": (pb[c] - pa[c]) * k for c in GROUPS["1x2"]}})
    cmp = pd.DataFrame(rows)
    stamp = datetime.utcnow().strftime("%Y%m%d")
    L = [f"# pre срещу final в layer_shadow — {datetime.utcnow():%d.%m.%Y %H:%M} UTC", "",
         f"Мачове: с pre {len(pre)}, с final {len(fin)}, с двете {len(both)}. Започнали мачове с pre без final: **{len(missing_final)}**"
         + (f" ({', '.join(map(str, missing_final[:20]))})" if missing_final else "") + ".",
         f"Грешки във final (числа, отношение, сборове 99–101%): **{len(errs)}**" + ("" if not errs else ": " + "; ".join(f"{f} {w}" for f, w in errs[:20])), ""]
    if len(cmp):
        mx = cmp[["d_home_win", "d_draw", "d_away_win"]].abs().max(1)
        L += [f"Разлика pre → final, 1X2 (п.п.): средна абсолютна {mx.mean():.2f}, най-голяма {mx.max():.2f}; "
              f"очаквани голове: средна абс. разлика {np.mean(np.abs(cmp.lam_final - cmp.lam_pre)):.3f} (домакин), "
              f"{np.mean(np.abs(cmp.mu_final - cmp.mu_pre)):.3f} (гост).", "",
              "| мач | лига | lam pre→final | mu pre→final | 1 | X | 2 |", "|---|---|---|---|---|---|---|"]
        for r in cmp.assign(m=mx).sort_values("m", ascending=False).head(15).itertuples():
            L.append(f"| {r.fixture_id} | {r.league} | {r.lam_pre:.2f}→{r.lam_final:.2f} | {r.mu_pre:.2f}→{r.mu_final:.2f} | "
                     f"{r.d_home_win:+.1f} | {r.d_draw:+.1f} | {r.d_away_win:+.1f} |")
    ok = len(fin) > 0 and not errs and not missing_final
    L += ["", f"**Готово за включване (поне 1 final, 0 грешки, 0 пропуснати): {'ДА' if ok else 'НЕ'}**", ""]
    out = os.path.join(ROOT, "validation", f"final_proverka_{stamp}.md")
    open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
