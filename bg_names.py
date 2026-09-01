BULGARIA_NAMES = {
    "Levski Sofia": "Левски София",
    "CSKA Sofia": "ЦСКА София",
    "CSKA 1948": "ЦСКА 1948",
    "Ludogorets": "Лудогорец",
    "Botev Plovdiv": "Ботев Пловдив",
    "Botev Vratsa": "Ботев Враца",
    "Beroe": "Берое",
    "Slavia Sofia": "Славия София",
    "Lokomotiv Sofia": "Локомотив София",
    "Lokomotiv Plovdiv": "Локомотив Пловдив",
    "Cherno More Varna": "Черно море Варна",
    "Arda Kardzhali": "Арда Кърджали",
    "Spartak Varna": "Спартак Варна",
    "Septemvri Sofia": "Септември София",
    "Dunav Ruse": "Дунав Русе",
    "Hebar 1918": "Хебър 1918",
    "Pirin Blagoevgrad": "Пирин Благоевград",
    "Etar Veliko Tarnovo": "Етър Велико Търново",
    "Levski Krumovgrad": "Левски Крумовград",
    # Допълнени 01.09.2026, изписването потвърдено от Дака - НЕ
    # транскрибирано наново, не пипай без ново изрично потвърждение.
    # Конвенция: резервните отбори са с арабска "2", не с "II".
    "Dobrudzha": "Добруджа",
    "Marek": "Марек",
    "Montana": "Монтана",
    "Tsarsko Selo": "Царско село",
    "Vereya Stara Zagora": "Верея Стара Загора",
    "Vitosha Bistritsa": "Витоша Бистрица",
    "Bdin": "Бдин",
    "Belasitsa": "Беласица",
    "Botev Plovdiv II": "Ботев Пловдив 2",
    "CSKA 1948 Sofia II": "ЦСКА 1948 София 2",
    "CSKA Sofia II": "ЦСКА София 2",
    "Chernomorets 1919 Burgas": "Черноморец 1919 Бургас",
    "Chernomorets Balchik": "Черноморец Балчик",
    "FK Minyor Pernik": "Миньор Перник",
    "Fratria": "Фратрия",
    "Litex": "Литекс",
    "Lokomotiv G. Oryahovitsa": "Локомотив Г. Оряховица",
    "Ludogorets II": "Лудогорец 2",
    "Maritsa Plovdiv": "Марица Пловдив",
    "Nesebar": "Несебър",
    "Rilski Sportist": "Рилски спортист",
    "Sevlievo": "Севлиево",
    "Sozopol": "Созопол",
    "Spartak Pleven": "Спартак Плевен",
    "Sportist Svoge": "Спортист Своге",
    "Strumska Slava": "Струмска слава",
    "Vihren": "Вихрен",
    "Yantra 2019": "Янтра 2019",
}

_translit_map = [
    ("ch", "ч"), ("sh", "ш"), ("th", "т"), ("ph", "ф"), ("kh", "х"),
    ("a", "а"), ("b", "б"), ("c", "к"), ("d", "д"), ("e", "е"), ("f", "ф"),
    ("g", "г"), ("h", "х"), ("i", "и"), ("j", "дж"), ("k", "к"), ("l", "л"),
    ("m", "м"), ("n", "н"), ("o", "о"), ("p", "п"), ("q", "к"), ("r", "р"),
    ("s", "с"), ("t", "т"), ("u", "у"), ("v", "в"), ("w", "в"), ("x", "кс"),
    ("y", "и"), ("z", "з"),
]


def simple_transliterate(name):
    result = name.lower()
    for latin, cyr in _translit_map:
        result = result.replace(latin, cyr)
    return " ".join(w.capitalize() for w in result.split())


# Преглед на Дака (01.09.2026), т.4: /prognozi показваше "Hebar 1918 —
# Fratria" на латиница за bulgaria2, макар "Hebar 1918" вече да е в
# BULGARIA_NAMES ("Хебър 1918") - условието по-долу проверяваше буквално
# league == "bulgaria", никога "bulgaria2". BULGARIA_NAMES вече обслужва И
# двете деления (нямат конфликт по имена) - проверено срещу реалния ростер
# на bulgaria/bulgaria2 (get_models()), 32 отбора (6 bulgaria + 26
# bulgaria2) остават без превод и чакат потвърждение на Дака за точния
# изписан вариант, вместо налучкани транскрипции - виж CLAUDE_HANDOFF.md.
BULGARIA_LEAGUES = {"bulgaria", "bulgaria2"}


def to_cyrillic(name, league="bulgaria"):
    if league in BULGARIA_LEAGUES and name in BULGARIA_NAMES:
        return BULGARIA_NAMES[name]
    return name
