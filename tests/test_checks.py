import pytest

from core.checks import check, contains_all, contains_none, exact, found, normalize


class TestNormalize:
    def test_убирает_регистр_и_края(self):
        assert normalize("  ДА Был.  ") == "да был"

    def test_схлопывает_пробелы_и_переносы(self):
        assert normalize("два\n\n  слова") == "два слова"


class TestExact:
    def test_совпадение_несмотря_на_регистр_и_точку(self):
        assert exact("Да.", "да") is True

    def test_разные_ответы(self):
        assert exact("нет", "да") is False

    def test_лишнее_слово_это_уже_не_точно(self):
        assert exact("конечно да", "да") is False

    def test_число_в_ожидании(self):
        # exact: 5 без кавычек раньше падал с AttributeError
        assert exact("5", 5) is True
        assert exact("6", 5) is False


class TestContainsAll:
    def test_все_факты_на_месте(self):
        answer = "Сумма 300 руб, курьер приехал"
        assert contains_all(answer, ["300", "курьер"]) is True

    def test_одного_факта_нет(self):
        answer = "Сумма 300 руб"
        assert contains_all(answer, ["300", "курьер"]) is False

    def test_пустой_список_всегда_верен(self):
        assert contains_all("что угодно", []) is True

    def test_значение_не_режется_посередине(self):
        # главный случай: 0.35 это не 0.3
        assert contains_all("weight=0.35; urgent=yes", ["weight=0.3"]) is False
        assert contains_all("weight=0.3; urgent=yes", ["weight=0.3"]) is True

    def test_точка_в_конце_ответа_не_мешает(self):
        assert contains_all("weight=0.3.", ["weight=0.3"]) is True


class TestFound:
    @pytest.mark.parametrize(
        "item, text",
        [
            ("300", "сумма 300 руб"),
            ("weight=0.3", "weight=0.3; urgent=yes"),
            ("weight=0.3", "итог: weight=0.3"),
            ("items=6", "items=6, urgent=no"),
            ("заказ", "по заказу 7710"),  # слова ищутся как подстрока, окончания не мешают
            ("urgent=yes", "urgent=yes;items=7"),
            ("0.5", "вес 0.5 кг"),
        ],
    )
    def test_находит(self, item, text):
        assert found(item, text) is True

    @pytest.mark.parametrize(
        "item, text",
        [
            ("weight=0.3", "weight=0.35"),
            ("weight=0.3", "weight=0.3,5"),  # дробь через запятую
            ("300", "1300 руб"),
            ("5", "вес 0.5 кг"),
            ("5", "вес 0,5 кг"),
            ("0.3", "10.3"),
            ("items=6", "items=6.5"),
        ],
    )
    def test_не_режет_число(self, item, text):
        assert found(item, text) is False

    def test_пустой_кусок_всегда_есть(self):
        assert found("", "что угодно") is True


class TestContainsNone:
    def test_мусора_нет(self):
        assert contains_none("2500", ["конечно", "вот ответ"]) is True

    def test_мусор_нашёлся(self):
        assert contains_none("Конечно! 2500", ["конечно"]) is False

    def test_граница_числа_работает_и_здесь(self):
        # запрещено ровно 0, а 0.5 это другое значение
        assert contains_none("weight=0.5", ["weight=0"]) is True
        assert contains_none("weight=0", ["weight=0"]) is False


class TestCheck:
    def test_пустое_ожидание_пропускает_всё(self):
        assert check("любой текст", {}) is True

    def test_условия_работают_вместе(self):
        expect = {"contains_all": ["300"], "contains_none": ["конечно"]}
        assert check("Сумма 300 руб", expect) is True
        assert check("Конечно, сумма 300 руб", expect) is False

    def test_одно_условие_не_выполнено_значит_провал(self):
        expect = {"exact": "да", "contains_none": ["нет"]}
        assert check("да", expect) is True
        assert check("нет", expect) is False
