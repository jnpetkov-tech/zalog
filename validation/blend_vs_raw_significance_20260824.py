"""
blend_vs_raw_significance_20260824.py — довършва Задача 1 (нощна сесия
23-24.08.2026): audit-ът от blend_vs_raw_audit_20260824.md показа точкови
оценки (Brier/log-loss) по пазарна група и по лига, но не провери дали
разликите са статистически различими от шум - точно въпросът, който
решава дали Задача 2-3 изобщо може да продължи (виж стоп-условието в
задачата от Дака).

Пуска paired bootstrap (5000 семпъла, seed=42, resample по редове от
blend_vs_raw_backtest_20260824.csv) за разликата (raw - blended) в
Brier и log-loss: ОБЩО, по пазарна група (1x2/ou25 - точно двойката,
която /daily реално блендва), и по лига. 95% CI, който не пресича нулата,
= разликата НЕ Е шум за тази подгрупа.

Употреба: python3 validation/blend_vs_raw_significance_20260824.py
Пише validation/blend_vs_raw_significance_20260824.txt.
"""
import csv
import random

IN_PATH = "validation/blend_vs_raw_backtest_20260824.csv"
OUT_PATH = "validation/blend_vs_raw_significance_20260824.txt"
N_BOOT = 5000
SEED = 42


def diff_stats(rows, a, b, label, out):
    diffs = [r[a] - r[b] for r in rows]
    n = len(diffs)
    mean = sum(diffs) / n
    rng = random.Random(SEED)
    boots = []
    for _ in range(N_BOOT):
        sample = [rng.choice(diffs) for _ in range(n)]
        boots.append(sum(sample) / n)
    boots.sort()
    lo = boots[int(0.025 * N_BOOT)]
    hi = boots[int(0.975 * N_BOOT)]
    verdict = "ЗНАЧИМО (смес по-точна)" if lo > 0 else ("ЗНАЧИМО (модел по-точен)" if hi < 0 else "ШУМ (CI пресича нулата)")
    line = f"{label} n={n} mean(raw-blended)={mean:.4f} 95% CI=[{lo:.4f}, {hi:.4f}] -> {verdict}"
    print(line)
    out.write(line + "\n")


def main():
    rows = list(csv.DictReader(open(IN_PATH, encoding="utf-8")))
    for r in rows:
        for k in ("raw_brier", "blended_brier", "raw_logloss", "blended_logloss"):
            r[k] = float(r[k])

    with open(OUT_PATH, "w", encoding="utf-8") as out:
        out.write("Paired bootstrap (n_boot=5000, seed=42) върху blend_vs_raw_backtest_20260824.csv\n")
        out.write("Положителна разлика (raw-blended) = смесеното е по-точно (по-нисък Brier/log-loss).\n\n")

        out.write("=== BRIER ===\n")
        print("=== BRIER ===")
        diff_stats(rows, "raw_brier", "blended_brier", "ОБЩО (1x2+ou25)", out)
        for grp in ("1x2", "ou25"):
            sub = [r for r in rows if r["market_group"] == grp]
            diff_stats(sub, "raw_brier", "blended_brier", f"Група {grp}", out)
        out.write("\n")
        print()

        out.write("=== LOG-LOSS ===\n")
        print("=== LOG-LOSS ===")
        diff_stats(rows, "raw_logloss", "blended_logloss", "ОБЩО (1x2+ou25)", out)
        for grp in ("1x2", "ou25"):
            sub = [r for r in rows if r["market_group"] == grp]
            diff_stats(sub, "raw_logloss", "blended_logloss", f"Група {grp}", out)
        out.write("\n")
        print()

        out.write("=== BRIER, ПО ЛИГА ===\n")
        print("=== BRIER, ПО ЛИГА ===")
        leagues = sorted(set(r["league"] for r in rows))
        for lg in leagues:
            sub = [r for r in rows if r["league"] == lg]
            if len(sub) < 5:
                line = f"{lg}: n={len(sub)} - твърде малко за bootstrap"
                print(line)
                out.write(line + "\n")
                continue
            diff_stats(sub, "raw_brier", "blended_brier", f"Лига {lg}", out)

    print(f"\nЗаписано: {OUT_PATH}")


if __name__ == "__main__":
    main()
