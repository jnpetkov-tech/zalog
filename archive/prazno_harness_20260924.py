# Тестова среда: регистрира САМО /prognozi върху реалната база и шаблони,
# без да импортира match_predictor_app (импортът пише в model_cache).
import sys, re, ast, importlib.util
REPO = "/home/inkas/sportbg-predictor"
sys.path.insert(0, REPO)
import os; os.chdir(REPO)
from flask import Flask
import system_tracker as st, prediction_policy as policy, pick_selection as ps, evaluation
from bg_names import to_cyrillic
src = open(f"{REPO}/match_predictor_app.py", encoding="utf-8").read()
tree = ast.parse(src)
ns = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) in ("ALL_LEAGUES", "LEAGUE_FLAGS"):
        exec(compile(ast.Module([node], []), "x", "exec"), ns)
mod_path = sys.argv[1]
spec = importlib.util.spec_from_file_location("prognozi_under_test", mod_path)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
app = Flask("t", template_folder=f"{REPO}/templates", static_folder=f"{REPO}/static")
m.register_prognozi_routes(app, {"ALL_LEAGUES": ns["ALL_LEAGUES"], "LEAGUE_FLAGS": ns["LEAGUE_FLAGS"],
    "st": st, "evaluation": evaluation, "ps": ps, "policy": policy, "to_cyrillic": to_cyrillic,
    "_market_info_for_pick": None, "MARKET_COPY_CODES": None, "MARKET_COPY_NOTE": None})
app.run(port=int(sys.argv[2]))
