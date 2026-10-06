"""validation/pazach_test_20261006.py - тест на пазача на слоя (ZADACHA_PAZACH т.5, 06.10.2026).

Всичко върху КОПИЕ на layer_model/ във временна папка (живото layer_model/current.json не се пипа - проверява се в края).
 1. кандидат 20261005_d8f9a8b срещу текуща 20261001_7d29039 -> трябва ПРИЕТА;
 2. --rollback -> current.json = 20261001_7d29039;
 3. развален кандидат: към листата на първото дърво (AB и ABC) е добавено log(5) -> отношение слой/ядро x5 -> ОТХВЪРЛЕНА, current.json непроменен;
 4. развален кандидат: листата на първото дърво = nan -> ОТХВЪРЛЕНА, current.json непроменен;
 5. кандидат, сочещ липсваща папка -> ОТХВЪРЛЕНА; write_current към липсваща папка -> отказ; повреден файл на модела -> ОТХВЪРЛЕНА;
 6. второ обучение в същия ден не презаписва папка (layer_train: _2) - проверява се само логиката за името.
Изход: validation/pazach_test_20261006.txt. Употреба: venv/bin/python3 -W ignore validation/pazach_test_20261006.py
"""
import hashlib
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from features import layer_gate as G  # noqa: E402

LIVE_CUR = os.path.join(ROOT, "layer_model", "current.json")
OUT = os.path.join(ROOT, "validation", "pazach_test_20261006.txt")


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def break_model(src, dst, how):
    shutil.copytree(src, dst)
    meta = json.load(open(os.path.join(dst, "meta.json")))
    meta["version"] = os.path.basename(dst)
    json.dump(meta, open(os.path.join(dst, "meta.json"), "w"))
    for m in ("AB", "ABC"):
        p = os.path.join(dst, f"{m}.txt")
        s = open(p).read()
        i = s.index("Tree=0")
        j = s.index("leaf_value=", i)
        k = s.index("\n", j)
        vals = s[j + len("leaf_value="):k].split()
        if how == "x5":
            new = " ".join(repr(float(v) + math.log(5)) for v in vals)
        else:
            new = " ".join("nan" for _ in vals)
        s = s[:j] + "leaf_value=" + new + s[k:]
        s = re.sub(r"^tree_sizes=.*\n", "", s, count=1, flags=re.M)     # размерите в байтове вече не важат - LightGBM чете дърветата подред
        open(p, "w").write(s)


def gate(md, rep, lg):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = G.main(["--model-dir", md, "--report-dir", rep, "--log", lg])
    return rc, buf.getvalue()


