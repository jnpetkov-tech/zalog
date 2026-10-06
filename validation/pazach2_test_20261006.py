"""validation/pazach2_test_20261006.py - тест на /admin/model и известията (ZADACHA_PAZACH_2 т.3, 06.10.2026).

Всичко върху КОПИЕ на layer_model/ във временна папка и в ОТДЕЛНО Flask приложение (не живия match-predictor-app); известията -
NOTIFY_ENV={} (нищо не се праща навън) и notify_log във временната папка. Живото layer_model/current.json и history.csv - md5 преди/след.
 0. регресия: старият тест на пазача (validation/pazach_test_20261006.py) - изходът му в pazach2_test_20261006_regresiya.txt;
 1. приета версия: пазачът приема 20261005_d8f9a8b срещу 20261001_7d29039 -> last_gate.json, известие "приет нов", страницата 200 с
    "На живо: версия 20261005_d8f9a8b", таблица, без бутон "Приеми";
 2. отхвърлена: развален кандидат (x5) -> ОТХВЪРЛЕНА, известие "ОТХВЪРЛЕН кандидат", страницата: "ВНИМАНИЕ", червени редове, бутон "Приеми";
 3. POST без потвърждение -> нищо не се сменя; POST със стара "текуща" -> нищо не се сменя;
 4. "Приеми кандидата въпреки това" -> current.json = кандидата, history.csv "ПРИЕТА ... ръчно от Дака", известие;
 5. "Върни предишната версия" -> current.json = предишната, history.csv "ВЪРНАТА ... ръчно от Дака", известие;
 6. докато ключът /tmp/layer_train.lock (тук - копие) е зает -> "Нищо не е сменено";
 7. грешка в пазача -> код 3, известие "ГРЕШКА в пазача", current.json непроменен;
 8. layer_weekly_cron.sh: преобучението спира с код 1 -> известие; пазачът убит (abort, код 134) -> известие;
 9. notify.py без канал -> само ред в лога, без грешка; непознат канал / непълен telegram / непълен email -> ред в лога, без грешка.
Изход: validation/pazach2_test_20261006.txt. Употреба: venv/bin/python3 -W ignore validation/pazach2_test_20261006.py
"""
import fcntl
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "validation"))
from features import layer_gate as G  # noqa: E402
import notify as N  # noqa: E402
import pazach_test_20261006 as OLD  # noqa: E402

