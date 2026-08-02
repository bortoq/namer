"""Tests for the extracted, offline language helpers (namer/language)."""

import sys
import pytest

sys.path.insert(0, '/home/user/work/namer')

from namer.language import detect_language, is_valid_language  # noqa: E402


class TestIsValidLanguage:
    @pytest.mark.parametrize("code,exp", [
        ("en", True),
        ("ru", True),
        ("de", True),
        ("ja", True),
        ("fr", True),
        ("be", True),
        ("ZZ", False),
        ("", False),
        ("english", False),
        ("en-US", False),
    ])
    def test_known_codes(self, code, exp):
        assert is_valid_language(code) is exp


class TestDetectLanguage:
    @pytest.mark.parametrize("text,exp", [
        ("Матрица", "ru"),
        ("Невидимый гость", "ru"),
        ("Открытие", "ru"),
        ("マトリックス", "ja"),          # CJK fallback -> ja
        ("マトリックス", "ja"),
        ("الدماغ", "ar"),
        ("Σκοτεινή θάλασσα", "el"),
        ("ชม", "th"),
        ("The Matrix", None),          # Latin-only -> None
        ("", None),
        ("1999", None),
        (None, None),
    ])
    def test_detect(self, text, exp):
        assert detect_language(text) == exp

    def test_cyrillic_extended(self):
        # Includes U+0500 range (extended Cyrillic)
        assert detect_language("\u0500\u0501") == "ru"

    def test_japanese_dict_appears(self):
        assert detect_language("日本語の") == "ja"
