#!/usr/bin/env python

"""
The result of g2_calibrate.py and g2_validate.py as tables, the same on the console (print_report) and
on the monitors (g2_validate.Screen.report).

A report is (title, ok, sections): ok True / False / None colours the title (green, red, black); a
section is (heading, rows), a row a list of cells, each a str or (str, ok) for a coloured mark.
"""

from __future__ import print_function

import unicodedata

GOOD = '#1a7f37'
BAD = '#c62828'
PLAIN = '#222222'


def colour(ok):
    return PLAIN if ok is None else (GOOD if ok else BAD)


def cell(c):
    """(text, ok) of a cell."""
    return c if isinstance(c, tuple) else (c, None)


def width(text):
    """Console columns of text (Hangul: two each)."""
    return sum(2 if unicodedata.east_asian_width(ch) in 'WF' else 1 for ch in text)


def pad(text, columns):
    return text + ' ' * max(0, columns - width(text))


def print_report(title, ok, sections):
    rule = '=' * 70
    print()
    print(rule)
    print('  %s' % title)
    print(rule)
    for heading, rows in sections:
        print()
        print('  ' + heading)
        if not rows:
            continue
        n = max(len(r) for r in rows)
        widths = [max(width(cell(r[i])[0]) for r in rows if i < len(r)) for i in range(n)]
        for r in rows:
            print('    ' + '   '.join(pad(cell(c)[0], widths[i]) for i, c in enumerate(r)).rstrip())
    print(rule)
