#!/usr/bin/env python

"""
Analyze the takeover logs written by takeover_experiment.py.

Every run leaves a folder Data/YYMMDD_HHMMSS/ (the start time of the run) with

    raw.csv      one row per frame from the pre-alert on, plus a TRIAL_END row per trial
    summary.csv  takeover metrics per trial
    figure.png   speed, acceleration, lane offset and driver input of every trial

takeover_experiment.py writes summary.csv and figure.png when it ends. This script
makes them again from raw.csv (for example after a crash, or with another --window)
and prints the metrics.

For every trial (one P-key takeover sequence) the metrics are recomputed from the
per-frame rows. They follow Bai et al. (2024), Human Factors 66(12): takeover time
(TOT) and the maximum lateral / longitudinal acceleration (MAlat, MAlon) of the
takeover period.

A collision gives a huge acceleration spike (hundreds of m/s2). MAlat / MAlon are
therefore reported twice: all frames, and "clean" without the frames around a
collision (0.1 s before to 1 s after it).

Run from the CARLA_0.9.16 root folder:

    python PythonAPI\\scripts\\analyze_takeover.py                     newest run in Data
    python PythonAPI\\scripts\\analyze_takeover.py Data\\261006_173529   chosen run(s)
    python PythonAPI\\scripts\\analyze_takeover.py --all               every run in Data
    python PythonAPI\\scripts\\analyze_takeover.py --window 15         other takeover period
"""

from __future__ import print_function

import argparse
import csv
import os
import statistics
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
DATA_DIR = os.path.join(ROOT, 'Data')

NUMERIC = ['t_prealert_s', 't_tor_s', 'speed_kmh', 'a_lon', 'a_lat', 'steer', 'throttle', 'brake',
           'driver_steer', 'driver_throttle', 'driver_brake', 'lane_offset_m', 'lead_gap_m',
           'lead_speed_kmh', 'ttc_s', 'first_input_s', 'tot_s', 'tor_reaction_s']
COLLISION_BEFORE = 0.1  # seconds excluded before a collision
COLLISION_AFTER = 1.0   # seconds excluded after a collision


# ==============================================================================
# -- loading -------------------------------------------------------------------
# ==============================================================================


def _num(value):
    return float(value) if value not in ('', None) else None


