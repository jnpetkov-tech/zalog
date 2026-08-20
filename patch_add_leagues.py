# -*- coding: utf-8 -*-
import ast

with open("match_predictor_app.py", encoding="utf-8") as f:
    content = f.read()

old_leagues = '''    "portugal2": {"name": "Португалия - Сегунда Лига", "id": 95},
    "bulgaria2": {"name": "България - Втора лига", "id": 173},
}'''

new_leagues = '''    "portugal2": {"name": "Португалия - Сегунда Лига", "id": 95},
    "bulgaria2": {"name": "България - Втора лига", "id": 173},
    "england2": {"name": "Англия - Чемпиъншип", "id": 40},
    "germany2": {"name": "Германия - Втора Бундеслига", "id": 79},
}'''

n1 = content.count(old_leagues)
assert n1 == 1, f"anchor 1 (ALL_LEAGUES край) count: {n1}"
content = content.replace(old_leagues, new_leagues, 1)

old_flags = '''    "france2": "🇫🇷", "spain2": "🇪🇸", "italy2": "🇮🇹", "portugal2": "🇵🇹", "bulgaria2": "🇧🇬",
}'''

new_flags = '''    "france2": "🇫🇷", "spain2": "🇪🇸", "italy2": "🇮🇹", "portugal2": "🇵🇹", "bulgaria2": "🇧🇬",
    "england2": "🏴", "germany2": "🇩🇪",
}'''

n2 = content.count(old_flags)
assert n2 == 1, f"anchor 2 (LEAGUE_FLAGS край) count: {n2}"
content = content.replace(old_flags, new_flags, 1)

ast.parse(content)

with open("match_predictor_app.py", "w", encoding="utf-8") as f:
    f.write(content)

print("OK - Англия 2 (Чемпиъншип, id=40) и Германия 2 (id=79) добавени успешно")
