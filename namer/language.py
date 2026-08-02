"""Language code validation and script-based language detection.

Pure, offline, deterministic helpers shared by the CLI, core and the
wikipedia translation layer.  Deliberately independent of any network call:
validation is a set membership check and detection only inspects Unicode
script ranges.
"""

import re
from typing import Optional

# ── Known Wikipedia languages ──────────────────────────────────────────────────

# Active Wikipedia language codes (from API sitematrix, 374 languages)
_KNOWN_LANGUAGES = frozenset({
    "aa", "ab", "ace", "ady", "af", "ak", "als", "alt", "am", "ami", "an", "ang",
    "ann", "anp", "ar", "arc", "ary", "arz", "as", "ast", "atj", "av", "avk", "awa",
    "ay", "az", "azb", "ba", "ban", "bar", "bat-smg", "bbc", "bcl", "bdr", "be",
    "be-tarask", "be-x-old", "bew", "bg", "bh", "bi", "bjn", "blk", "bm", "bn", "bo",
    "bol", "bpy", "br", "bs", "btm", "bug", "bxr", "ca", "cbk-zam", "cdo", "ce", "ceb",
    "ch", "cho", "chr", "chy", "ckb", "co", "cr", "crh", "cs", "csb", "cu", "cv", "cy",
    "da", "dag", "de", "dga", "din", "diq", "dsb", "dtp", "dty", "dv", "dz", "ee", "el",
    "eml", "en", "eo", "es", "et", "eu", "ext", "fa", "fat", "ff", "fi", "fiu-vro", "fj",
    "fo", "fon", "fr", "frp", "frr", "fur", "fy", "ga", "gag", "gan", "gcr", "gd", "gl",
    "glk", "gn", "gom", "gor", "got", "gpe", "gsw", "gu", "guc", "gur", "guw", "gv", "ha",
    "hak", "haw", "he", "hi", "hif", "ho", "hr", "hsb", "ht", "hu", "hy", "hyw", "hz",
    "ia", "iba", "id", "ie", "ig", "igl", "ii", "ik", "ilo", "inh", "io", "is", "isv",
    "it", "iu", "ja", "jam", "jbo", "jv", "ka", "kaa", "kab", "kai", "kaj", "kbd", "kbp",
    "kcg", "kg", "kge", "ki", "kj", "kk", "kl", "km", "kn", "knc", "ko", "koi", "kr",
    "krc", "ks", "ksh", "ku", "kus", "kv", "kw", "ky", "la", "lad", "lb", "lbe", "lez",
    "lfn", "lg", "li", "lij", "lld", "lmo", "ln", "lo", "lrc", "lt", "ltg", "lv", "lzh",
    "mad", "mag", "mai", "map-bms", "mdf", "mg", "mh", "mhr", "mi", "min", "mk", "ml",
    "mn", "mni", "mnw", "mo", "mos", "mr", "mrj", "ms", "mt", "mus", "mwl", "my", "myv",
    "mzn", "na", "nah", "nap", "nds", "nds-nl", "ne", "new", "ng", "nia", "nl",
    "nn", "no", "nov", "nqo", "nr", "nrm", "nso", "nup", "nv", "ny", "oc", "olo", "om",
    "or", "os", "pa", "pag", "pam", "pap", "pcd", "pcm", "pdc", "pfl", "pi", "pih", "pl",
    "pms", "pnb", "pnt", "ppl", "ps", "pt", "pwn", "qu", "rki", "rm", "rmy", "rn", "ro",
    "roa-rup", "roa-tara", "rsk", "ru", "rue", "rup", "rw", "sa", "sah", "sat", "sc",
    "scn", "sco", "sd", "se", "sg", "sgs", "sh", "shi", "shn", "shy", "si", "simple",
    "sk", "skr", "sl", "sm", "smn", "sn", "so", "sq", "sr", "srn", "ss", "st", "stq",
    "su", "sv", "sw", "syl", "szl", "szy", "ta", "tay", "tcy", "tdd", "te", "tet", "tg",
    "th", "ti", "tig", "tk", "tl", "tly", "tn", "to", "tok", "tpi", "tr", "trv", "ts",
    "tt", "tum", "tw", "ty", "tyv", "udm", "ug", "uk", "ur", "uz", "ve", "vec", "vep",
    "vi", "vls", "vo", "vro", "wa", "war", "wo", "wuu", "xal", "xh", "xmf", "yi", "yo",
    "yue", "za", "zea", "zgh", "zh", "zh-classical", "zh-min-nan", "zh-yue", "zu",
})


def is_valid_language(code: str) -> bool:
    """Check if *code* is a known active Wikipedia language code."""
    return code in _KNOWN_LANGUAGES


# ── Language detection ────────────────────────────────────────────────────────

# Cyrillic range: U+0400–U+04FF + U+0500–U+052F
_CYRILLIC_RE = re.compile(r'[\u0400-\u052F]')

# CJK (Chinese, Japanese, Korean)
_CJK_RE = re.compile(r'[\u3040-\u9FFF\uAC00-\uD7AF]')

# Arabic
_ARABIC_RE = re.compile(r'[\u0600-\u06FF]')

# Greek
_GREEK_RE = re.compile(r'[\u0370-\u03FF]')

# Thai
_THAI_RE = re.compile(r'[\u0E00-\u0E7F]')

_LANG_MAP = [
    (_CYRILLIC_RE, 'ru'),    # Russian for Cyrillic
    (_CJK_RE, 'ja'),         # Japanese for CJK (fallback, not ideal)
    (_ARABIC_RE, 'ar'),
    (_GREEK_RE, 'el'),
    (_THAI_RE, 'th'),
]


def detect_language(title: str) -> Optional[str]:
    """Detect a Wikipedia language code from *title* characters.

    Returns a two-letter code (e.g. 'ru', 'ja') or None for Latin-only text
    (assumed English).
    """
    for pattern, lang in _LANG_MAP:
        if pattern.search(title or ''):
            return lang
    return None
