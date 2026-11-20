"""Pyosmium paths are UTF-8; its Windows C runtime must decode them as UTF-8 too.

    Python's Unicode filesystem support alone does not cover libosmium's narrow fopen.
    Configure LC_CTYPE in every builder process, preserving numeric/date formatting.
    https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/setlocale-wsetlocale
"""
import locale
import sys

if sys.platform == 'win32':
    locale.setlocale(locale.LC_CTYPE, '.UTF-8')

import osmium  # noqa: E402,F401 -- exported package, after configuring its C runtime
