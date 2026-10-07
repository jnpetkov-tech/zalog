"""validation/pazach3_test_20261007.py - тест на честната проверка в пазача (ZADACHA_MODELI, ЧАСТ 1, т.4, 07.10.2026).

Всичко върху КОПИЕ на layer_model/ във временна папка (живото layer_model/current.json не се пипа - проверява се в края). Таблицата с
признаци е сегашната (features/features_table.csv.gz, последен мач 04.10.2026) - без ново строене.
 0. окончателните AB.txt/ABC.txt от новия layer_train.train() = 20261005_d8f9a8b (обучена от стария код върху същата таблица) -
    т.е. окончателните модели не са променени, добавени са само проверочните;
 1. нормална седмица: обучение (окончателни + проверочни) срещу текуща 20261005_d8f9a8b -> ПРИЕТА, режим holdout;
 2. пауза: в 4-те проверочни седмици остават само 100 мача (останалите махнати от таблицата за пазача) -> ЧАКА РЕШЕНИЕ, current.json
    непроменен; status() го показва като чакащ; manual_accept() го приема;
 3. развален кандидат - обучен с разбъркани цели (голове, пермутирани между редовете) -> ОТХВЪРЛЕНА, current.json непроменен;
 4. кандидат без проверочни модели (стар формат) при малко невидени мачове -> ЧАКА РЕШЕНИЕ (не се приема автоматично).
Изход: validation/pazach3_test_20261007.txt (+ отчетите на пазача от копието: pazach3_test_20261007_<n>.md).
Употреба: nice -n 19 venv/bin/python3 -W ignore validation/pazach3_test_20261007.py
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
OUT = os.path.join(ROOT, "validation", "pazach3_test_20261007.txt")


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def trees(p):
    """Съдържанието на модела без заглавните редове с версия/параметри (сравнение на дърветата)."""
    s = open(p).read()
    return s[s.index("Tree=0"):s.index("end of trees")]


def main():
    live_before = md5(LIVE_CUR)
    lines = [f"Тест на честната проверка (features/layer_train.py + features/layer_gate.py) - живото current.json md5 преди: {live_before}", ""]
    ok_all = True

    def check(name, cond, extra=""):
        nonlocal ok_all
        ok_all &= bool(cond)
        lines.append(f"[{'OK ' if cond else 'ГРЕШКА'}] {name}" + (f" - {extra}" if extra else ""))
        print(lines[-1], flush=True)

    tmp = tempfile.mkdtemp(prefix="pazach3_")
    md, rep, lg = os.path.join(tmp, "lm"), os.path.join(tmp, "rep"), os.path.join(tmp, "gate.log")
    shutil.copytree(os.path.join(ROOT, "layer_model"), md)
    G.NOTIFY_LOG = os.path.join(tmp, "notify.log")
    G.NOTIFY_ENV = {}
    cur = lambda: G.current_version(md)
    reports = []

    def gate(tag):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = G.main(["--model-dir", md, "--report-dir", rep, "--log", lg])
        out = buf.getvalue()
        rp = [l.split("отчет: ", 1)[1].strip() for l in out.splitlines() if l.startswith("отчет: ")]
        if rp:
            dst = os.path.join(ROOT, "validation", f"pazach3_test_20261007_{tag}.md")
            shutil.copy(rp[0], dst)
            reports.append(os.path.relpath(dst, ROOT))
        lg_json = G.read_json(os.path.join(md, "last_gate.json"))
        return rc, out, lg_json

    # отделно Flask приложение със страницата /admin/model върху копието (не живия match-predictor-app)
    from flask import Flask
    from web.model_admin import register_model_admin_routes
    app = Flask("pazach3_test", template_folder=os.path.join(ROOT, "templates"))
    app.secret_key = "test"
    app.config.update(LAYER_MODEL_DIR=md, LAYER_GATE_LOG=lg, TESTING=True)
    register_model_admin_routes(app, {})
    client = app.test_client()

    def page():
        r = client.get("/admin/model")
        return r.status_code, re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.get_data(as_text=True))), r.get_data(as_text=True)

    t = L.load_table()
    long = L.to_long(t)
    hf = T.holdout_from(t)
    lines += [f"Таблица: {len(t)} мача, последен {t['date'].max()}; holdout_from = {hf}; мачове в 4-те седмици: "
              f"{int((t['date'] >= hf).sum())}", ""]

    # 0 + 1
    v1 = T.train(t, long, md)
    m1 = json.load(open(os.path.join(md, v1, "meta.json")))
    same = all(trees(os.path.join(md, v1, f"{m}.txt")) == trees(os.path.join(md, "20261005_d8f9a8b", f"{m}.txt")) for m in ("AB", "ABC"))
    check("0. окончателните AB/ABC = 20261005_d8f9a8b (същите дървета; добавени са само проверочните)", same)
    files = sorted(os.listdir(os.path.join(md, v1)))
    check("0b. папката има проверочните модели и holdout_from в meta.json",
          all(f in files for f in ("AB_holdout.txt", "ABC_holdout.txt", "AB_holdout_cur.txt", "ABC_holdout_cur.txt")) and m1["holdout_from"] == hf,
          f"{files}; holdout = {m1['holdout']}")
    rc, out, lj = gate("1_normalna")
    check("1. нормална седмица -> ПРИЕТА (режим holdout)", rc == 0 and cur() == v1 and lj["mode"] == "holdout",
          f"{lj['verdict']}, режим {lj['mode']}, {lj['n_matches']} мача; Brier AB разлика {lj['models']['AB']['cmp']['brier'][2]}; "
          f"срещу ядрото AB {lj['models']['AB']['vs_core']['brier'][2]}")

    code, txt, _ = page()
    check("1b. страницата: 200, „На живо: версия <нова>“, бележка за проверочните модели, без бутон „Приеми“",
          code == 200 and f"На живо: версия {v1}" in txt and "проверочните модели" in txt and "Приеми кандидата" not in txt,
          re.search(r"На живо:[^.]*\.", txt).group(0) if "На живо:" in txt else txt[:200])

    # 2 - пауза: само 100 мача в 4-те седмици
    v2 = T.train(t, long, md)
    orig = G.load_played

    def few():
        x = orig()
        h = x[x["date"] >= hf]
        drop = h.index[100:]
        return x.drop(index=drop).reset_index(drop=True)
    G.load_played = few
    before = md5(os.path.join(md, "current.json"))
    rc, out, lj = gate("2_pauza")
    G.load_played = orig
    st = G.status(md)
    check("2. пауза (100 мача в 4-те седмици) -> ЧАКА РЕШЕНИЕ, current.json непроменен",
          rc == 2 and lj["verdict"] == "ЧАКА РЕШЕНИЕ" and lj["mode"] == "fallback" and before == md5(os.path.join(md, "current.json")) and cur() == v1,
          lj["eval_note"][:300])
    check("2b. status(): кандидатът е чакащ (бутон „Приеми“ на /admin/model)", st["rejected"] and st["rejected"]["version"] == v2 and
          st["rejected"]["action"] == "ЧАКА", str({k: st["rejected"][k] for k in ("action", "version", "note")}) if st["rejected"] else "")
    code, txt, html = page()
    check("2d. страницата: „ЧАКА ТВОЕТО РЕШЕНИЕ“ и бутон „Приеми кандидата <чакащ>“ (без „въпреки това“)",
          code == 200 and "ЧАКА ТВОЕТО РЕШЕНИЕ" in txt and f"Приеми кандидата {v2}" in txt and f"Приеми кандидата {v2} въпреки това" not in txt,
          re.search(r"ЧАКА ТВОЕТО РЕШЕНИЕ[^.]*\.", txt).group(0) if "ЧАКА ТВОЕТО" in txt else txt[:200])
    open(os.path.join(ROOT, "validation", "pazach3_test_20261007_stranica_chaka.html"), "w", encoding="utf-8").write(html)
    with redirect_stdout(io.StringIO()):
        new, old = G.manual_accept(md, version=v2, expected_current=v1, log_path=lg, who="тест")
    check("2c. manual_accept() приема чакащия кандидат", cur() == v2 and old == v1, G.read_history(md)[-1]["note"][:200])

    # 3 - развален: разбъркани цели
    rng = np.random.default_rng(7)
    bad_long = long.copy()
    bad_long["y"] = rng.permutation(bad_long["y"].to_numpy())
    v3 = T.train(t, long, md, cand_long=bad_long)
    before = md5(os.path.join(md, "current.json"))
    rc, out, lj = gate("3_razbarkani")
    check("3. развален кандидат (разбъркани цели) -> ОТХВЪРЛЕНА, current.json непроменен",
          rc == 2 and lj["verdict"] == "ОТХВЪРЛЕНА" and before == md5(os.path.join(md, "current.json")) and cur() == v2,
          "; ".join(lj["reasons"])[:500])

    # 3б - развален, но с "разумни" числа: същият кандидат с разбъркани цели, корекцията на слоя наполовина (shrink 0.5 в meta.json) -
    # отношенията слой/ядро остават в рамката, (а) минава -> трябва да го хване честното сравнение (б)
    v3b = v3 + "_polovin"
    shutil.copytree(os.path.join(md, v3), os.path.join(md, v3b))
    mm = json.load(open(os.path.join(md, v3b, "meta.json")))
    mm["version"] = v3b
    for m in mm["models"]:
        mm["models"][m]["shrink"] = 0.5
    json.dump(mm, open(os.path.join(md, v3b, "meta.json"), "w"))
    json.dump({"version": v3b}, open(os.path.join(md, "candidate.json"), "w"))
    before = md5(os.path.join(md, "current.json"))
    rc, out, lj = gate("3b_razbarkani_polovin")
    sane = all(not lj["models"][m]["bad"] for m in lj["models"])
    check("3б. развален кандидат, който минава (а) -> ОТХВЪРЛЕНА от (б) (Brier/log-loss на 4-те невидени седмици)",
          rc == 2 and lj["verdict"] == "ОТХВЪРЛЕНА" and sane and any("значимо по-лош" in r for r in lj["reasons"]) and
          before == md5(os.path.join(md, "current.json")), "; ".join(lj["reasons"])[:500])

    code, txt, _ = page()
    check("3в. страницата след отказ: „ВНИМАНИЕ … отхвърлено“ и бутон „… въпреки това“", code == 200 and "ВНИМАНИЕ: последното преобучение" in txt
          and f"Приеми кандидата {v3b} въпреки това" in txt)

    # 4 - стар формат (без проверочни модели)
    v4 = "20261007_staformat"
    shutil.copytree(os.path.join(ROOT, "layer_model", "20261005_d8f9a8b"), os.path.join(md, v4))
    json.dump({"version": v4}, open(os.path.join(md, "candidate.json"), "w"))
    before = md5(os.path.join(md, "current.json"))
    rc, out, lj = gate("4_star_format")
    check("4. кандидат без проверочни модели, малко невидени мачове -> ЧАКА РЕШЕНИЕ (не автоматично)",
          rc == 2 and lj["verdict"] == "ЧАКА РЕШЕНИЕ" and before == md5(os.path.join(md, "current.json")), lj["eval_note"][:200])

    lines += ["", "Отчети на пазача от копието: " + ", ".join(reports), "",
              "history.csv на копието:", open(os.path.join(md, "history.csv"), encoding="utf-8").read(),
              "layer_gate_log на копието:", open(lg, encoding="utf-8").read(),
              "известия (само в файл):", open(G.NOTIFY_LOG, encoding="utf-8").read() if os.path.exists(G.NOTIFY_LOG) else "—"]
    live_after = md5(LIVE_CUR)
    check("живото layer_model/current.json непроменено", live_before == live_after, live_after)
    lines.insert(1, f"ОБЩО: {'ВСИЧКО OK' if ok_all else 'ИМА ГРЕШКИ'}")
    open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    shutil.rmtree(tmp)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
