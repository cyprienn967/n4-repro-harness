#!/usr/bin/env python3
"""Plot Boolean features, exact circuit sizes, and conflicts from analyze_n4.py."""
import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path
from urllib.parse import quote


FEATURE_LABELS = {
    "max_sensitivity": "Maximum sensitivity",
    "mean_sensitivity": "Mean sensitivity",
    "essential_variables": "Essential variables",
    "degree": "Algebraic degree",
    "stabilizer_size": "NPN stabilizer size",
    "input_only_stabilizer_size": "Input-only stabilizer size",
    "orbit_size": "NPN orbit size",
    "restriction_orbit_count": "Number of signed restriction orbits",
}
LOG_FEATURES = {"stabilizer_size", "input_only_stabilizer_size", "orbit_size"}
BUDGETS = {"k": ("k (SAT)", "#2166ac", "o"), "k-1": ("k−1 (UNSAT)", "#b35806", "^")}


def read_features(path):
    features = {}
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            row["restriction_orbit_count"] = len(row["restriction_orbits"])
            features[row["hex"]] = row
    if not features:
        raise ValueError(f"No function features in {path}")
    return features


def plot_features(series, outcome, title, output):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.ticker import MaxNLocator, ScalarFormatter

    figure = Figure(figsize=(13.2, 7.8), layout="constrained")
    FigureCanvasAgg(figure)
    panels = figure.subplots(2, 4, sharey=True)
    for ax, (feature, label) in zip(panels.flat, FEATURE_LABELS.items()):
        for name, rows, color, marker in series:
            points = Counter((row[feature], row[outcome]) for row in rows)
            if points:
                x, y = zip(*points)
                ax.scatter(x, y, s=[12 + 15 * math.sqrt(count) for count in points.values()],
                           c=color, marker=marker, alpha=0.72, linewidths=0.35,
                           edgecolors="white", label=f"{name} · n={len(rows)}", zorder=3)
        if feature in LOG_FEATURES:
            ax.set_xscale("log", base=2)
            ax.xaxis.set_major_formatter(ScalarFormatter())
        elif feature != "mean_sensitivity":
            ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_xlabel(label)
        ax.grid(alpha=0.24, zorder=0)

    if outcome == "conflicts":
        panels[0, 0].set_yscale("symlog", linthresh=1)
        ylabel = "Solver conflicts"
    else:
        panels[0, 0].yaxis.set_major_locator(MaxNLocator(integer=True))
        ylabel = "Minimum circuit size (gates)"
    for ax in panels[:, 0]:
        ax.set_ylabel(ylabel)
    handles, labels = panels[0, 0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="outside lower center", ncols=len(labels), frameon=False)
    figure.suptitle(title + "\nLarger markers represent more functions at the same coordinates.", fontsize=13)
    figure.savefig(output, dpi=160)


def plot_correlations(rows, output):
    from matplotlib import colormaps
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    by_budget = {budget: {} for budget in BUDGETS}
    for row in rows:
        if row["outcome"] == "conflicts" and row["budget"] in by_budget:
            by_budget[row["budget"]][row["configuration"], row["feature"]] = row
    labels = sorted({label for group in by_budget.values() for label, _ in group})
    if not labels:
        raise ValueError("No conflict correlations in correlations.csv")

    all_columns = {**FEATURE_LABELS, "minimum": "Minimum circuit size"}
    available = {feature for group in by_budget.values() for _, feature in group}
    columns = [feature for feature in all_columns if feature in available]
    if not columns:
        raise ValueError("No recognized features in correlations.csv")
    color_map = colormaps["RdBu_r"].with_extremes(bad="#dce2e8")
    for budget, group in by_budget.items():
        values = []
        for label in labels:
            scores = [group.get((label, feature), {}).get("spearman_rho") for feature in columns]
            values.append([float(score) if score else math.nan for score in scores])
        sizes = {label: row["n"] for (label, _), row in group.items()}
        figure = Figure(figsize=(11.5, max(4.2, 2.4 + 0.22 * len(labels))), layout="constrained")
        FigureCanvasAgg(figure)
        ax = figure.subplots()
        image = ax.imshow(values, vmin=-1, vmax=1, cmap=color_map,
                          aspect="auto", interpolation="nearest")
        ax.set_xticks(range(len(columns)), [all_columns[feature] for feature in columns],
                      rotation=30, ha="right", rotation_mode="anchor")
        ax.set_yticks(range(len(labels)),
                      [f"{label} (n={sizes.get(label, '0')})" for label in labels], fontsize=8)
        subtitle, _, _ = BUDGETS[budget]
        ax.set_title(f"Feature correlations with solver conflicts at {subtitle}\n"
                     "Gray cells indicate an unavailable correlation.", loc="left")
        figure.colorbar(image, ax=ax, shrink=0.75, label="Spearman rank correlation")
        figure.savefig(output / f"conflicts-spearman-{budget}.svg")


def read_conflicts(path, features, configurations):
    selected = {label: {budget: [] for budget in BUDGETS} for label in configurations}
    if not selected:
        return selected
    with path.open(newline="") as stream:
        for row in csv.DictReader(stream):
            label, budget = row["configuration"], row["budget"]
            if label in selected and budget in BUDGETS and row["used_for_stats"] == "True":
                function = row["hex"]
                if function not in features:
                    raise ValueError(f"No features for function {function} in the selected benchmark data")
                selected[label][budget].append(dict(features[function], conflicts=int(row["conflicts"])))
    for label, groups in selected.items():
        if not any(groups.values()):
            raise ValueError(f"No usable conflict counts for configuration {label!r}")
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, default=Path("results/n4/feature-analysis"),
                        help="Directory written by analyze_n4.py")
    parser.add_argument("--out", type=Path, help="Output directory (default: <analysis>/plots)")
    parser.add_argument("--configuration", action="append", default=[],
                        help="Also plot individual conflict counts for this label (repeatable)")
    args = parser.parse_args()
    output = args.out or args.analysis / "plots"
    try:
        features = read_features(args.analysis / "features.jsonl")
        selected = read_conflicts(args.analysis / "benchmarks-with-features.csv", features, args.configuration)
        with (args.analysis / "correlations.csv").open(newline="") as stream:
            correlations = list(csv.DictReader(stream))
        output.mkdir(parents=True, exist_ok=True)
        plot_features([("NPN representatives", list(features.values()), "#2166ac", "o")],
                      "minimum", "Function features and minimum circuit size",
                      output / "features-vs-minimum.png")
        plot_correlations(correlations, output)
        for label, groups in selected.items():
            series = [(name, groups[budget], color, marker)
                      for budget, (name, color, marker) in BUDGETS.items() if groups[budget]]
            plot_features(series, "conflicts", f"Function features and solver conflicts · {label}",
                          output / f"conflicts-vs-features-{quote(label, safe='-_')}.png")
    except ImportError:
        parser.exit(2, "Install plotting support with python -m pip install -e '.[plot]'\n")
    except (KeyError, ValueError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(f"Wrote feature plots to {output}")


if __name__ == "__main__":
    main()
