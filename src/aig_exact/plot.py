"""Scatterplots for matched near-minimum benchmark instances."""
import math
import re
from itertools import combinations
from pathlib import Path

from .analysis import wall_seconds


METRICS = ('conflicts', 'runtime')


def index_samples(rows, metric, labels=None):
    if metric not in METRICS:
        raise ValueError(f'Unknown plot metric {metric!r}')
    by_label = {}
    for row in rows:
        task = row['task']
        label = task.get('label')
        if not label or (labels is not None and label not in labels):
            continue
        minimum = task.get('minimum')
        if minimum is not None and task['k'] - minimum not in (-1, 0):
            continue
        model = task.get('options', {}).get('model', 'aig')
        key = model, task['n'], int(task['hex'], 16), task['k']
        if metric == 'conflicts':
            value = row.get('conflicts')
            if type(value) is not int or value < 0:
                value = None
        else:
            value = wall_seconds(row)
            if value is not None and (not math.isfinite(value) or value <= 0):
                value = None
        sample = (row['run_id'], row['status'], value, minimum)
        measurements = by_label.setdefault(label, {})
        if key in measurements and measurements[key] != sample:
            raise ValueError(f'Multiple measurements for {label} on {key}. Select one campaign.')
        measurements[key] = sample
    return by_label


def pair_samples(x, y):
    points = {'SAT': [], 'UNSAT': []}
    missing = len(x.keys() ^ y.keys())
    incomplete = 0
    for key in sorted(x.keys() & y.keys()):
        _, x_status, x_value, x_minimum = x[key]
        _, y_status, y_value, y_minimum = y[key]
        if x_status != y_status or x_status not in points or x_value is None or y_value is None:
            incomplete += 1
            continue
        # Older manifests omit the minimum and used SAT/UNSAT at k and k-1.
        implied_minimum = key[-1] + (x_status == 'UNSAT')
        if any(m is not None and m != implied_minimum for m in (x_minimum, y_minimum)):
            incomplete += 1
            continue
        points[x_status].append((x_value, y_value))
    return points, missing, incomplete


def paired_measurements(rows, x_label, y_label, metric='conflicts'):
    if x_label == y_label:
        raise ValueError('Choose two different configuration labels')
    samples = index_samples(rows, metric, {x_label, y_label})
    for label in (x_label, y_label):
        if label not in samples:
            raise ValueError(f'No benchmark results for label {label!r}. Use the manifest label.')
    return pair_samples(samples[x_label], samples[y_label])


def paired_times(rows, x_label, y_label):
    return paired_measurements(rows, x_label, y_label, 'runtime')


def draw_scatter(points, x_label, y_label, output, metric):
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
    except ImportError as exc:
        raise ImportError("Install plotting support with python -m pip install -e '.[plot]'") from exc

    values = [value for group in points.values() for point in group for value in point]
    if metric == 'conflicts':
        # Keep measured zeros visible and use logarithmic spacing for larger counts.
        scale = 'symlog'
        lo, hi = -0.15, max(1, max(values)) * 1.2
        scale_options = {'linthresh': 1}
        axis_label = 'Solver conflicts'
        title = 'Solver conflicts by configuration and gate budget'
        equality = 'Equal conflicts'
        comparison = 'Above diagonal: x fewer   |   Below diagonal: y fewer'
    else:
        scale = 'log'
        lo, hi = min(values) / 1.2, max(values) * 1.2
        scale_options = {}
        axis_label = 'Solver wall time (s)'
        title = 'Solver time by configuration and gate budget'
        equality = 'Equal time'
        comparison = 'Above diagonal: x faster   |   Below diagonal: y faster'

    fig = Figure(figsize=(7.4, 7.4), layout='constrained')
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    ax.set_xscale(scale, **scale_options)
    ax.set_yscale(scale, **scale_options)
    ax.set(xlim=(lo, hi), ylim=(lo, hi),
           xlabel=f'{x_label}\n{axis_label}', ylabel=f'{y_label}\n{axis_label}')
    ax.set_aspect('equal', adjustable='box')
    ax.set_axisbelow(True)
    ax.grid(alpha=0.22)
    start = max(0, lo)
    ax.plot([start, hi], [start, hi], color='#555555', linestyle='--', linewidth=1.2, label=equality)
    for status, budget, color, marker in (
        ('SAT', 'k (SAT)', '#1965a7', 'o'),
        ('UNSAT', 'k−1 (UNSAT)', '#c85400', '^'),
    ):
        group = points[status]
        if group:
            x, y = zip(*group)
            ax.scatter(x, y, s=32, color=color, marker=marker, alpha=0.73, edgecolors='none',
                       label=f'{budget} · {len(group)} pairs', zorder=3)

    fig.suptitle(title, fontsize=15, fontweight='semibold')
    ax.set_title(comparison, fontsize=10, pad=10)
    ax.legend(loc='upper left', fontsize=9)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=160)


def scatter(rows, x_label, y_label, output, metric='conflicts'):
    points, missing, incomplete = paired_measurements(rows, x_label, y_label, metric)
    if not any(points.values()):
        raise ValueError(f'No completed pairs with {metric} to plot '
                         f'({missing} unpaired, {incomplete} incomplete or mismatched)')
    output = Path(output)
    if output.suffix.lower() not in ('.png', '.svg', '.pdf'):
        raise ValueError('Plot filename must end in .png, .svg, or .pdf')

    draw_scatter(points, x_label, y_label, output, metric)
    better = 'fewer' if metric == 'conflicts' else 'faster'
    for status, budget in (('SAT', 'k (SAT)'), ('UNSAT', 'k−1 (UNSAT)')):
        group = points[status]
        above = sum(x < y for x, y in group)
        below = sum(y < x for x, y in group)
        print(f'{budget}: x {better} {above}, y {better} {below}, tied {len(group) - above - below}')
    print(f'Saved {output} ({missing} unpaired, {incomplete} incomplete or mismatched pairs excluded)')


def scatter_all(rows, output, metric='conflicts'):
    samples = index_samples(rows, metric)
    labels = sorted(samples)
    if len(labels) < 2:
        raise ValueError('Need benchmark results for at least two configurations')
    output = Path(output)
    slugs = {label: re.sub(r'[^A-Za-z0-9_-]+', '-', label).strip('-_')[:60] or 'config'
             for label in labels}
    total = math.comb(len(labels), 2)
    print(f'Comparing {len(labels)} configurations across {total:,} pairs using {metric}', flush=True)
    written = 0
    for number, (x_label, y_label) in enumerate(combinations(labels, 2), 1):
        points, _, _ = pair_samples(samples[x_label], samples[y_label])
        if any(points.values()):
            filename = f'{metric}-{number:05d}-{slugs[x_label]}-vs-{slugs[y_label]}.png'
            draw_scatter(points, x_label, y_label, output / filename, metric)
            written += 1
        if number % 100 == 0 and number < total:
            print(f'Compared {number:,}/{total:,} pairs ({written:,} plots saved)', flush=True)
    if not written:
        raise ValueError(f'No completed pairs with {metric} to plot')
    print(f'Saved {written:,} plots to {output}. '
          f'Skipped {total - written:,} comparisons with no completed pairs for {metric}.')
