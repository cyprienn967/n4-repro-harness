#!/usr/bin/env python3
"""Join saved n=4 minima and benchmarks to Boolean-function features."""
import argparse
import json
import statistics
from collections import defaultdict
from itertools import groupby
from pathlib import Path

from aig_exact import analysis, boolean


FEATURES = (
    "max_sensitivity", "mean_sensitivity", "essential_variables", "degree",
    "stabilizer_size", "input_only_stabilizer_size", "orbit_size",
)
BUDGETS = {0: ("k", "SAT"), -1: ("k-1", "UNSAT")}


def read_minima(halves):
    minima = {}
    models = set()
    for half in halves:
        path = half / "minima.json"
        report = json.loads(path.read_text())
        if report.get("complete") is False or not report["functions"]:
            raise ValueError(f"{path} needs a completed minimum search")
        for row in report["functions"]:
            if row["n"] != 4 or row["status"] != "EXACT":
                raise ValueError(f"{path}: expected an exact n=4 minimum for {row['hex']}")
            models.add(row.get("model", report.get("model", "aig")))
            function = int(row["hex"], 16)
            minimum = row["minimum"]
            if type(minimum) is not int or minimum < 0:
                raise ValueError(f"{path}: invalid minimum for {row['hex']}")
            if function in minima and minima[function] != minimum:
                raise ValueError(f"{path}: conflicting minima for 0x{function:04x}")
            minima[function] = minimum
    if len(models) != 1:
        raise ValueError("Use minima from one circuit model")
    return minima, models.pop()


def read_benchmarks(halves, features, model):
    roots = [half / "benchmarks" for half in halves]
    for root in roots:
        if not root.is_dir():
            raise ValueError(f"Missing benchmark directory {root}")

    groups = defaultdict(dict)
    for row in analysis.load_results(*roots):
        task = row["task"]
        label = task.get("label")
        if not label:
            continue
        function = int(task["hex"], 16)
        if task["n"] != 4 or task.get("options", {}).get("model", "aig") != model or function not in features:
            raise ValueError(f"Benchmark {row['record_path']} does not match the n=4 minima")
        feature = features[function]
        minimum = feature["minimum"]
        if task.get("minimum", minimum) != minimum:
            raise ValueError(f"Benchmark {row['record_path']} records a different minimum")
        offset = task["k"] - minimum
        if offset not in BUDGETS:
            continue
        budget, expected_status = BUDGETS[offset]
        status = row["status"]
        conflicts = row.get("conflicts")
        has_count = type(conflicts) is int and conflicts >= 0
        joined = dict(run_id=row["run_id"], configuration=label, hex=feature["hex"],
                      model=model, minimum=minimum, budget=budget, gates=task["k"],
                      status=status, conflicts=conflicts, expected_status=expected_status,
                      used_for_stats=status == expected_status and has_count,
                      **{key: feature[key] for key in FEATURES})
        group = groups[label, offset]
        if function in group and group[function] != joined:
            raise ValueError(f"Multiple benchmark results for {label} on {feature['hex']} at {budget}")
        group[function] = joined
    if not groups:
        raise ValueError("No labeled benchmark results at k or k-1")
    return groups


def ranks(values):
    """One-based ranks with the mean rank assigned to ties."""
    result = [0.0] * len(values)
    start = 1
    for _, indices in groupby(sorted(range(len(values)), key=values.__getitem__), key=values.__getitem__):
        tied = list(indices)
        rank = start + (len(tied) - 1) / 2
        for index in tied:
            result[index] = rank
        start += len(tied)
    return result


def correlations(rows, outcome, predictors, **group):
    y = [row[outcome] for row in rows]
    y_ranks = ranks(y)
    for predictor in predictors:
        x = [row[predictor] for row in rows]
        pearson = spearman = None
        if len(set(x)) > 1 and len(set(y)) > 1:
            pearson = statistics.correlation(x, y)
            spearman = statistics.correlation(ranks(x), y_ranks)
        yield dict(outcome=outcome, **group, feature=predictor, n=len(y),
                   pearson_r=pearson, spearman_rho=spearman)


def run(results, output):
    halves = [results / "half-1", results / "half-2"]
    minima, model = read_minima(halves)
    features = {}
    for function, minimum in sorted(minima.items()):
        row = boolean.features(4, function, include_stabilizer=True)
        # Several stabilizer elements can map a restriction to the same member.
        row["restriction_orbits"] = [sorted(set(orbit)) for orbit in row["restriction_orbits"]]
        features[function] = dict(row, minimum=minimum, model=model,
                                  mean_sensitivity=statistics.mean(row["sensitivity"]))
    groups = read_benchmarks(halves, features, model)

    stats = list(correlations(list(features.values()), "minimum", FEATURES,
                              configuration="", budget="", eligible=len(features),
                              recorded=len(features), timeouts=0))
    eligible = {0: len(features), -1: sum(m > 0 for m in minima.values())}
    for label in sorted({label for label, _ in groups}):
        for offset, (budget, _) in BUDGETS.items():
            rows = list(groups.get((label, offset), {}).values())
            usable = [r for r in rows if r["used_for_stats"]]
            stats.extend(correlations(usable, "conflicts", (*FEATURES, "minimum"),
                                      configuration=label, budget=budget, eligible=eligible[offset],
                                      recorded=len(rows), timeouts=sum(r["status"] == "TIMEOUT" for r in rows)))

    output.mkdir(parents=True, exist_ok=True)
    with (output / "features.jsonl").open("w") as stream:
        for row in features.values():
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    joined = [row for key in sorted(groups) for row in groups[key].values()]
    analysis.write_csv(output / "benchmarks-with-features.csv", joined)
    analysis.write_csv(output / "correlations.csv", stats)
    count = sum(row["used_for_stats"] for row in joined)
    print(f"Wrote {len(features)} function records and {len(joined)} benchmark records to {output}")
    print(f"Conflict correlations used {count} records with the expected result and a recorded count")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path("results/n4"),
                        help="Directory containing half-1 and half-2 (default: results/n4)")
    parser.add_argument("--out", type=Path, help="Output directory (default: <results>/feature-analysis)")
    args = parser.parse_args()
    try:
        run(args.results, args.out or args.results / "feature-analysis")
    except (ValueError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()
