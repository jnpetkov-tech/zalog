"""
web/model_admin.py — страница /admin/model: кой модел (версия на слоя) е на живо и защо, и ръчно превключване (ZADACHA_PAZACH_2,
06.10.2026, Дака).

Чете само файловете на пазача (features/layer_gate.py): layer_model/current.json, history.csv, last_gate.json. Бутоните викат
layer_gate.manual_rollback / manual_accept (същата логика като --rollback; под ключа на седмичното преобучение). Превключването е само
current.json - без рестарт: снимката (build_predictions_snapshot, на 30 мин) чете current.json при всеки цикъл.

Зад паролата като останалите админски страници (require_auth в match_predictor_app.py - /admin/model не е в PUBLIC_PATHS).
Пътищата се взимат от app.config (LAYER_MODEL_DIR, LAYER_GATE_LOG) - тестът на копие ги сочи към временна папка.
"""
from datetime import datetime
from flask import Blueprint, request, redirect, render_template, flash, current_app

from features import layer_gate as G

MODEL_NAMES = {"AB": "Прогнозата преди съставите (AB)", "ABC": "Прогнозата след съставите (ABC)"}
GROUP_NAMES = {"1x2": "1X2 (победа/равен)", "ou25": "Над/под 2.5 гола", "btts": "Двата вкарват", "team_total": "Голове по отбор"}


def _fmt_dt(iso):
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M") + " UTC"
    except Exception:
        return iso or "—"


def _sig(ci):
    """ci = (разлика, долна, горна): 'worse' значимо по-лош, 'better' значимо по-добър, 'noise'."""
    return "worse" if ci[1] > 0 else "better" if ci[2] < 0 else "noise"


def gate_rows(gate):
    """Последната проверка -> по модел списък редове {name, cur, cand, color, text}. Цветове: green / yellow / red."""
    out = []
    if not gate:
        return out
    n = gate.get("n_matches") or 0
    for fset, r in (gate.get("models") or {}).items():
        rows = []
        bad = r.get("bad") or []
        st = r.get("sanity") or {}
        rows.append({"name": "Здрав ли е моделът", "cur": "", "cand": "проблем" if bad else "наред",
                     "color": "red" if bad else "green",
                     "text": ("Кандидатът дава странни числа: " + "; ".join(bad)) if bad else
                             f"Зарежда се, числата са смислени (кандидатът мести прогнозата на ядрото между "
                             f"{st.get('ratio_min', 0):.2f} и {st.get('ratio_max', 0):.2f} пъти; рамка 0.5–2)."})
        c = r.get("cmp")
        if c:
            for key, label in (("brier", "Точност (Brier, по-малко = по-добре)"), ("logloss", "Точност (log-loss, по-малко = по-добре)")):
                k, cand, ci = c[key]
                s = _sig(ci)
                color = "red" if s == "worse" else "green" if s == "better" or ci[0] <= 0 else "yellow"
                text = {"worse": "Кандидатът греши ЗНАЧИМО повече от текущата - това е причина за отказ.",
                        "better": "Кандидатът греши значимо по-малко от текущата.",
                        "noise": ("Разликата е в рамките на шума - на практика еднакво точни" +
                                  (", кандидатът е малко по-добър." if ci[0] <= 0 else ", кандидатът е съвсем малко по-лош, но не значимо."))}[s]
                rows.append({"name": label, "cur": f"{k:.5f}", "cand": f"{cand:.5f}", "color": color,
                             "text": f"{text} (разлика {ci[0]:+.5f}, 95%: {ci[1]:+.5f} до {ci[2]:+.5f})"})
            ak, ac = c["cal"]
            for g, gname in GROUP_NAMES.items():
                if g not in ac:
                    continue
                d = c["dcal"][g]
                inside = 0.9 <= ac[g] <= 1.1
                if inside:
                    color, text = "green", "В рамката 0.9–1.1 - вероятностите отговарят на реалността."
                elif d[1] > 0:
                    color, text = "red", "Извън рамката и ЗНАЧИМО по-далеч от реалността от текущата - причина за отказ."
                else:
                    color = "yellow"
                    text = (f"Извън рамката 0.9–1.1 ({'по-плах' if ac[g] > 1 else 'по-смел'} от реалността), но не по-зле от текущата "
                            f"({ak[g]:.3f}) - не блокира.")
                rows.append({"name": f"Калибрация: {gname} (1.00 = идеално)", "cur": f"{ak[g]:.3f}", "cand": f"{ac[g]:.3f}",
                             "color": color, "text": text})
            for g, k in c["top"].items():
                share = k / n * 100 if n else 0
                color = "green" if share < 5 else "yellow" if share < 15 else "red"
                rows.append({"name": f"Сменена водеща прогноза: {g}", "cur": "", "cand": f"{k} от {n} ({share:.1f}%)", "color": color,
                             "text": f"В толкова мача кандидатът посочва друг най-вероятен изход от текущата. Не блокира - само за сведение"
                                     f"{' (много смени - заслужава поглед)' if color == 'red' else ''}."})
        else:
            for b in r.get("bad_cmp") or []:
                rows.append({"name": "Сравнение", "cur": "", "cand": "", "color": "red", "text": b})
        out.append({"fset": fset, "title": MODEL_NAMES.get(fset, fset), "rows": rows})
    return out


