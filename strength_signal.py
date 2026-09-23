"""strength_signal.py - ZADACHA_XG.md (23.09.2026): от какво наблюдение
моделът учи силата на отборите.

Целта, която моделът предсказва, си остава реалните голове. Променя се само
ковариатата, подавана на fl.fit_goals_model() през вече съществуващите
cov_home_col/cov_away_col (team_rating() -> beta * рейтинг), плюс по избор
по-малко тегло за мачове с червен картон (row_weight_col).

Видове сигнал (избират се по лига в SIGNAL_CONFIG, доказателство:
validation/xg_signal_20260923.md):
- "xg":    w * xG + (1 - w) * голове; където xG липсва -> голове.
- "shots": очаквани голове от ударите: a * удари в целта + b * удари извън
           целта (a, b - най-малки квадрати без свободен член, по лига,
           само върху подадената история); където ударите липсват -> голове.
- липсва в SIGNAL_CONFIG -> старото поведение, без промяна.
"""
import numpy as np

HOME_SIG, AWAY_SIG = "home_strength_sig", "away_strength_sig"
ROW_WEIGHT = "strength_row_weight"
RED_CARD_WEIGHT = 0.5

# лига -> {"kind": "xg"|"shots", "w": тегло на xG (само за "xg"), "red": bool}
# Попълнено след измерването (ЧАСТ Г) - само лигите, където помага.
SIGNAL_CONFIG = {}


def shots_conversion(df):
    """(a, b): голове ~ a * удари_в_целта + b * удари_извън_целта, двете
    страни заедно, без свободен член, отрязано >= 0."""
    rows = []
    for side in ("home", "away"):
        sub = df.dropna(subset=[f"{side}_goals", f"{side}_shots", f"{side}_shots_on_goal"])
        on = sub[f"{side}_shots_on_goal"].to_numpy(dtype=float)
        off = np.clip(sub[f"{side}_shots"].to_numpy(dtype=float) - on, 0, None)
        rows.append((on, off, sub[f"{side}_goals"].to_numpy(dtype=float)))
    on = np.concatenate([r[0] for r in rows])
    off = np.concatenate([r[1] for r in rows])
    g = np.concatenate([r[2] for r in rows])
    if len(g) < 50:
        return None
    coef, *_ = np.linalg.lstsq(np.column_stack([on, off]), g, rcond=None)
    return float(max(coef[0], 0.0)), float(max(coef[1], 0.0))


def add_signal(df, kind, w=None, conv=None):
    """Връща копие на df с колоните HOME_SIG/AWAY_SIG. conv - (a, b) за
    "shots"; None -> изчислява се от самия df."""
    out = df.copy()
    for side, col in (("home", HOME_SIG), ("away", AWAY_SIG)):
        goals = out[f"{side}_goals"].astype(float)
        if kind == "xg":
            xg = out[f"{side}_xg"].astype(float)
            sig = w * xg + (1 - w) * goals
        elif kind == "shots":
            a, b = conv if conv is not None else shots_conversion(df)
            on = out[f"{side}_shots_on_goal"].astype(float)
            off = (out[f"{side}_shots"].astype(float) - on).clip(lower=0)
            sig = a * on + b * off
        else:
            raise ValueError(kind)
        out[col] = sig.where(sig.notna(), goals)
    return out


def add_red_weight(df):
    """ROW_WEIGHT = RED_CARD_WEIGHT за мач с показан червен картон, иначе 1.0."""
    out = df.copy()
    red = (out["home_red"].fillna(0) > 0) | (out["away_red"].fillna(0) > 0)
    out[ROW_WEIGHT] = np.where(red, RED_CARD_WEIGHT, 1.0)
    return out


def prepare(df, cfg):
    """(df с нужните колони, kwargs за fl.fit_goals_model()). cfg=None ->
    (df, {}) - старото поведение."""
    if not cfg:
        return df, {}
    kwargs = {}
    if cfg.get("kind"):
        df = add_signal(df, cfg["kind"], cfg.get("w"))
        kwargs.update(cov_home_col=HOME_SIG, cov_away_col=AWAY_SIG)
    if cfg.get("red"):
        df = add_red_weight(df)
        kwargs["row_weight_col"] = ROW_WEIGHT
    return df, kwargs
