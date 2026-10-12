"""Real posts (lightly trimmed) with the kind and regions the parser must produce."""
import pytest

from airraid.regions import find_regions
from airraid.sources.telegram import DROP, FOLLOW_UP, classify
from airraid.sources.telegram_parse import normalize

KP, AM = "kpszsu", "povitryanatrivogaaa"


@pytest.mark.parametrize("channel, text, kind, regions", [
    (KP, "🛵 БпЛА на Суми з півночі.", "drone", ["UA-59"]),
    (KP, "🏍 Реактивний БпЛА курсом на Вінницю з півночі.", "jet_drone", ["UA-05"]),
    (KP, "🚀Пуски керованих авіаційних бомб ворожою тактичною авіацією на Запоріжжі!", "guided_bomb", ["UA-23"]),
    (KP, "🚀Балістична ракета на Сумщині у напрямку Чернігівщини.", "ballistic", ["UA-59", "UA-74"]),
    (KP, "☄️ Загроза застосування балістичного озброєння з півночі.", "ballistic", []),
    (KP, "⚠УВАГА\n🚨 Вся Україна - ракетна небезпека!\n🛫 Зафіксовано зліт МіГ-31К.", "aviation", []),
    (KP, "📢 Відбій ракетної небезпеки по МіГ-31К.", "clear", []),
    (KP, "🛫 Активність ворожої тактичної авіації на північно-східному напрямку!", "aviation", []),
    (KP, "Ще одна ракета курсом на Дніпро!", "missile", ["UA-12"]),
    (KP, "Ціль повз Краснокутськ на Харківщині південно-західним напрямком", FOLLOW_UP, ["UA-63"]),
    (KP, "⚡️ ЗБИТО/ПОДАВЛЕНО 203 із 236", DROP, []),
    (AM, "✈️Чернігівщина:\n→Славутич/Київщина (2х).", "drone", ["UA-74", "UA-32"]),
    (AM, "💥 Хоростків/околиці (Тернопільщина) - вибухи", "explosion", ["UA-61"]),
    (AM, "⚠️🚀Загроза балістики з Брянська", "ballistic", []),
    (AM, "Бандероль 🚀→Дергачі/Харків", "missile", ["UA-63"]),
    (AM, "‼️ Одещина — чисто", "clear", ["UA-51"]),
    (AM, "‼️ Карта повітряних тривог ‼️", DROP, []),
    (AM, "💔 Київ. Пошкоджено багато житлових будинків", DROP, ["UA-30"]),
    (AM, "‼️ Одещина — дорозвідка", DROP, ["UA-51"]),
])
def test_classify_and_map(channel, text, kind, regions):
    assert classify(text, channel) == kind
    assert find_regions(text) == regions


def test_normalize_fixes_latin_lookalikes():
    assert normalize("Kиїв, рiвненщинa") == "Київ, рівненщина"
    assert normalize("Shahed над Kиєвом") == "Shahed над Києвом"


def test_update_text_is_cut_only_from_edited_posts():
    text = "✈️ БПЛА→Суми/р-н\nUPD 13:21: не фіксується"
    assert "UPD" not in normalize(text, edited=True)
    assert "UPD" in normalize(text, edited=False)
