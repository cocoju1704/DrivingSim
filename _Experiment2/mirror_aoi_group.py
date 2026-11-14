#!/usr/bin/env python

"""
Mirror glances between participants: every block's mirror_aoi_rates.csv (mirror_aoi.py) with its
run.json (participant, block, set, condition), summed up per condition.

    python _Experiment2/mirror_aoi_group.py                     Data/ without Data/test
    python _Experiment2/mirror_aoi_group.py --test              Data/test too (the test drives)
    python _Experiment2/mirror_aoi_group.py --test --practice   the practice blocks (set P) too
    python _Experiment2/mirror_aoi_group.py --out <dir>         (default: Data/)

Blocks: under --data recursively; set P (practice) left out unless --practice; a block shorter than
--min-s (real s of its 'block' segment, default 60: aborted starts) left out; a participant's block
(participant, block number, set, condition) recorded more than once: the last run at least FULL_SHARE as long as the
longest kept (--all-runs: all).

Segments: block, auto (to the TOR alert), sagat_pre (the PRE_S before every SAGAT freeze of the
block pooled: glances over the summed minutes, dwell over the summed seconds), tor_pre, tor_post.
Measures per mirror (left, rear, right) and all three (any): glances per minute of real time
(per_min, the main measure), dwell share of the segment (dwell_share) and dwell s; eye_data_share.
Two variants (sensitivity): sure = the glances as judged (the unsure runs next to a glance joined
in), with_unsure = the unsure runs left over (left? / right?) counted as glances at that side's
mirror too (mirror_aoi_rates.csv's _with_unsure columns).

Out, into --out:
    mirror_aoi_group_blocks.csv    one row per block x segment x variant: the block's values
    mirror_aoi_group_summary.csv   per condition x segment x variant x measure: n (blocks), mean, SD,
                                   median, min, max; and the participants
"""

from __future__ import print_function

import argparse
import csv
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MIRRORS = ('left', 'rear', 'right')
SEGMENTS = ('block', 'auto', 'sagat_pre', 'tor_pre', 'tor_post')
VARIANTS = (('sure', ''), ('with_unsure', '_with_unsure'))
CONDITIONS = ('glasses', 'phone', 'hud')
FULL_SHARE = 0.9    # a participant's block run more than once: the last run at least this share as long as the longest


