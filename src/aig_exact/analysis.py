"""Result aggregation preserves SAT/UNSAT and incomplete outcomes separately."""
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from .experiment import digest


def load_results(*roots):
    paths = {path.resolve() for root in roots for path in Path(root).rglob('result.json')}
    for path in sorted(paths):
        row = json.loads(path.read_text())
        row['record_path'] = str(path.resolve())
        check = path.parent / 'proof-check.json'
        if check.exists():
            checked = json.loads(check.read_text())
            row['proof_verified'] = (checked.get('status') == 'VERIFIED' and
                                     checked.get('cnf_sha256') == digest(path.parent / 'instance.cnf') and
                                     checked.get('proof_sha256') == digest(path.parent / 'proof.drat'))
            row['proof_check_seconds'] = checked.get('wall_seconds')
        yield row


def wall_seconds(row):
    seconds = row.get('solve_wall_seconds')
    return None if seconds is None else seconds + (row.get('solver_init_wall_seconds') or 0)


def flatten(row):
    task, inst = row['task'], row['instance']
    backend = task.get('backend', 'pysat')  # Older result files defaulted to PySAT.
    result = dict(run_id=row['run_id'], n=task['n'], hex=task['hex'], k=task['k'],
                  minimum=task.get('minimum'), expected_status=row.get('expected_status'),
                  model=inst['options'].get('model', 'aig'),
                  encoding=inst['options']['encoding'],
                  options=json.dumps(inst['options'], sort_keys=True),
                  backend=backend,
                  solver=task.get('solver', task.get('solver_argv', 'cadical' if backend == 'cadical' else None)),
                  label=task.get('label'), status=row['status'],
                  source_sha256=row['provenance']['source_sha256'],
                  solver_binary_sha256=row['provenance'].get('solver_binary_sha256'),
                  cadical_version=row['provenance'].get('cadical_version'),
                  python_sat_version=row['provenance'].get('python_sat_version'))
    for key in ('encode_wall_seconds', 'solve_wall_seconds', 'solver_init_wall_seconds',
                'solver_cpu_seconds', 'solver_peak_memory_mb', 'decisions', 'conflicts',
                'propagations', 'restarts', 'proof_bytes', 'proof_verified', 'proof_check_seconds'):
        result[key] = row.get(key)
    for key in ('variables', 'clauses', 'literals', 'query'):
        result[key] = inst[key]
    result['directory'] = row['directory']
    return result


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        key = (row['encoding'], row['options'], row['backend'], str(row['solver']),
               row['source_sha256'], row['solver_binary_sha256'], row['python_sat_version'])
        groups[key].append(row)
    summaries = []
    for key, group in groups.items():
        identity = dict(zip(('encoding', 'options', 'backend', 'solver', 'source_sha256',
                             'solver_binary_sha256', 'python_sat_version'), key))
        for status in ('SAT', 'UNSAT', 'TIMEOUT', 'UNKNOWN', 'ERROR'):
            subset = [r for r in group if r['status'] == status]
            if not subset:
                continue
            times = sorted(r['solve_wall_seconds'] for r in subset if r['solve_wall_seconds'] is not None)
            item = dict(identity, status=status, count=len(subset),
                        timeout_fraction=sum(r['status'] == 'TIMEOUT' for r in group) / len(group))
            if times:
                item.update(median_seconds=statistics.median(times), max_seconds=max(times),
                            geometric_mean_seconds=math.exp(sum(math.log(max(t, 1e-9)) for t in times) / len(times)),
                            p95_seconds=times[max(0, math.ceil(.95 * len(times)) - 1)])
            summaries.append(item)
    return summaries


def write_csv(path, rows):
    rows = list(rows)
    if not rows:
        raise ValueError('No results to export')
    with Path(path).open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
