"""validation/pazach4_test_20261007.py - тест на (д) "слоят срещу ядрото" в пазача (ZADACHA_MODELI_2, ЧАСТ 1, т.5, 07.10.2026).

Всичко върху КОПИЕ на layer_model/ (живото current.json - md5 преди/след), известията - само във файл, страницата - отделно Flask приложение.
 1. нормалната седмица от pazach3 -> ПРИЕТА; (д) за AB и ABC - не по-лош от ядрото; на страницата ред (д);
 2. разбъркани цели с половин корекция (pazach3, т.3б) -> ОТХВЪРЛЕНА, сред причините и (д);
 3. същата развалена рецепта и при кандидата, и при текущата (проверочните двойки еднакви -> (б) = 0) -> ОТХВЪРЛЕНА САМО по (д);
    известие "по-лош от ядрото ... на живо остава" + "и текущата е по-лоша от ядрото - препоръка: LAYER_LIVE=0"; страницата - червен ред (д);
 4. пауза (100 мача в 4-те седмици) -> ЧАКА РЕШЕНИЕ, както преди.
Изход: validation/pazach4_test_20261007.txt (+ отчетите на пазача pazach4_test_20261007_<n>.md).
Употреба: nice -n 19 venv/bin/python3 -W ignore validation/pazach4_test_20261007.py
"""
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
from contextlib import redirect_stdout

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from features import layer_gate as G  # noqa: E402
from features import layer_lib as L  # noqa: E402
from features import layer_train as T  # noqa: E402

LIVE_CUR = os.path.join(ROOT, "layer_model", "current.json")
OUT = os.path.join(ROOT, "validation", "pazach4_test_20261007.txt")


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def half_copy(md, src, dst, holdout_cur_from_self=False, cur_version=None):
    """Копие на версия с корекция на слоя наполовина (shrink 0.5); по желание _cur = собствените проверочни (еднаква рецепта)."""
    shutil.copytree(os.path.join(md, src), os.path.join(md, dst))
    mm = json.load(open(os.path.join(md, dst, "meta.json")))
    mm["version"] = dst
    for m in mm["models"]:
        mm["models"][m]["shrink"] = 0.5
    if holdout_cur_from_self:
        for m in ("AB", "ABC"):
            shutil.copy(os.path.join(md, dst, f"{m}_holdout.txt"), os.path.join(md, dst, f"{m}_holdout_cur.txt"))
        mm["holdout"]["current_version"] = cur_version
        mm["holdout"]["current_recipe"] = {m: dict(mm["models"][m]) for m in mm["models"]}
        mm["holdout"]["same_recipe"] = True
    json.dump(mm, open(os.path.join(md, dst, "meta.json"), "w"))


