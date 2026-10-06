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


# ------------------------------------------------------------------------------------------------------------------------------
# ZADACHA_TEKST_2 (Дака, 06.10.2026): имена на ХОРА (треньори, играчи) на българските отбори - на кирилица, в текста на мача.
# Ред: (1) PERSON_NAMES - точно име -> потвърдено изписване (попълва се след прегледа на Дака, виж validation/tekst2_imena_20261006.md);
# (2) BG_NAME_WORDS - дума от името, където обратната транслитерация е двусмислена (ъ/а: Petar -> Петър, но Bozhidar -> Божидар);
# (3) обратно на Закона за транслитерацията (ДВ бр. 19/2009): zh->ж, ts->ц, ch->ч, sh->ш, sht->щ, yu->ю, ya->я, y->й, -ia (край) -> -ия,
#     "yo" след съгласна -> ьо (Кръстьо), иначе йо (Йордан); a -> а (ъ не може да се различи - затова речникът в (2)).
#     Букви извън закона (c, j, q, w, x, диакритика) значат чуждо име - превежда се по най-близкото четене и се маркира "чуждо" за преглед.
PERSON_NAMES = {
}

BG_NAME_WORDS = {
    "petar": "Петър", "dimitar": "Димитър", "aleksandar": "Александър", "alexandar": "Александър", "krastyo": "Кръстьо",
    "krastev": "Кръстев", "krastanov": "Кръстанов", "parvanov": "Първанов", "valchev": "Вълчев", "valkov": "Вълков",
    "valkanov": "Вълканов", "galabov": "Гълъбов", "sabev": "Събев", "tsvetan": "Цветан", "atanas": "Атанас",
    "angel": "Ангел", "hristo": "Христо", "yasen": "Ясен", "zahari": "Захари",
}

_PRE = {"č": "ch", "ć": "ch", "š": "sh", "ž": "zh", "đ": "dzh", "ş": "sh", "ș": "sh", "ţ": "ts", "ț": "ts", "ö": "yo", "ü": "yu",
        "ø": "yo", "ä": "e", "æ": "e", "å": "o", "ß": "s", "ł": "l", "ı": "i", "ğ": "g", "ç": "s"}
_MULTI = [("sht", "щ"), ("dzh", "дж"), ("zh", "ж"), ("ts", "ц"), ("ch", "ч"), ("sh", "ш"), ("yu", "ю"), ("ya", "я"),
          ("cz", "ч"), ("ck", "к"), ("ph", "ф"), ("th", "т"), ("kh", "х")]
_ONE = {"a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х", "i": "и", "j": "й", "k": "к", "l": "л",
        "m": "м", "n": "н", "o": "о", "p": "п", "q": "к", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "w": "в", "x": "кс",
        "y": "й", "z": "з"}
_VOW = set("aeiouy")


def _ascii_word(w):
    import unicodedata
    w = "".join(_PRE.get(ch, ch) for ch in w.lower())
    return "".join(c for c in unicodedata.normalize("NFKD", w) if not unicodedata.combining(c))


def _translit_word(w):
    """Една дума (само букви) латиница -> кирилица, по обратното на закона."""
    s = _ascii_word(w)
    out, i = [], 0
    while i < len(s):
        if s.startswith("yo", i):
            out.append("ьо" if i > 0 and s[i - 1] not in _VOW and s[i - 1].isalpha() else "йо")
            i += 2
            continue
        if s.startswith("ja", i) or s.startswith("ju", i):          # чуждо j+гласна (Ljubomir, Jakub): я/ю
            out.append("я" if s[i + 1] == "a" else "ю")
            i += 2
            continue
        if s[i] == "y" and i + 1 < len(s) and s[i + 1] not in _VOW and (i == 0 or s[i - 1] not in _VOW):
            out.append("и")                                           # y между/пред съгласни (Yves, Lyndon) - не е й
            i += 1
            continue
        if s.endswith("ia") and i == len(s) - 2:
            out.append("ия")
            break
        for lat, cyr in _MULTI:
            if s.startswith(lat, i):
                out.append(cyr)
                i += len(lat)
                break
        else:
            out.append(_ONE.get(s[i], s[i]))
            i += 1
    return "".join(out)


def _is_foreign_word(w):
    w = w.lower()
    if any(ord(ch) > 127 for ch in w) or any(d in w for d in ("ph", "th", "ck")):
        return True
    return any(ch in "cjqwx" for ch in w.replace("ch", ""))


def person_to_cyrillic(name):
    """Име на човек (латиница от API-то) -> (кирилица, източник), източник: "речник" | "закон" | "чуждо".
    "D. Kajzer" -> "Д. Кайзер"; "Petar Zanev" -> "Петър Занев"; празно/вече на кирилица -> без промяна."""
    import re
    if not isinstance(name, str) or not name.strip():
        return name, "речник"
    name = name.strip()
    if name in PERSON_NAMES:
        return PERSON_NAMES[name], "речник"
    if not re.search(r"[A-Za-zÀ-ɏ]", name):
        return name, "речник"
    src = "закон"
    parts = re.split(r"([A-Za-zÀ-ɏ]+)", name)
    out = []
    for p in parts:
        if not p or not re.match(r"[A-Za-zÀ-ɏ]", p):
            out.append(p)
            continue
        key = _ascii_word(p)
        if key in BG_NAME_WORDS:
            out.append(BG_NAME_WORDS[key])
            continue
        if _is_foreign_word(p):
            src = "чуждо"
        c = _translit_word(p)
        out.append(c[:1].upper() + c[1:])
    return "".join(out), src
