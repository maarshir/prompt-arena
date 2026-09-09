from core.checks import check, contains_all, contains_none, exact, normalize


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


class TestContainsAll:
    def test_все_факты_на_месте(self):
        answer = "Воды 300 мл, зал был"
        assert contains_all(answer, ["300", "зал"]) is True

    def test_одного_факта_нет(self):
        answer = "Воды 300 мл"
        assert contains_all(answer, ["300", "зал"]) is False

    def test_пустой_список_всегда_верен(self):
        assert contains_all("что угодно", []) is True


class TestContainsNone:
    def test_мусора_нет(self):
        assert contains_none("2500", ["конечно", "вот ответ"]) is True

    def test_мусор_нашёлся(self):
        assert contains_none("Конечно! 2500", ["конечно"]) is False


class TestCheck:
    def test_пустое_ожидание_пропускает_всё(self):
        assert check("любой текст", {}) is True

    def test_условия_работают_вместе(self):
        expect = {"contains_all": ["300"], "contains_none": ["конечно"]}
        assert check("Воды 300 мл", expect) is True
        assert check("Конечно, воды 300 мл", expect) is False

    def test_одно_условие_не_выполнено_значит_провал(self):
        expect = {"exact": "да", "contains_none": ["нет"]}
        assert check("да", expect) is True
        assert check("нет", expect) is False