def main():
    live_before = md5(LIVE_CUR)
    lines = [f"Тест на (д) слоят срещу ядрото (features/layer_gate.py) - живото current.json md5 преди: {live_before}", ""]
    ok_all = True

    def check(name, cond, extra=""):
        nonlocal ok_all
        ok_all &= bool(cond)
        lines.append(f"[{'OK ' if cond else 'ГРЕШКА'}] {name}" + (f" - {extra}" if extra else ""))
        print(lines[-1], flush=True)

    tmp = tempfile.mkdtemp(prefix="pazach4_")
    md, rep, lg = os.path.join(tmp, "lm"), os.path.join(tmp, "rep"), os.path.join(tmp, "gate.log")
    shutil.copytree(os.path.join(ROOT, "layer_model"), md)
    G.NOTIFY_LOG = os.path.join(tmp, "notify.log")
    G.NOTIFY_ENV = {}
    cur = lambda: G.current_version(md)
    nlast = lambda: open(G.NOTIFY_LOG, encoding="utf-8").read().strip().splitlines()[-1]
    reports = []

    from flask import Flask
    from web.model_admin import register_model_admin_routes
    app = Flask("pazach4_test", template_folder=os.path.join(ROOT, "templates"))
    app.secret_key = "test"
    app.config.update(LAYER_MODEL_DIR=md, LAYER_GATE_LOG=lg, TESTING=True)
    register_model_admin_routes(app, {})
    client = app.test_client()

    def page():
        r = client.get("/admin/model")
        h = r.get_data(as_text=True)
        return r.status_code, re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h)), h

    def gate(tag):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = G.main(["--model-dir", md, "--report-dir", rep, "--log", lg])
        rp = [l.split("отчет: ", 1)[1].strip() for l in buf.getvalue().splitlines() if l.startswith("отчет: ")]
        if rp:
            dst = os.path.join(ROOT, "validation", f"pazach4_test_20261007_{tag}.md")
            shutil.copy(rp[0], dst)
            reports.append(os.path.relpath(dst, ROOT))
        return rc, G.read_json(os.path.join(md, "last_gate.json"))

    t = L.load_table()
    long = L.to_long(t)
    hf = T.holdout_from(t)

    # 1 - нормална седмица
    v1 = T.train(t, long, md)
    rc, lj = gate("1_normalna")
    vc = {m: lj["models"][m]["vs_core"] for m in ("AB", "ABC")}
    check("1. нормална седмица -> ПРИЕТА; (д) AB и ABC не по-лоши от ядрото", rc == 0 and cur() == v1 and lj["mode"] == "holdout" and
          not any(lj["models"][m]["bad_core"] for m in vc),
          "; ".join(f"{m} Brier {v['brier'][2][0]:+.5f} [{v['brier'][2][1]:+.5f}; {v['brier'][2][2]:+.5f}], log-loss 1X2 {v['logloss'][2][0]:+.5f} "
                    f"[{v['logloss'][2][1]:+.5f}; {v['logloss'][2][2]:+.5f}]" for m, v in vc.items()))
    code, txt, _ = page()
    check("1b. страницата: ред „Слоят срещу ядрото без слой“", code == 200 and "Слоят срещу ядрото без слой: Brier 11" in txt)

    # 2 - разбъркани цели, половин корекция (pazach3 т.3б) - текущата е нормална
    rng = np.random.default_rng(7)
    bad_long = long.copy()
    bad_long["y"] = rng.permutation(bad_long["y"].to_numpy())
    v2 = T.train(t, long, md, cand_long=bad_long)
    v2h = v2 + "_polovin"
    half_copy(md, v2, v2h)
    json.dump({"version": v2h}, open(os.path.join(md, "candidate.json"), "w"))
    rc, lj = gate("2_razbarkani_polovin")
    check("2. разбъркани цели, половин корекция -> ОТХВЪРЛЕНА, сред причините (д)", rc == 2 and cur() == v1 and
          any("(д)" in r for r in lj["reasons"]), "; ".join(r for r in lj["reasons"] if "(д)" in r)[:400])

    # 3 - една и съща развалена рецепта при текущата и кандидата -> (б) = 0, хваща само (д)
    vcur = v2 + "_polovin_tekushta"
    half_copy(md, v2, vcur)
    G.write_current(md, vcur)
    G.append_history(md, "ПРИЕТА", vcur, v1, "тест: развалена текуща (ръчно)")
    vcand = v2 + "_polovin_kandidat"
    half_copy(md, v2, vcand, holdout_cur_from_self=True, cur_version=vcur)
    json.dump({"version": vcand}, open(os.path.join(md, "candidate.json"), "w"))
    before = md5(os.path.join(md, "current.json"))
    rc, lj = gate("3_samo_d")
    other = [r for r in lj["reasons"] if "(д)" not in r]
    b_ab = lj["models"]["AB"]["cmp"]["brier"][2]
    check("3. еднаква развалена рецепта: (б) = 0, ОТХВЪРЛЕНА само по (д), current.json непроменен",
          rc == 2 and not other and any("(д)" in r for r in lj["reasons"]) and abs(b_ab[0]) < 1e-12 and before == md5(os.path.join(md, "current.json")),
          f"(б) AB {b_ab}; причини: " + "; ".join(lj["reasons"])[:400])
    n = nlast()
    check("3b. известие: „по-лош от ядрото на последните 4 седмици; на живо остава …“ + „препоръка: LAYER_LIVE=0, решава Дака“",
          "по-лош от ядрото на последните 4 седмици" in n and f"на живо остава {vcur}" in n and "LAYER_LIVE=0, решава Дака" in n, n[:400])
    code, txt, html = page()
    check("3c. страницата: „ЗНАЧИМО повече от самото ядро“ (червен ред (д))", code == 200 and "ЗНАЧИМО повече от самото ядро" in txt)
    open(os.path.join(ROOT, "validation", "pazach4_test_20261007_stranica_d.html"), "w", encoding="utf-8").write(html)

    # 4 - пауза
    G.write_current(md, v1)
    G.append_history(md, "ВЪРНАТА", v1, vcur, "тест: обратно на нормалната")
    v4 = T.train(t, long, md)
    orig = G.load_played

    def few():
        x = orig()
        h = x[x["date"] >= hf]
        return x.drop(index=h.index[100:]).reset_index(drop=True)
    G.load_played = few
    rc, lj = gate("4_pauza")
    G.load_played = orig
    check("4. пауза (100 мача) -> ЧАКА РЕШЕНИЕ", rc == 2 and lj["verdict"] == "ЧАКА РЕШЕНИЕ" and cur() == v1)

    lines += ["", "Отчети на пазача от копието: " + ", ".join(reports), "", "известия (само във файл):",
              open(G.NOTIFY_LOG, encoding="utf-8").read(), "history.csv на копието:", open(os.path.join(md, "history.csv"), encoding="utf-8").read()]
    live_after = md5(LIVE_CUR)
    check("живото layer_model/current.json непроменено", live_before == live_after, live_after)
    lines.insert(1, f"ОБЩО: {'ВСИЧКО OK' if ok_all else 'ИМА ГРЕШКИ'}")
    open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    shutil.rmtree(tmp)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