def load_trials(path):
    """{trial number: [rows]} with the numeric columns converted to float or None."""
    trials = {}
    with open(path, newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            for key in NUMERIC:
                row[key] = _num(row.get(key))
            row['collisions'] = int(row['collisions'] or 0)
            trials.setdefault(int(row['trial']), []).append(row)
    return trials


# ==============================================================================
# -- metrics -------------------------------------------------------------------
# ==============================================================================


def collision_times(rows):
    """Times (since the pre-alert) at which the collision counter went up."""
    times = []
    for previous, current in zip(rows, rows[1:]):
        if current['collisions'] > previous['collisions']:
            times.append(current['t_prealert_s'])
    return times


def _window_stats(rows, prefix=''):
    """Takeover-period metrics of the given frames."""
    stats = {}
    if not rows:
        return stats
    offsets = [r['lane_offset_m'] for r in rows if r['lane_offset_m'] is not None]
    speeds = [r['speed_kmh'] for r in rows]
    ttcs = [r['ttc_s'] for r in rows if r['ttc_s'] is not None]
    gaps = [r['lead_gap_m'] for r in rows if r['lead_gap_m'] is not None]
    stats[prefix + 'malat'] = max(abs(r['a_lat']) for r in rows)
    stats[prefix + 'malon'] = max(abs(r['a_lon']) for r in rows)
    stats[prefix + 'sdlp'] = statistics.pstdev(offsets) if len(offsets) > 1 else None
    stats[prefix + 'max_offset'] = max((abs(o) for o in offsets), default=None)
    stats[prefix + 'speed_min'] = min(speeds)
    stats[prefix + 'speed_mean'] = sum(speeds) / len(speeds)
    stats[prefix + 'min_ttc'] = min(ttcs, default=None)
    stats[prefix + 'min_gap'] = min(gaps, default=None)
    return stats


def analyze_trial(rows, window):
    frames = [r for r in rows if r['event'] != 'TRIAL_END']
    end = next((r for r in rows if r['event'] == 'TRIAL_END'), None)
    result = {'frames': len(frames), 'scenario': rows[0].get('scenario', ''), 'input': rows[0]['input'],
              'lane': rows[0]['lane'], 'vehicles': rows[0]['vehicles']}

    tor = next((r for r in frames if r['event'] == 'TOR'), None)
    takeover = next((r for r in frames if r['event'].startswith('TAKEOVER_')), None)
    result['takeover_type'] = takeover['event'][len('TAKEOVER_'):].lower() if takeover else None
    result['tor_at'] = tor['t_prealert_s'] if tor else None
    result['takeover_at'] = takeover['t_prealert_s'] if takeover else None
    result['tot'] = takeover['t_prealert_s'] if takeover else None
    result['tor_reaction'] = (takeover['t_prealert_s'] - tor['t_prealert_s']
                              if takeover and tor and result['takeover_type'] == 'after_tor' else None)
    result['first_input'] = end['first_input_s'] if end else None
    result['speed_prealert'] = frames[0]['speed_kmh'] if frames else None
    result['collisions_total'] = frames[-1]['collisions'] if frames else 0
    if not takeover:
        return result

    start = takeover['t_prealert_s']
    period = [r for r in frames if start <= r['t_prealert_s'] <= start + window]
    result['window_s'] = period[-1]['t_prealert_s'] - start if period else 0.0
    result['window_complete'] = result['window_s'] >= window - 0.1
    result['speed_takeover'] = takeover['speed_kmh']
    lanes = [r['lane_id'] for r in period]
    result['lane_changes'] = sum(1 for a, b in zip(lanes, lanes[1:]) if a != b)
    result['collisions'] = period[-1]['collisions'] - takeover['collisions']
    result['input_type'] = '+'.join(name for name, key in (('steer', 'driver_steer'),
                                                           ('throttle', 'driver_throttle'),
                                                           ('brake', 'driver_brake'))
                                    if takeover[key]) or None

    result.update(_window_stats(period))
    hits = collision_times(frames)
    clean = [r for r in period
             if not any(t - COLLISION_BEFORE <= r['t_prealert_s'] <= t + COLLISION_AFTER for t in hits)]
    result.update(_window_stats(clean, 'clean_'))
    result['clean_frames'] = len(clean)
    return result


# ==============================================================================
# -- output --------------------------------------------------------------------
# ==============================================================================


def _f(value, digits=2, width=0):
    text = '-' if value is None else ('%.*f' % (digits, value) if isinstance(value, float) else str(value))
    return text.rjust(width)


def print_trials(name, results):
    print('\n%s' % name)
    header = ('trial', 'type', 'TOT', 'TOR->', 'MAlat', 'MAlon', 'MAlat*', 'MAlon*', 'SDLP', 'LC', 'minTTC',
              'coll', 'window')
    print('  ' + ' '.join(h.rjust(9) for h in header))
    for trial, r in sorted(results.items()):
        window = '-' if 'window_s' not in r else '%.1fs%s' % (r['window_s'], '' if r['window_complete'] else ' !')
        cells = (trial, r['takeover_type'] or 'none', _f(r['tot'], 2), _f(r['tor_reaction'], 2),
                 _f(r.get('malat'), 2), _f(r.get('malon'), 2), _f(r.get('clean_malat'), 2),
                 _f(r.get('clean_malon'), 2), _f(r.get('sdlp'), 2), _f(r.get('lane_changes')),
                 _f(r.get('min_ttc'), 1), _f(r.get('collisions')), window)
        print('  ' + ' '.join(str(c).rjust(9) for c in cells))
    print('  TOT, TOR-> in s (TOR-> only for takeovers after the TOR); MAlat/MAlon in m/s2;'
          ' * = without frames around collisions;')
    print('  LC = lane changes; coll = collisions in the takeover period; window ! = ended early')
    for trial, r in sorted(results.items()):
        notes = []
        if r.get('collisions'):
            notes.append('%d collision(s): raw MAlat/MAlon are impact spikes, use the * values' % r['collisions'])
        if r.get('takeover_type') == 'forced':
            notes.append('forced takeover (no input): TOT is capped by the system')
        if r.get('window_complete') is False:
            notes.append('takeover period shorter than the window')
        if notes:
            print('  trial %s: %s' % (trial, '; '.join(notes)))


def print_groups(all_results):
    """Mean and SD of the main metrics per takeover type, over all trials."""
    groups = {}
    for results in all_results:
        for r in results.values():
            if r['takeover_type']:
                groups.setdefault(r['takeover_type'], []).append(r)
    if sum(len(g) for g in groups.values()) < 2:
        return
    print('\nBy takeover type (mean +- SD)')
    print('  ' + ' '.join(h.rjust(14) for h in ('type', 'n', 'TOT', 'MAlat*', 'MAlon*', 'SDLP')))
    for kind, group in sorted(groups.items()):
        cells = [kind, len(group)]
        for key in ('tot', 'clean_malat', 'clean_malon', 'sdlp'):
            values = [r[key] for r in group if r.get(key) is not None]
            if len(values) > 1:
                cells.append('%.2f +- %.2f' % (statistics.mean(values), statistics.stdev(values)))
            elif values:
                cells.append('%.2f' % values[0])
            else:
                cells.append('-')
        print('  ' + ' '.join(str(c).rjust(14) for c in cells))


EXPORT_COLUMNS = ['run', 'trial', 'scenario', 'input', 'lane', 'vehicles', 'takeover_type', 'tot', 'tor_reaction',
                  'first_input', 'input_type', 'speed_prealert', 'speed_takeover', 'window_s',
                  'window_complete', 'malat', 'malon', 'clean_malat', 'clean_malon', 'sdlp',
                  'max_offset', 'lane_changes', 'speed_min', 'speed_mean', 'min_ttc', 'min_gap',
                  'collisions', 'collisions_total']


def export_summary(path, name, results):
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPORT_COLUMNS, restval='', extrasaction='ignore')
        writer.writeheader()
        for trial, result in sorted(results.items()):
            row = dict(result, run=name, trial=trial)
            writer.writerow({k: ('' if v is None else (round(v, 4) if isinstance(v, float) else v))
                             for k, v in row.items()})
    print('Summary saved: %s' % path)


