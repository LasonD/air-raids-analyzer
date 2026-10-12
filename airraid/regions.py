"""Canonical region list shared by all sources: ISO 3166-2:UA codes, names, neighbours.

Source adapters map their own spellings onto these codes; the core only sees codes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Region:
    code: str                 # ISO 3166-2:UA
    name: str                 # English display name
    csv_name: str             # spelling used by the alert CSVs
    patterns: tuple[str, ...]  # Ukrainian regex fragments (oblast forms, centre, frequently named towns)
    neighbours: tuple[str, ...] = field(default=())


A = "['’ʼ]"  # apostrophe variants seen in Ukrainian text

# Town lists were extended from the most frequent unmatched words in the Telegram posts.
REGIONS: tuple[Region, ...] = (
    Region("UA-05", "Vinnytsia", "Vinnytska oblast", (r"Вінниц\w*", r"Віннич\w*", r"Козятин\w*"),
           ("UA-18", "UA-32", "UA-71", "UA-35", "UA-51", "UA-68", "UA-77")),
    Region("UA-07", "Volyn", "Volynska oblast", (r"Волин\w*", r"Луцьк\w*", r"Ковел\w*"),
           ("UA-56", "UA-46")),
    Region("UA-12", "Dnipropetrovsk", "Dnipropetrovska oblast",
           (r"Дніпр\w*", r"Крив\w* (?:Ріг|Рог\w*|Роз\w*)", r"Павлоград\w*", r"Нікопол\w*",
            r"Синельников\w*", rf"Кам{A}янськ\w*"),
           ("UA-63", "UA-53", "UA-35", "UA-48", "UA-65", "UA-23", "UA-14")),
    Region("UA-14", "Donetsk", "Donetska oblast",
           (r"Донеч\w*", r"Донецьк\w*", r"Краматорськ\w*", rf"Слов{A}янськ\w*"),
           ("UA-63", "UA-12", "UA-23")),
    Region("UA-18", "Zhytomyr", "Zhytomyrska oblast", (r"Житомир\w*", r"Бердичів\w*", r"Бердичев\w*", r"Коростен\w*"),
           ("UA-56", "UA-68", "UA-05", "UA-32")),
    Region("UA-21", "Zakarpattia", "Zakarpatska oblast", (r"Закарпат\w*", r"Ужгород\w*", r"Мукачев\w*"),
           ("UA-46", "UA-26")),
    Region("UA-23", "Zaporizhzhia", "Zaporizka oblast", (r"Запоріж\w*", r"Запоріз\w*"),
           ("UA-12", "UA-14", "UA-65")),
    Region("UA-26", "Ivano-Frankivsk", "Ivano-Frankivska oblast", (r"Івано-Франків\w*", r"Прикарпат\w*"),
           ("UA-46", "UA-21", "UA-77", "UA-61")),
    Region("UA-30", "Kyiv City", "Kyiv City", (r"Київ(?!щ|ськ)\w*", r"Києв\w*"),
           ("UA-32",)),
    Region("UA-32", "Kyiv Oblast", "Kyivska oblast",
           (r"Київщ\w*", r"Київськ\w* област\w*", r"Біл\w* Церк\w*", r"Бровар\w*",
            r"Васильк(?:ів|ова|ові)\b", r"Борисп(?:іль|оля|олі)\b", r"Обух(?:ів|ова|ові)\b", r"Буч(?:а|у|і|ею)\b",
            r"Ірпін\w*", r"Гостомел\w*", r"Вишгород\w*", r"Димер\w*", r"Глевах\w*", r"Українк\w*", r"Боярк\w*",
            r"Фаст(?:ів|ова|ові)\b", r"Славутич\w*", r"Макар(?:ів|ова|ові)\b"),
           ("UA-30", "UA-18", "UA-05", "UA-71", "UA-53", "UA-74")),
    Region("UA-35", "Kirovohrad", "Kirovohradska oblast", (r"Кіровоград\w*", r"Кропивницьк\w*", r"Олександрі\w*"),
           ("UA-05", "UA-71", "UA-53", "UA-12", "UA-48", "UA-51")),
    Region("UA-46", "Lviv", "Lvivska oblast", (r"Львів\w*", r"Львов\w*"),
           ("UA-07", "UA-56", "UA-61", "UA-26", "UA-21")),
    Region("UA-48", "Mykolaiv", "Mykolaivska oblast",
           (r"Миколаїв\w*", r"Миколаєв\w*", r"Очак\w*", r"Первомайськ\w*", r"Вознесенськ\w*"),
           ("UA-51", "UA-35", "UA-12", "UA-65")),
    Region("UA-51", "Odesa", "Odeska oblast",
           (r"Одес\w*", r"Одещ\w*", r"Ізмаїл\w*", r"Чорноморськ\w*", r"Заток\w*", r"Білгород-?\s?Дністров\w*",
            r"Біляр\w*", r"Біляїв\w*"),
           ("UA-05", "UA-35", "UA-48")),
    Region("UA-53", "Poltava", "Poltavska oblast", (r"Полтав\w*", r"Кременчук\w*", r"Миргород\w*"),
           ("UA-74", "UA-59", "UA-63", "UA-12", "UA-35", "UA-71", "UA-32")),
    Region("UA-56", "Rivne", "Rivnenska oblast", (r"Рівн\w*",),
           ("UA-07", "UA-46", "UA-61", "UA-68", "UA-18")),
    Region("UA-59", "Sumy", "Sumska oblast",
           (r"Сум(?:и|ах|ам|щ\w*|ськ\w*)\b", r"Конотоп\w*", r"Шостк\w*", r"Ромн\w*", r"Охтирк\w*",
            r"Глух(?:ів|ова|ові)\b"),
           ("UA-74", "UA-53", "UA-63")),
    Region("UA-61", "Ternopil", "Ternopilska oblast", (r"Тернопіл\w*",),
           ("UA-56", "UA-46", "UA-26", "UA-77", "UA-68")),
    Region("UA-63", "Kharkiv", "Kharkivska oblast",
           (r"Харків\w*", r"Харков\w*", r"Дергач\w*", r"Чугу\w*", r"Лозов\w*", r"Ізюм\w*", rf"Куп{A}янськ\w*"),
           ("UA-59", "UA-53", "UA-12", "UA-14")),
    Region("UA-65", "Kherson", "Khersonska oblast", (r"Херсон\w*",),
           ("UA-48", "UA-12", "UA-23")),
    Region("UA-68", "Khmelnytskyi", "Khmelnytska oblast",
           (r"Хмельниц\w*", r"Хмельнич\w*", r"Старокостянтинів\w*", r"Шепетів\w*"),
           ("UA-56", "UA-61", "UA-77", "UA-05", "UA-18")),
    Region("UA-71", "Cherkasy", "Cherkaska oblast", (r"Черкас\w*", r"Черкащ\w*", r"Умань\w*", r"Умані"),
           ("UA-32", "UA-53", "UA-35", "UA-05")),
    Region("UA-74", "Chernihiv", "Chernihivska oblast", (r"Чернігів\w*", r"Чернігов\w*", r"Ніжин\w*", r"Прилук\w*"),
           ("UA-32", "UA-53", "UA-59")),
    Region("UA-77", "Chernivtsi", "Chernivetska oblast", (r"Чернівц\w*", r"Чернівеч\w*", r"Буковин\w*"),
           ("UA-26", "UA-61", "UA-68", "UA-05")),
)

# Not forecast: Luhansk has been under a permanent alert since 2022 (3 records in the data),
# Crimea and Sevastopol are absent from the alert data.
EXCLUDED = {"UA-09": "Luhanska oblast", "UA-43": "Crimea", "UA-40": "Sevastopol"}

BY_CODE = {r.code: r for r in REGIONS}
BY_CSV_NAME = {r.csv_name: r.code for r in REGIONS}
CODES = tuple(r.code for r in REGIONS)

_MATCHERS = [(r.code, re.compile(rf"(?<![\w'’ʼ-])(?:{'|'.join(r.patterns)})")) for r in REGIONS]


def find_regions(text: str) -> list[str]:
    """Region codes mentioned in Ukrainian text, in order of first mention."""
    hits = sorted((m.start(), code) for code, rx in _MATCHERS if (m := rx.search(text)))
    return [code for _, code in hits]
