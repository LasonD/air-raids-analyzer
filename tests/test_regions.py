import pytest

from airraid.regions import BY_CODE, CODES, find_regions


def test_neighbours_are_symmetric_and_known():
    for code in CODES:
        for n in BY_CODE[code].neighbours:
            assert n in BY_CODE, f"{code} lists unknown neighbour {n}"
            assert code in BY_CODE[n].neighbours, f"{code} -> {n} is not mirrored"


@pytest.mark.parametrize("text, expected", [
    ("🛵 БпЛА на Суми з півночі.", ["UA-59"]),
    ("💣 КАБи на Харківщину.", ["UA-63"]),
    ("🏍 Реактивний БпЛА через південь Хмельниччини в напрямку Тернопільщини.", ["UA-68", "UA-61"]),
    ("Загроза ударних БпЛА в м. Запоріжжя та Запорізька територіальна громада!", ["UA-23"]),
    ("✈️ Житомирщина: →Бердичів/р-н; →Попільня. ✈️ Київщина: →Наливайківка/Макарів.", ["UA-18", "UA-32"]),
    ("Вибухи в Києві. Загроза балістики триває.", ["UA-30"]),
    ("БпЛА на Київщині курсом на Київ", ["UA-32", "UA-30"]),
    ("Ракета на Кривий Ріг", ["UA-12"]),
    ("Сума збитків", []),
])
def test_find_regions(text, expected):
    assert find_regions(text) == expected
