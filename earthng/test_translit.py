"""translit.lua: Cyrillic names in Latin letters for the English UI."""
from pathlib import Path
import unittest

import lupa.luajit21 as lj

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'mod' / 'lua' / 'ge' / 'extensions' / 'e2r' / 'translit.lua'


def load():
    lua = lj.LuaRuntime()
    return lua.execute(SRC.read_text(encoding='utf8'))


class TranslitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.T = load()

    def latin(self, s, rule=None):
        return self.T.latin(s, rule) if rule else self.T.latin(s)

    def test_ukrainian_kmu_2010(self):
        # the resolution's own examples
        cases = {
            'Алушта': 'Alushta', 'Згорани': 'Zghorany', 'Розгон': 'Rozghon', 'Ґалаґан': 'Galagan',
            'Єнакієве': 'Yenakiieve', 'Гаєвич': 'Haievych', 'Їжакевич': 'Yizhakevych', 'Кадиївка': 'Kadyivka',
            'Йосипівка': 'Yosypivka', 'Стрий': 'Stryi', 'Юрій': 'Yurii', 'Корюківка': 'Koriukivka',
            'Яготин': 'Yahotyn', 'Костянтин': 'Kostiantyn', 'Знам\'янка': 'Znamianka', 'Щербухи': 'Shcherbukhy',
            'Вінниця': 'Vinnytsia', 'Київ': 'Kyiv', 'Білички': 'Bilychky', 'Харків': 'Kharkiv',
        }
        for uk, en in cases.items():
            self.assertEqual(self.latin(uk), en, uk)

    def test_words_capitals_and_the_rest(self):
        self.assertEqual(self.latin('вулиця Чорнобильська'), 'vulytsia Chornobylska')
        self.assertEqual(self.latin('ЩОРСА 12-А'), 'SHCHORSA 12-A')
        self.assertEqual(self.latin('Обʼєкт'), 'Obiekt')
        self.assertEqual(self.latin('McDonald\'s'), 'McDonald\'s')
        self.assertEqual(self.latin('АТБ-Маркет'), 'ATB-Market')
        self.assertEqual(self.latin('Ярмарок · 2'), 'Yarmarok · 2')

    def test_russian_by_its_letters(self):
        self.assertEqual(self.latin('Тверская улица'), 'Tverskaia ulytsa')  # no Russian-only letter: the Ukrainian rule
        self.assertEqual(self.latin('Тверская улица', 'ru'), 'Tverskaya ulitsa')
        self.assertEqual(self.latin('Мытищи'), 'Mytishchi')
        self.assertEqual(self.latin('Ельня, Подъём'), 'Yelnya, Podyom')

    def test_show_prefers_the_english_name(self):
        self.assertEqual(self.T.show('Київ', 'Kyiv', 'en'), 'Kyiv')
        self.assertEqual(self.T.show('Боярка', '', 'en'), 'Boiarka')
        self.assertEqual(self.T.show('Боярка', None, 'uk'), 'Боярка')


if __name__ == '__main__':
    unittest.main()