OUT = os.path.join(ROOT, "validation", "pazach2_test_20261006.txt")
LIVE = [os.path.join(ROOT, "layer_model", f) for f in ("current.json", "history.csv")]


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def text_of(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def main():
    live_before = [md5(p) for p in LIVE]
    lines = ["Тест на /admin/model и известията (ZADACHA_PAZACH_2) - на копие, отделно Flask приложение", ""]
    ok_all = True

    def check(name, cond, extra=""):
        nonlocal ok_all
        ok_all &= bool(cond)
        lines.append(f"[{'OK ' if cond else 'ГРЕШКА'}] {name}" + (f" - {extra}" if extra else ""))

    tmp = tempfile.mkdtemp(prefix="pazach2_")
    nlog = os.path.join(tmp, "notify_log.txt")
    G.NOTIFY_ENV, G.NOTIFY_LOG, G.LOCK_PATH = {}, nlog, os.path.join(tmp, "layer_train.lock")

    # 0 - регресия на стария тест (неговите известия - в нашия временен лог)
    OLD.OUT = os.path.join(ROOT, "validation", "pazach2_test_20261006_regresiya.txt")
    with redirect_stdout(io.StringIO()):
        rc = OLD.main()
    check("0. старият тест на пазача (9 проверки) минава и след промяната", rc == 0, open(OLD.OUT, encoding="utf-8").readline().strip())
    open(nlog, "w").close()

    md, rep, lg = os.path.join(tmp, "lm"), os.path.join(tmp, "rep"), os.path.join(tmp, "gate.log")
    shutil.copytree(os.path.join(ROOT, "layer_model"), md)
    for f in ("current.json", "candidate.json", "history.csv", "last_gate.json"):
        if os.path.exists(os.path.join(md, f)):
            os.remove(os.path.join(md, f))
    G.write_current(md, "20261001_7d29039")
    G.append_history(md, "НАЧАЛНА", "20261001_7d29039", "", "тест: първата обучена версия")
    cur = lambda: G.current_version(md)
    hist = lambda: G.read_history(md)
    put_cand = lambda v: json.dump({"version": v}, open(os.path.join(md, "candidate.json"), "w"))
    nlines = lambda: open(nlog, encoding="utf-8").read().splitlines()

    def gate():
        with redirect_stdout(io.StringIO()):
            return G.main(["--model-dir", md, "--report-dir", rep, "--log", lg, "--notify-log", nlog])

    # отделно Flask приложение с копието
    from flask import Flask
    from web.model_admin import register_model_admin_routes
    app = Flask("pazach2_test", template_folder=os.path.join(ROOT, "templates"))
    app.secret_key = "test"
    app.config.update(LAYER_MODEL_DIR=md, LAYER_GATE_LOG=lg, TESTING=True)
    register_model_admin_routes(app, {})
    c = app.test_client()
    page = lambda: c.get("/admin/model")

    # 1 - приета
    put_cand("20261005_d8f9a8b")
    rc = gate()
    r = page()
    t = text_of(r.get_data(as_text=True))
    lg_json = G.read_json(os.path.join(md, "last_gate.json"))
    check("1a. пазачът приема 20261005_d8f9a8b -> last_gate.json", rc == 0 and cur() == "20261005_d8f9a8b" and lg_json["verdict"] == "ПРИЕТА")
    check("1b. известие 'Модел: приет нов 20261005_d8f9a8b' в notify_log", any("Модел: приет нов 20261005_d8f9a8b" in l and "/admin/model" in l
                                                                             for l in nlines()), nlines()[-1][:220])
    check("1c. страницата 200, 'На живо: версия 20261005_d8f9a8b ... приета защото пазачът', таблица, без бутон 'Приеми'",
          r.status_code == 200 and "На живо: версия 20261005_d8f9a8b" in t and "пазачът я провери" in t and "Калибрация" in t
          and "Приеми кандидата" not in t and "Върни предишната версия (20261001_7d29039)" in t,
          re.search(r"На живо:[^.]*\.[^.]*\.", t).group(0) if "На живо:" in t else t[:200])
    shutil.copy(os.path.join(md, "last_gate.json"), os.path.join(ROOT, "validation", "pazach2_test_20261006_last_gate_prieta.json"))
    open(os.path.join(ROOT, "validation", "pazach2_test_20261006_stranica_prieta.html"), "w", encoding="utf-8").write(r.get_data(as_text=True))

    # 2 - отхвърлена
    OLD.break_model(os.path.join(md, "20261005_d8f9a8b"), os.path.join(md, "20261006_badx5"), "x5")
    before = md5(os.path.join(md, "current.json"))
    put_cand("20261006_badx5")
    rc = gate()
    r = page()
    html = r.get_data(as_text=True)
    t = text_of(html)
    check("2a. развален кандидат -> ОТХВЪРЛЕНА, current.json непроменен", rc == 2 and before == md5(os.path.join(md, "current.json")))
    check("2b. известие 'Модел: ОТХВЪРЛЕН кандидат 20261006_badx5, остава 20261005_d8f9a8b - <причина>'",
          any("Модел: ОТХВЪРЛЕН кандидат 20261006_badx5, остава 20261005_d8f9a8b - " in l for l in nlines()), nlines()[-1][:220])
    check("2c. страницата: 'ВНИМАНИЕ: последното преобучение ... отхвърлено — остава версия', червен ред, бутон 'Приеми'",
          r.status_code == 200 and "ВНИМАНИЕ: последното преобучение (20261006_badx5" in t and "остава версия 20261005_d8f9a8b" in t
          and 'class="red"' in html and "Приеми кандидата 20261006_badx5 въпреки това" in t, t[t.find("ВНИМАНИЕ"):][:250])
    shutil.copy(os.path.join(md, "last_gate.json"), os.path.join(ROOT, "validation", "pazach2_test_20261006_last_gate_otharlena.json"))
    open(os.path.join(ROOT, "validation", "pazach2_test_20261006_stranica_otharlena.html"), "w", encoding="utf-8").write(html)

    # 3 - без потвърждение / стара текуща
    n_hist = len(hist())
    c.post("/admin/model/accept", data={"version": "20261006_badx5", "current": "20261005_d8f9a8b"})
    c.post("/admin/model/accept", data={"confirm": "1", "version": "20261006_badx5", "current": "20261001_7d29039"})
    r = c.get("/admin/model")
    check("3. POST без потвърждение и POST със стара 'текуща' -> нищо не е сменено, съобщение на страницата",
          cur() == "20261005_d8f9a8b" and len(hist()) == n_hist and "Нищо не е сменено" in r.get_data(as_text=True))

    # 6 - зает ключ
    fd = os.open(G.LOCK_PATH, os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    c.post("/admin/model/rollback", data={"confirm": "1", "current": "20261005_d8f9a8b"})
    t = text_of(c.get("/admin/model").get_data(as_text=True))
    os.close(fd)
    check("6. докато тече преобучението (ключът е зает) -> 'Нищо не е сменено'", cur() == "20261005_d8f9a8b" and len(hist()) == n_hist
          and "тече седмичното преобучение" in t)

    # 4 - приеми въпреки отказа
    r = c.post("/admin/model/accept", data={"confirm": "1", "version": "20261006_badx5", "current": "20261005_d8f9a8b"}, follow_redirects=True)
    t = text_of(r.get_data(as_text=True))
    h = hist()[-1]
    check("4a. 'Приеми въпреки това' -> current.json = 20261006_badx5", cur() == "20261006_badx5")
    check("4b. history.csv: ПРИЕТА, ръчно от Дака", h["action"] == "ПРИЕТА" and h["version"] == "20261006_badx5" and "ръчно от Дака" in h["note"],
          h["note"][:160])
    check("4c. известие + на страницата 'до 30 мин' и 'приета защото ти я прие ръчно'",
          "Модел: приет нов 20261006_badx5" in nlines()[-1] and "до 30 мин" in t and "ти я прие ръчно" in t)

    # 5 - върни предишната
    r = c.post("/admin/model/rollback", data={"confirm": "1", "current": "20261006_badx5"}, follow_redirects=True)
    h = hist()[-1]
    check("5a. 'Върни предишната версия' -> current.json = 20261005_d8f9a8b", cur() == "20261005_d8f9a8b")
    check("5b. history.csv: ВЪРНАТА, ръчно от Дака + известие", h["action"] == "ВЪРНАТА" and "ръчно от Дака" in h["note"]
          and "Модел: ВЪРНАТА версия 20261005_d8f9a8b" in nlines()[-1], nlines()[-1][:200])

    # 7 - грешка в пазача
    put_cand("20261005_d8f9a8b")
    orig = G.eval_set
    G.eval_set = lambda metas: (_ for _ in ()).throw(ValueError("тестова грешка"))
    before = md5(os.path.join(md, "current.json"))
    rc = gate()
    G.eval_set = orig
    os.remove(os.path.join(md, "candidate.json"))
    check("7. грешка в пазача -> код 3, известие 'ГРЕШКА в пазача', current.json непроменен",
          rc == 3 and before == md5(os.path.join(md, "current.json")) and "Модел: ГРЕШКА в пазача - ValueError: тестова грешка" in nlines()[-1])

    # 8 - layer_weekly_cron.sh в мини-копие: фалшиви layer_train/layer_gate, истинските notify.py и python
    w = os.path.join(tmp, "wk")
    os.makedirs(os.path.join(w, "features"))
    os.makedirs(os.path.join(w, "venv", "bin"))
    os.symlink(os.path.join(ROOT, "venv", "bin", "python3"), os.path.join(w, "venv", "bin", "python3"))
    shutil.copy(os.path.join(ROOT, "layer_weekly_cron.sh"), w)
    shutil.copy(os.path.join(ROOT, "notify.py"), w)                     # без config.py до него -> без .env -> само в лога
    wlog = os.path.join(w, "notify_log.txt")
    open(os.path.join(w, "features", "layer_train.py"), "w").write("import sys; sys.exit(1)\n")
    open(os.path.join(w, "features", "layer_gate.py"), "w").write("print('не бива да стигне дотук')\n")
    rc1 = subprocess.run(["sh", os.path.join(w, "layer_weekly_cron.sh")]).returncode
    l1 = open(wlog, encoding="utf-8").read() if os.path.exists(wlog) else ""
    check("8a. преобучението спира с код 1 -> известие, пазачът не се пуска", rc1 == 1 and "преобучението на слоя (layer_train.py) спря с код 1" in l1
          and "не бива" not in open(os.path.join(w, "layer_gate_cron.log")).read(), l1.strip()[-200:])
    open(os.path.join(w, "features", "layer_train.py"), "w").write("print('ок')\n")
    open(os.path.join(w, "features", "layer_gate.py"), "w").write("import os; os.abort()\n")
    rc2 = subprocess.run(["sh", os.path.join(w, "layer_weekly_cron.sh")]).returncode
    l2 = open(wlog, encoding="utf-8").read().splitlines()[-1]
    check("8b. пазачът убит (код 134) -> известие", rc2 == 134 and "пазачът (layer_gate.py) спря неочаквано с код 134" in l2, l2[-160:])
    open(os.path.join(w, "features", "layer_gate.py"), "w").write("import sys; sys.exit(2)\n")
    n_before = len(open(wlog, encoding="utf-8").read().splitlines())
    rc3 = subprocess.run(["sh", os.path.join(w, "layer_weekly_cron.sh")]).returncode
    check("8c. отхвърлена (код 2) -> без допълнително известие от скрипта (пазачът сам известява)",
          rc3 == 2 and len(open(wlog, encoding="utf-8").read().splitlines()) == n_before)

    # 9 - notify.py без/с непълни данни - без грешка, само ред в лога
    t9 = os.path.join(tmp, "n9.txt")
    res = [N.send("Модел: тест 9", env=e, log_path=t9) for e in
           ({}, {"NOTIFY_CHANNEL": "sms"}, {"NOTIFY_CHANNEL": "telegram"}, {"NOTIFY_CHANNEL": "email", "SMTP_HOST": "x"})]
    l9 = open(t9, encoding="utf-8").read().splitlines()
    check("9. без канал / непознат / непълен telegram / непълен email -> 4 реда в лога, без грешка", len(l9) == 4, " || ".join(res))
    p = subprocess.run([os.path.join(ROOT, "venv", "bin", "python3"), "-c",
                        "import sys; sys.path.insert(0, sys.argv[1]); import notify as N; "
                        "print(N.send('Модел: пробно', env={}, log_path=sys.argv[2]))", ROOT, t9], capture_output=True, text=True)
    check("9b. пробно известие (същата функция като notify.py --test) работи", p.returncode == 0 and "само в лога" in p.stdout, p.stdout.strip())

    lines += ["", "history.csv на копието:", open(os.path.join(md, "history.csv"), encoding="utf-8").read(),
              "notify_log.txt на копието:", open(nlog, encoding="utf-8").read(),
              "notify_log.txt на мини-копието за layer_weekly_cron.sh:", open(wlog, encoding="utf-8").read()]
    live_after = [md5(p) for p in LIVE]
    check("живите layer_model/current.json и history.csv непроменени", live_before == live_after)
    lines.insert(1, f"ОБЩО: {'ВСИЧКО OK' if ok_all else 'ИМА ГРЕШКИ'}")
    open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    shutil.rmtree(tmp)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