def _draw_trial(axes, rows, result, window, title, first_column):
    frames = [r for r in rows if r['event'] != 'TRIAL_END']
    t = [r['t_prealert_s'] for r in frames]
    hits = collision_times(frames)

    axes[0].plot(t, [r['speed_kmh'] for r in frames], color='#1f6f8b', label='ego')
    lead = [r['lead_speed_kmh'] for r in frames]
    if any(v is not None for v in lead):
        axes[0].plot(t, [float('nan') if v is None else v for v in lead], color='#999999',
                     linestyle='--', label='lead vehicle')
    axes[0].legend(loc='lower left', fontsize=8)

    axes[1].plot(t, [r['a_lon'] for r in frames], color='#d1495b', label='longitudinal', linewidth=1)
    axes[1].plot(t, [r['a_lat'] for r in frames], color='#edae49', label='lateral', linewidth=1)
    clean_peak = max([abs(result.get(k)) for k in ('clean_malat', 'clean_malon') if result.get(k) is not None]
                     or [5.0])
    limit = max(5.0, clean_peak * 1.3)
    axes[1].set_ylim(-limit, limit)
    axes[1].legend(loc='lower left', fontsize=8)
    if hits:
        axes[1].text(0.995, 0.93, 'collision spikes beyond the axis are clipped', transform=axes[1].transAxes,
                     ha='right', va='top', fontsize=8, color='#555555')

    offsets = [float('nan') if r['lane_offset_m'] is None else r['lane_offset_m'] for r in frames]
    axes[2].plot(t, offsets, color='#00798c')
    axes[2].axhline(0, color='#bbbbbb', linewidth=0.8)

    axes[3].plot(t, [r['driver_throttle'] for r in frames], color='#2e8b57', label='throttle')
    axes[3].plot(t, [r['driver_brake'] for r in frames], color='#c0392b', label='brake')
    axes[3].plot(t, [r['driver_steer'] for r in frames], color='#34495e', label='steer', linewidth=1)
    axes[3].set_xlabel('time since pre-alert (s)')
    axes[3].legend(loc='upper left', fontsize=8, ncol=3)

    if first_column:
        for axis, label in zip(axes, ('speed (km/h)', 'acceleration (m/s²)', 'lane offset (m)', 'driver input')):
            axis.set_ylabel(label)

    for axis in axes:
        if result['tor_at'] is not None:
            axis.axvline(result['tor_at'], color='#c0392b', linewidth=1.2)
        if result['takeover_at'] is not None:
            axis.axvline(result['takeover_at'], color='black', linestyle='--', linewidth=1.2)
            axis.axvspan(result['takeover_at'], result['takeover_at'] + window, color='#000000', alpha=0.05)
        for hit in hits:
            axis.axvline(hit, color='#e67e22', linewidth=0.8, alpha=0.7)
        axis.grid(alpha=0.25)

    top = axes[0].get_ylim()[1]
    if result['tor_at'] is not None:
        axes[0].text(result['tor_at'], top, ' TOR', color='#c0392b', va='top', fontsize=8)
    if result['takeover_at'] is not None:
        axes[0].text(result['takeover_at'], top, ' takeover', va='top', fontsize=8)
    if hits:
        axes[0].text(hits[0], top, ' collision', color='#e67e22', va='top', fontsize=8)
    if result.get('scenario'):
        title += ' (scenario %s)' % result['scenario']
    if result['tot'] is not None:
        title += '\nTOT %.2f s (%s)' % (result['tot'], result['takeover_type'])
    axes[0].set_title(title, fontsize=10)