def headline(st):
    """Голямото изречение най-горе -> (вид, текст). вид: ok / warn / none."""
    cur, since, rej = st["current"], st["since"], st["rejected"]
    if not cur:
        return "warn", "ВНИМАНИЕ: няма версия на живо (layer_model/current.json липсва)."
    why = "—"
    when = _fmt_dt(since["at_utc"]) if since else "неизвестна дата"
    if since:
        note = since.get("note", "")
        if since["action"] == "ВЪРНАТА":
            why = f"върната ръчно ({note})"
        elif "ръчно от Дака" in note:
            why = "ти я прие ръчно въпреки отказа на пазача"
        elif note.startswith("пазач"):
            why = "пазачът я провери и всички проверки минаха"
        elif since["action"] == "НАЧАЛНА":
            why = "това е първата обучена версия"
        else:
            why = note
    if rej:
        return "warn", (f"ВНИМАНИЕ: последното преобучение ({rej['version']}, {_fmt_dt(rej['at_utc'])}) е отхвърлено — остава версия "
                        f"{cur}, причина: {rej['note']}")
    return "ok", f"На живо: версия {cur}, от {when}, приета защото {why}."


def register_model_admin_routes(app, ctx):
    bp = Blueprint("model_admin", __name__)

    def model_dir():
        return current_app.config.get("LAYER_MODEL_DIR", G.MODEL_DIR)

    def log_path():
        return current_app.config.get("LAYER_GATE_LOG", G.LOG_PATH)

    @bp.route("/admin/model")
    def model_page():
        st = G.status(model_dir())
        kind, text = headline(st)
        gate = st["gate"]
        return render_template("model_admin.html", active_page="model_admin", st=st, kind=kind, headline=text, gate=gate,
                               gate_at=_fmt_dt(gate["at_utc"]) if gate else None, models=gate_rows(gate), fmt_dt=_fmt_dt)

    def _do(fn, ok_text):
        try:
            new, old = fn()
            flash(("ok", ok_text.format(new=new, old=old) + " Сайтът ще мине на новата версия до 30 мин."))
        except G.Busy as e:
            flash(("err", f"Нищо не е сменено: {e}."))
        except Exception as e:
            flash(("err", f"Нищо не е сменено: {e}."))
        return redirect("/admin/model")

    @bp.route("/admin/model/rollback", methods=["POST"])
    def model_rollback():
        if request.form.get("confirm") != "1":
            flash(("err", "Нищо не е сменено: липсва потвърждение."))
            return redirect("/admin/model")
        return _do(lambda: G.manual_rollback(model_dir(), expected_current=request.form.get("current"), log_path=log_path()),
                   "Върната е версия {new} (беше {old}). Записано в историята като „ръчно от Дака“.")

    @bp.route("/admin/model/accept", methods=["POST"])
    def model_accept():
        if request.form.get("confirm") != "1":
            flash(("err", "Нищо не е сменено: липсва потвърждение."))
            return redirect("/admin/model")
        return _do(lambda: G.manual_accept(model_dir(), version=request.form.get("version"),
                                           expected_current=request.form.get("current"), log_path=log_path()),
                   "Приет е кандидатът {new} въпреки пазача (беше {old}). Записано в историята като „ръчно от Дака“.")

    app.register_blueprint(bp)
