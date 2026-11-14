#!/usr/bin/env python

"""
Per-cell SAGAT accuracy of the 8-cell era (to 2026-11-12: behind / beside / ahead, each left, own
lane, right; the beside cells only left and right), for the paper's case that the cells beside the
car are at chance (they were dropped on 2026-11-13).

    python _Experiment2/sagat_cells.py                         Data/test, set A
    python _Experiment2/sagat_cells.py --sets A P --out x.csv

Reads every sagat.json under Data/ (recursively) with 8 items per stop and the driver's answers
(ended_by answer; the runs with no answer, e.g. the participant 0 test drives, are left out). Two
formats: 'items' (2026-11-12 evening on: behind_left .. ahead_right; before that mirror_left /
mirror_rear / mirror_right in place of the behind cells, 'in the mirror', counted as behind_* with
the column format 'items-mirror') and the older grid ('cells' clicked: 1_front .. 3_rear, a cell
not clicked = absent). Out: per cell n, correct, accuracy, the exact two-sided binomial p against
0.5, hits / misses / false alarms / correct rejections, the mean confidence where there is one.
"""

from __future__ import print_function

import argparse
import csv
import glob
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CELLS = ['behind_left', 'behind', 'behind_right', 'beside_left', 'beside_right', 'ahead_left', 'ahead',
         'ahead_right']
GROUP = {'behind_left': 'behind', 'behind': 'behind', 'behind_right': 'behind', 'beside_left': 'beside',
         'beside_right': 'beside', 'ahead_left': 'ahead', 'ahead': 'ahead', 'ahead_right': 'ahead'}
GRID = {'1_rear': 'behind_left', '2_rear': 'behind', '3_rear': 'behind_right', '1_side': 'beside_left',
        '3_side': 'beside_right', '1_front': 'ahead_left', '2_front': 'ahead', '3_front': 'ahead_right'}
MIRROR_ITEMS = {'mirror_left': 'behind_left', 'mirror_rear': 'behind', 'mirror_right': 'behind_right'}


def binom_p(k, n, p=0.5):
    """Exact two-sided binomial test (the outcomes no more likely than k)."""
    if n == 0:
        return float('nan')
    probs = [math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(n + 1)]
    return min(1.0, sum(q for q in probs if q <= probs[k] * (1 + 1e-9)))


def trials(path):
    """[(cell, truth, answer, confidence or None, format)] of one sagat.json's answered stops."""
    out = []
    with open(path, encoding='utf-8') as handle:
        stops = json.load(handle)
    for q in stops:
        if q.get('ended_by') != 'answer' or not (q.get('score') or {}).get('answered'):
            continue
        truth, answer = q.get('truth') or {}, q.get('answer') or {}
        unscored = set((q.get('score') or {}).get('unscored') or []) | set(truth.get('ambiguous') or [])
        if len(truth.get('items') or {}) == 8 and answer.get('items'):
            for item, present in truth['items'].items():
                cell = MIRROR_ITEMS.get(item, item)
                a = answer['items'].get(item) or {}
                if cell not in CELLS or item in unscored or a.get('present') is None:
                    continue
                out.append((cell, bool(present), bool(a['present']), a.get('confidence'),
                            'items-mirror' if item in MIRROR_ITEMS else 'items', q['id']))
        elif 'cells' in answer and 'cells' in truth:
            chosen = set(answer['cells'])
            for grid, cell in GRID.items():
                out.append((cell, grid in truth['cells'], grid in chosen, None, 'grid', q['id']))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--data', default=os.path.join(HERE, 'Data'))
    parser.add_argument('--sets', nargs='+', default=['A'])
    parser.add_argument('--out', default=os.path.join(HERE, 'claude_reply', 'sagat_8cell_accuracy.csv'))
    args = parser.parse_args()
    rows = []
    for path in sorted(glob.glob(os.path.join(args.data, '**', 'sagat.json'), recursive=True)):
        folder = os.path.dirname(path)
        try:
            with open(os.path.join(folder, 'run.json'), encoding='utf-8') as handle:
                a = json.load(handle).get('args') or {}
        except (OSError, ValueError):
            continue
        if a.get('set') not in args.sets:
            continue
        for t in trials(path):
            rows.append((os.path.basename(folder), a.get('participant'), a.get('set')) + t)
    if not rows:
        raise SystemExit('no answered 8-cell SAGAT stops for sets %s' % ' '.join(args.sets))
    blocks = sorted({(r[0], r[1], r[2], r[7]) for r in rows})
    print('blocks (folder, participant, set, format): ' + '; '.join('%s P%s %s %s' % b for b in blocks))
    print('stops: %d' % len({(r[0], r[8]) for r in rows}))
    table = []
    for label, keys in [(c, [c]) for c in CELLS] + [('all ' + g, [c for c in CELLS if GROUP[c] == g])
                                                    for g in ('behind', 'beside', 'ahead')] + \
            [('side lanes ahead', ['ahead_left', 'ahead_right']), ('side lanes behind', ['behind_left', 'behind_right']),
             ('own lane', ['behind', 'ahead']), ('all', CELLS)]:
        mine = [r for r in rows if r[3] in keys]
        n = len(mine)
        k = sum(1 for r in mine if r[4] == r[5])
        hit = sum(1 for r in mine if r[4] and r[5])
        miss = sum(1 for r in mine if r[4] and not r[5])
        fa = sum(1 for r in mine if not r[4] and r[5])
        cr = sum(1 for r in mine if not r[4] and not r[5])
        conf = [r[6] for r in mine if r[6] is not None]
        table.append({'cell': label, 'n': n, 'correct': k, 'accuracy': round(k / float(n), 3) if n else '',
                      'p_vs_chance': round(binom_p(k, n), 3) if n else '', 'present_n': hit + miss,
                      'hits': hit, 'misses': miss, 'false_alarms': fa, 'correct_rejections': cr,
                      'mean_confidence': round(sum(conf) / float(len(conf)), 2) if conf else ''})
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)
    print('%-14s %3s %4s %6s %7s  %s' % ('cell', 'n', 'ok', 'acc', 'p(0.5)', 'hit miss FA CR  conf'))
    for t in table:
        print('%-14s %3d %4d %6s %7s  %d %d %d %d  %s' % (t['cell'], t['n'], t['correct'], t['accuracy'],
                                                          t['p_vs_chance'], t['hits'], t['misses'],
                                                          t['false_alarms'], t['correct_rejections'],
                                                          t['mean_confidence']))
    print('written: %s' % args.out)


if __name__ == '__main__':
    main()