def plot_trials(path, name, trials, results, window):
    """One column of four panels per trial, saved as one PNG."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print('matplotlib is not installed, no figure saved (pip install matplotlib)')
        return False

    numbers = sorted(trials)
    count = len(numbers)
    figure, axes = plt.subplots(4, count, figsize=(11 if count == 1 else 7.5 * count, 9),
                                sharex='col', squeeze=False)
    for column, number in enumerate(numbers):
        _draw_trial(axes[:, column], trials[number], results[number], window, 'trial %d' % number, column == 0)
    figure.suptitle(name, fontsize=12)
    figure.tight_layout()
    figure.savefig(path, dpi=100)
    plt.close(figure)
    print('Figure saved: %s' % path)
    return True


# ==============================================================================
# -- main() --------------------------------------------------------------------
# ==============================================================================


def report(run_dir, window=10.0, save=True):
    """Print the metrics of a run folder and write summary.csv and figure.png into it."""
    name = os.path.basename(os.path.normpath(run_dir))
    trials = load_trials(os.path.join(run_dir, 'raw.csv'))
    results = {trial: analyze_trial(rows, window) for trial, rows in trials.items()}
    print_trials(name, results)
    if save:
        export_summary(os.path.join(run_dir, 'summary.csv'), name, results)
        plot_trials(os.path.join(run_dir, 'figure.png'), name, trials, results, window)
    return results


def find_runs():
    """Run folders in Data, oldest first."""
    if not os.path.isdir(DATA_DIR):
        return []
    return [os.path.join(DATA_DIR, d) for d in sorted(os.listdir(DATA_DIR))
            if os.path.isfile(os.path.join(DATA_DIR, d, 'raw.csv'))]


def main():
    parser = argparse.ArgumentParser(description='Analyze takeover_experiment.py logs')
    parser.add_argument('runs', nargs='*', help='run folders or their raw.csv (default: the newest run in Data)')
    parser.add_argument('--all', action='store_true', help='analyze every run in Data')
    parser.add_argument('--window', type=float, default=10.0,
                        help='seconds after the takeover that count as the takeover period (default: 10)')
    parser.add_argument('--no-save', action='store_true', help='only print, do not write summary.csv and figure.png')
    args = parser.parse_args()

    if args.runs:
        runs = [os.path.dirname(r) if os.path.basename(r) == 'raw.csv' else r for r in args.runs]
    else:
        runs = find_runs()
        if not runs:
            sys.exit('No runs found in %s' % DATA_DIR)
        if not args.all:
            runs = runs[-1:]

    all_results = []
    for run in runs:
        if not os.path.isfile(os.path.join(run, 'raw.csv')):
            print('Skipping %s: no raw.csv in it' % run)
            continue
        all_results.append(report(run, args.window, save=not args.no_save))
    print_groups(all_results)


if __name__ == '__main__':
    main()
