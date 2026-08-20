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


def to_cyrillic(name, league="bulgaria"):
    if league == "bulgaria" and name in BULGARIA_NAMES:
        return BULGARIA_NAMES[name]
    return name
