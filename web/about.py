"""
web/about.py — статичната обяснителна страница "Как работи това"
(искане на Дака, 01.09.2026: секцията излиза публична на медиен сайт,
за читатели, които не познават системата - трябва обяснение на прост
български, без технически жаргон, виж CLAUDE_HANDOFF.md).

Нищо динамично тук - чист рендер на шаблон, регистриран по същия модел
като web/daily.py и web/results.py, за да няма кръгов импорт с
match_predictor_app.py.
"""
from flask import Blueprint, render_template


def register_about_routes(app, ctx):
    about_bp = Blueprint("about", __name__)

    @about_bp.route("/how_it_works")
    def how_it_works():
        return render_template("how_it_works.html", active_page="how_it_works")

    app.register_blueprint(about_bp)