def main():
    live_before = md5(LIVE_CUR)
    lines = [f"Тест на пазача (features/layer_gate.py) - живото current.json md5 преди: {live_before}", ""]
    ok_all = True

    def check(name, cond, extra=""):
        nonlocal ok_all
        ok_all &= bool(cond)
        lines.append(f"[{'OK ' if cond else 'ГРЕШКА'}] {name}" + (f" - {extra}" if extra else ""))

    tmp = tempfile.mkdtemp(prefix="pazach_")
    md, rep, lg = os.path.join(tmp, "lm"), os.path.join(tmp, "rep"), os.path.join(tmp, "gate.log")
    shutil.copytree(os.path.join(ROOT, "layer_model"), md)
    for f in ("current.json", "candidate.json", "history.csv"):
        if os.path.exists(os.path.join(md, f)):
            os.remove(os.path.join(md, f))
    G.write_current(md, "20261001_7d29039")
    G.append_history(md, "НАЧАЛНА", "20261001_7d29039", "", "тест")
    cur = lambda: G.current_version(md)
    put_cand = lambda v: json.dump({"version": v}, open(os.path.join(md, "candidate.json"), "w"))

    # 1
    put_cand("20261005_d8f9a8b")
    rc, out = gate(md, rep, lg)
    check("1. 20261005_d8f9a8b срещу 20261001_7d29039 -> ПРИЕТА", rc == 0 and cur() == "20261005_d8f9a8b", out.strip().splitlines()[0])
    # 2
    with redirect_stdout(io.StringIO()):
        rc = G.main(["--rollback", "--model-dir", md, "--log", lg])
    check("2. --rollback -> 20261001_7d29039", rc == 0 and cur() == "20261001_7d29039", f"current = {cur()}")
    # обратно на 20261005 за следващите (развалените се сравняват с нея)
    G.write_current(md, "20261005_d8f9a8b")
    G.append_history(md, "ПРИЕТА", "20261005_d8f9a8b", "20261001_7d29039", "тест: обратно след rollback")
    # 3, 4
    for n, how in ((3, "x5"), (4, "nan")):
        v = f"20261006_bad{how}"
        break_model(os.path.join(md, "20261005_d8f9a8b"), os.path.join(md, v), how)
        before = md5(os.path.join(md, "current.json"))
        put_cand(v)
        rc, out = gate(md, rep, lg)
        first = [l for l in out.splitlines() if "ОТХВЪРЛЕНА" in l or "ПРИЕТА" in l]
        check(f"{n}. развален кандидат ({how}) -> ОТХВЪРЛЕНА, current.json непроменен",
              rc == 2 and before == md5(os.path.join(md, "current.json")) and cur() == "20261005_d8f9a8b", (first[0] if first else out)[:400])
    # 5c - повреден файл (размерите в заглавката не съвпадат) - LightGBM би убил процеса; пазачът го пробва в подпроцес
    v = "20261006_povreden"
    shutil.copytree(os.path.join(md, "20261005_d8f9a8b"), os.path.join(md, v))
    p = os.path.join(md, v, "AB.txt")
    s = open(p).read()
    open(p, "w").write(s.replace("leaf_value=", "leaf_value=0.123456789 ", 1))
    put_cand(v)
    rc, out = gate(md, rep, lg)
    first = [l for l in out.splitlines() if "ОТХВЪРЛЕНА" in l]
    check("5c. повреден файл на модела -> ОТХВЪРЛЕНА (процесът оцелява)", rc == 2 and cur() == "20261005_d8f9a8b", (first[0] if first else out)[:300])
    # 5
    put_cand("20261007_nema")
    rc, out = gate(md, rep, lg)
    check("5a. кандидат към липсваща папка -> ОТХВЪРЛЕНА", rc == 2 and cur() == "20261005_d8f9a8b")
    try:
        G.write_current(md, "20261007_nema")
        check("5b. write_current към липсваща папка -> отказ", False)
    except RuntimeError as e:
        check("5b. write_current към липсваща папка -> отказ", cur() == "20261005_d8f9a8b", str(e))
    # 6 - логиката за име от layer_train (без обучение)
    src = open(os.path.join(ROOT, "features", "layer_train.py")).read()
    check("6. layer_train не пише current.json, пише candidate.json, не презаписва папка",
          '"current.json"' not in src and "candidate.json" in src and "os.makedirs(out)" in src and "while os.path.exists" in src)
    # пазене на 4 версии
    for v in ("20260901_a", "20260908_b", "20260915_c"):
        shutil.copytree(os.path.join(md, "20261005_d8f9a8b"), os.path.join(md, v))
    gone = G.prune(md, [cur(), G.rollback_target(md)])
    left = sorted(d for d in os.listdir(md) if re.fullmatch(r"\d{8}_[0-9A-Za-z_]+", d))
    check("7. пазят се последните 4 + текущата + за връщане", G.current_version(md) in left and G.rollback_target(md) in left and
          "20260901_a" not in left, f"изтрити {gone}; останали {left}")
    lines += ["", "history.csv на копието:", open(os.path.join(md, "history.csv"), encoding="utf-8").read(), "layer_gate_log на копието:",
              open(lg, encoding="utf-8").read()]
    live_after = md5(LIVE_CUR)
    check("живото layer_model/current.json непроменено", live_before == live_after, live_after)
    lines.insert(1, f"ОБЩО: {'ВСИЧКО OK' if ok_all else 'ИМА ГРЕШКИ'}")
    open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    shutil.rmtree(tmp)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