def number(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def find_blocks(data, test):
    """[(folder, run.json args)] of the folders with mirror_aoi_rates.csv."""
    out = []
    for root, dirs, files in os.walk(data):
        dirs.sort()
        if not test and os.path.basename(root) == 'test' and os.path.dirname(root) == os.path.abspath(data):
            dirs[:] = []
            continue
        if 'mirror_aoi_rates.csv' in files and 'run.json' in files:
            try:
                with open(os.path.join(root, 'run.json'), encoding='utf-8') as handle:
                    run = json.load(handle)
            except (OSError, ValueError):
                continue
            args = dict(run.get('args') or {})
            for key in ('participant', 'block', 'set', 'condition'):
                args.setdefault(key, run.get(key))
            out.append((root, args))
    return out


def block_rows(folder, args):
    """{(segment, variant): {measure: value}} of one block (sagat_pre pooled)."""
    with open(os.path.join(folder, 'mirror_aoi_rates.csv'), encoding='utf-8') as handle:
        rates = list(csv.DictReader(handle))
    out = {}
    for segment in SEGMENTS:
        mine = [r for r in rates if r['segment'] == segment or (segment == 'sagat_pre' and r['segment'].startswith('sagat_pre '))]
        if not mine:
            continue
        real = sum(number(r['real_s']) for r in mine)
        length = sum(number(r['end']) - number(r['start']) for r in mine)
        eye = sum(number(r['eye_data_share']) * number(r['real_s']) for r in mine) / real if real else 0.0
        for variant, suffix in VARIANTS:
            row = {'real_s': round(real, 1), 'windows': len(mine), 'eye_data_share': round(eye, 3)}
            total_n = total_dwell = 0.0
            for m in MIRRORS:
                n = sum(number(r.get('%s_n%s' % (m, suffix))) for r in mine)
                dwell = sum(number(r.get('%s_dwell_s%s' % (m, suffix))) for r in mine)
                total_n += n
                total_dwell += dwell
                row.update({'%s_n' % m: int(n), '%s_per_min' % m: round(n / (real / 60.0), 3) if real else '',
                            '%s_dwell_s' % m: round(dwell, 2),
                            '%s_dwell_share' % m: round(dwell / length, 4) if length else ''})
            row.update({'any_n': int(total_n), 'any_per_min': round(total_n / (real / 60.0), 3) if real else '',
                        'any_dwell_s': round(total_dwell, 2),
                        'any_dwell_share': round(total_dwell / length, 4) if length else ''})
            out[(segment, variant)] = row
    return out


MEASURES = ['eye_data_share'] + ['%s_%s' % (m, k) for m in MIRRORS + ('any',) for k in ('per_min', 'dwell_share', 'dwell_s', 'n')]


def describe(values):
    n = len(values)
    if not n:
        return {'n': 0}
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1)) if n > 1 else ''
    s = sorted(values)
    median = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0
    return {'n': n, 'mean': round(mean, 4), 'sd': '' if sd == '' else round(sd, 4), 'median': round(median, 4),
            'min': round(s[0], 4), 'max': round(s[-1], 4)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--data', default=os.path.join(HERE, 'Data'))
    parser.add_argument('--test', action='store_true', help='Data/test too')
    parser.add_argument('--practice', action='store_true', help='the practice blocks (set P) too')
    parser.add_argument('--min-s', type=float, default=60.0, help='blocks shorter than this (real s) left out')
    parser.add_argument('--all-runs', action='store_true', help='keep every run of a participant\'s block')
    parser.add_argument('--out', help='output folder (default: --data)')
    args = parser.parse_args()
    data = os.path.abspath(args.data)
    out_dir = os.path.abspath(args.out or data)
    blocks = []
    for folder, run in find_blocks(data, args.test):
        if run.get('set') == 'P' and not args.practice:
            continue
        rows = block_rows(folder, run)
        real = (rows.get(('block', 'sure')) or {}).get('real_s', 0.0)
        if real < args.min_s:
            print('left out (%.0f s): %s' % (real, os.path.relpath(folder, data)))
            continue
        blocks.append((folder, run, rows, real))
    if not args.all_runs:
        # one run per participant's block: the last one (folder order = time) of those at least
        # FULL_SHARE as long as the longest (a restart after an aborted start)
        runs = {}
        for b in blocks:
            runs.setdefault((str(b[1].get('participant')), str(b[1].get('block')), b[1].get('set'), b[1].get('condition')), []).append(b)
        blocks = []
        for key, mine in sorted(runs.items()):
            longest = max(b[3] for b in mine)
            keep = [b for b in sorted(mine, key=lambda b: os.path.basename(b[0])) if b[3] >= FULL_SHARE * longest][-1]
            for b in mine:
                if b is not keep:
                    print('left out (P%s block %s %s %s run again in %s): %s' % (key[0], key[1], key[2], key[3],
                                                                          os.path.basename(keep[0]), os.path.relpath(b[0], data)))
            blocks.append(keep)
        blocks.sort(key=lambda b: b[0])
    if not blocks:
        raise SystemExit('no blocks with mirror_aoi_rates.csv under %s%s' % (data, '' if args.test else ' (--test: Data/test too)'))
    os.makedirs(out_dir, exist_ok=True)
    head = ['folder', 'participant', 'block', 'set', 'condition', 'segment', 'variant', 'real_s', 'windows']
    long_rows = []
    for folder, run, rows, _ in blocks:
        for (segment, variant), values in sorted(rows.items(), key=lambda kv: (SEGMENTS.index(kv[0][0]), kv[0][1])):
            r = {'folder': os.path.relpath(folder, data), 'participant': run.get('participant'), 'block': run.get('block'),
                 'set': run.get('set'), 'condition': run.get('condition'), 'segment': segment, 'variant': variant}
            r.update(values)
            long_rows.append(r)
    with open(os.path.join(out_dir, 'mirror_aoi_group_blocks.csv'), 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=head + MEASURES, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(long_rows)
    conditions = [c for c in CONDITIONS if any(b[1].get('condition') == c for b in blocks)] + \
        sorted({b[1].get('condition') or '?' for b in blocks} - set(CONDITIONS))
    summary = []
    for condition in conditions:
        for segment in SEGMENTS:
            for variant, _ in VARIANTS:
                mine = [r for r in long_rows if (r['condition'] or '?') == condition and r['segment'] == segment
                        and r['variant'] == variant]
                if not mine:
                    continue
                for measure in MEASURES:
                    values = [float(r[measure]) for r in mine if r.get(measure) not in ('', None)]
                    row = {'condition': condition, 'segment': segment, 'variant': variant, 'measure': measure,
                           'participants': ' '.join(sorted({str(r['participant']) for r in mine}))}
                    row.update(describe(values))
                    summary.append(row)
    with open(os.path.join(out_dir, 'mirror_aoi_group_summary.csv'), 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=['condition', 'segment', 'variant', 'measure', 'n', 'mean', 'sd',
                                                    'median', 'min', 'max', 'participants'])
        writer.writeheader()
        writer.writerows(summary)
    print('%d blocks: %s' % (len(blocks), ', '.join('%s (P%s B%s %s %s)' % (
        os.path.basename(b[0]), b[1].get('participant'), b[1].get('block'), b[1].get('set'), b[1].get('condition'))
        for b in blocks)))
    print('\nglances per minute, mean (SD) [n], sure | with unsure:')
    print('%-9s %-10s %s' % ('condition', 'segment', '   '.join('%-24s' % m for m in MIRRORS + ('any',))))
    look = {(r['condition'], r['segment'], r['variant'], r['measure']): r for r in summary}
    for condition in conditions:
        for segment in SEGMENTS:
            cells = []
            for m in MIRRORS + ('any',):
                parts = []
                for variant, _ in VARIANTS:
                    r = look.get((condition, segment, variant, '%s_per_min' % m))
                    parts.append('-' if not r or not r['n'] else '%.2f%s' % (
                        r['mean'], '' if r['sd'] == '' else ' (%.2f)' % r['sd']))
                n = (look.get((condition, segment, 'sure', '%s_per_min' % m)) or {}).get('n', 0)
                cells.append('%-24s' % ('%s | %s [%d]' % (parts[0], parts[1], n)))
            if any(c.strip() != '- | - [0]' for c in cells):
                print('%-9s %-10s %s' % (condition, segment, '   '.join(cells)))
    print('\nwritten: %s, %s' % (os.path.join(out_dir, 'mirror_aoi_group_blocks.csv'),
                                 os.path.join(out_dir, 'mirror_aoi_group_summary.csv')))


if __name__ == '__main__':
    main()
