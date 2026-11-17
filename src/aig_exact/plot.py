"""Timing scatterplots for matched near-minimum benchmark instances."""
import math
from pathlib import Path

from .analysis import wall_seconds


def paired_times(rows, x_label, y_label):
    if x_label == y_label:
        raise ValueError('Choose two different configuration labels')
    by_label = {x_label: {}, y_label: {}}
    for row in rows:
        task = row['task']
        label = task.get('label')
        if label not in by_label:
            continue
        minimum = task.get('minimum')
        if minimum is not None and task['k'] - minimum not in (-1, 0):
            continue
        model = task.get('options', {}).get('model', 'aig')
        key = model, task['n'], int(task['hex'], 16), task['k']
        sample = (row['run_id'], row['status'], wall_seconds(row), minimum)
        if key in by_label[label] and by_label[label][key] != sample:
            raise ValueError(f'Multiple measurements for {label} on {key}. Select one campaign.')
        by_label[label][key] = sample

    x, y = by_label[x_label], by_label[y_label]
    for label, samples in by_label.items():
        if not samples:
            raise ValueError(f'No benchmark results for label {label!r}. Use the manifest label.')
    times = {'SAT': [], 'UNSAT': []}
    missing = len(x.keys() ^ y.keys())
    incomplete = 0
    for key in sorted(x.keys() & y.keys()):
        _, x_status, x_time, x_minimum = x[key]
        _, y_status, y_time, y_minimum = y[key]
        if x_status != y_status or x_status not in times or any(
            t is None or not math.isfinite(t) or t <= 0 for t in (x_time, y_time)
        ):
            incomplete += 1
            continue
        # Older manifests omit the minimum and used SAT/UNSAT at k and k-1.
        implied_minimum = key[-1] + (x_status == 'UNSAT')
        if any(m is not None and m != implied_minimum for m in (x_minimum, y_minimum)):
            incomplete += 1
            continue
        times[x_status].append((x_time, y_time))
    return times, missing, incomplete


def scatter(rows, x_label, y_label, output):
    times, missing, incomplete = paired_times(rows, x_label, y_label)
    points = [point for group in times.values() for point in group]
    if not points:
        raise ValueError(f'No completed pairs to plot ({missing} unpaired, {incomplete} incomplete or mismatched)')
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
    except ImportError as exc:
        raise ImportError("Install plotting support with python -m pip install -e '.[plot]'") from exc

    output = Path(output)
    if output.suffix.lower() not in ('.png', '.svg', '.pdf'):
        raise ValueError('Plot filename must end in .png, .svg, or .pdf')
    lo = min(min(point) for point in points) / 1.2
    hi = max(max(point) for point in points) * 1.2
    fig = Figure(figsize=(7.4, 7.4), layout='constrained')
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    ax.set(xscale='log', yscale='log', xlim=(lo, hi), ylim=(lo, hi),
           xlabel=f'{x_label}\nSolver wall time (s)',
           ylabel=f'{y_label}\nSolver wall time (s)')
    ax.set_aspect('equal', adjustable='box')
    ax.set_axisbelow(True)
    ax.grid(alpha=0.22)
    ax.plot([lo, hi], [lo, hi], color='#555555', linestyle='--', linewidth=1.2, label='Equal time')
    for status, budget, color, marker in (
        ('SAT', 'k (SAT)', '#1965a7', 'o'),
        ('UNSAT', 'k−1 (UNSAT)', '#c85400', '^'),
    ):
        group = times[status]
        if group:
            x, y = zip(*group)
            ax.scatter(x, y, s=32, color=color, marker=marker, alpha=0.73, edgecolors='none',
                       label=f'{budget} · {len(group)} pairs', zorder=3)
        above = sum(x < y for x, y in group)
        below = sum(y < x for x, y in group)
        print(f'{budget}: x faster {above}, y faster {below}, tied {len(group) - above - below}')

    fig.suptitle('Solver time by configuration and gate budget', fontsize=15, fontweight='semibold')
    ax.set_title('Above diagonal: x faster   |   Below diagonal: y faster', fontsize=10, pad=10)
    ax.legend(loc='upper left', fontsize=9)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=160)
    print(f'Saved {output} ({missing} unpaired, {incomplete} incomplete or mismatched pairs excluded)')
