import argparse
import json
import math
from collections import deque
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from contextlib import closing
from dataclasses import asdict, fields
from functools import partial
from itertools import islice
from multiprocessing import get_context
from pathlib import Path
from . import boolean, circuit, solver, analysis
from .encode import Instance, Options
from .experiment import dump, digest, run_task, minimum_step


EXPECTED_CLASSES = {0: 1, 1: 2, 2: 4, 3: 14, 4: 222}


def tables(path):
    text = Path(path).read_text()
    if Path(path).suffix == '.json':
        values = json.loads(text)
        if isinstance(values, dict):
            values = values['functions']
        return [int(v['hex'] if isinstance(v, dict) else v, 16) for v in values]
    return [int(line.split('#')[0].strip(), 16) for line in text.splitlines() if line.split('#')[0].strip()]


def options(args):
    return Options(**{f.name: getattr(args, f.name) for f in fields(Options)})


def add_options(p):
    p.add_argument('--model', choices=['aig', 'paper'], default='aig',
                   help='aig counts AND gates; paper counts arbitrary two-input operators')
    p.add_argument('--symmetries', default='', help='Paper Section III-D letters, e.g. NARCOS or NARCS')
    p.add_argument('--encoding', choices=['ssv', 'msv', 'ditt'], default='ssv')
    p.add_argument('--cardinality', choices=['sequential', 'pairwise'], default='sequential')
    p.add_argument('--fanin-order', action=argparse.BooleanOptionalAction, default=True)
    for flag in ('no-trivial', 'no-duplicates', 'all-used', 'target-symmetry'):
        p.add_argument('--' + flag, action='store_true')


def add_solver(p):
    p.add_argument('--backend', choices=['cadical', 'external'], default='cadical',
                   help='CaDiCaL 3+ (default) or a custom external solver')
    p.add_argument('--solver-argv', type=json.loads, help='Override solver argv as JSON; placeholders {cnf}, {proof}')
    p.add_argument('--timeout', type=positive_seconds, help='Solver time limit per instance in seconds')
    p.add_argument('--resume', action='store_true')


def positive_seconds(value):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError('Expected a positive, finite number of seconds')
    return seconds


def task_from(args, k=None):
    task = dict(n=args.n, hex=boolean.hex_tt(args.n, int(args.hex, 16)),
                k=args.k if k is None else k, options=asdict(options(args)), backend=args.backend)
    if args.timeout is not None:
        task['timeout'] = args.timeout
    if args.solver_argv is not None:
        task['solver_argv'] = args.solver_argv
    return task


def half_members(functions, half):
    return set(sorted(set(functions))[half - 1::2])


def minimum_rows(values, search, workers, max_gates):
    """Queue one budget per function, returning completed functions immediately."""
    if not values:
        return

    pool = ProcessPoolExecutor(max_workers=min(workers, len(values)),
                               mp_context=get_context('spawn'))
    queued = deque((index, 0) for index in range(len(values)))
    runs = [[] for _ in values]
    pending = {}
    try:
        while queued or pending:
            while queued and len(pending) < workers:
                index, k = queued.popleft()
                pending[pool.submit(search, f=values[index], k=k)] = (index, k)
            done, _ = wait(pending, timeout=30, return_when=FIRST_COMPLETED)
            if not done:
                active = ', '.join(f'{values[i]:x}@k={k}' for i, k in pending.values())
                print(f'Active: {active}; queued checks: {len(queued)}', flush=True)
            for future in done:
                index, k = pending.pop(future)
                row = future.result()
                runs[index].extend(row['runs'])
                if row['status'] == 'CONTINUE' and k < max_gates:
                    queued.append((index, k + 1))
                    continue
                if row['status'] == 'CONTINUE':
                    row['status'] = 'ABOVE_LIMIT'
                yield index, dict(row, runs=runs[index])
    finally:
        pool.shutdown(cancel_futures=True)


def run_rows(tasks, out, resume, workers):
    if workers == 1:
        for index, task in tasks:
            yield index, run_task(task, out, resume)
        return

    queued = iter(tasks)
    pending = {}
    with ProcessPoolExecutor(max_workers=workers, mp_context=get_context('spawn')) as pool:
        while True:
            for index, task in islice(queued, workers - len(pending)):
                pending[pool.submit(run_task, task, out, resume)] = (index, task)
            if not pending:
                return
            completed, _ = wait(pending, timeout=30, return_when=FIRST_COMPLETED)
            if not completed:
                active = ', '.join(f'{task["hex"]}@k={task["k"]}' for _, task in pending.values())
                print(f'Active benchmark checks: {active}', flush=True)
            for future in completed:
                index, _ = pending.pop(future)
                yield index, future.result()


def run_manifest(args):
    if args.workers < 1:
        raise ValueError('--workers must be at least 1')
    if args.shards < 1 or not 0 <= args.shard_index < args.shards:
        raise ValueError('Require 0 <= shard-index < shards')
    if args.half and args.shards != 1:
        raise ValueError('Use --half or --shards, one at a time')

    tasks = [(i, json.loads(line)) for i, line in enumerate(args.manifest.read_text().splitlines())
             if line.strip() and i % args.shards == args.shard_index]
    suffix = f'-shard-{args.shard_index}-of-{args.shards}' if args.shards > 1 else ''
    if args.half:
        def function_key(task):
            return task['n'], int(task['hex'], 16)
        members = half_members((function_key(task) for _, task in tasks), args.half)
        tasks = [(i, task) for i, task in tasks if function_key(task) in members]
        suffix = f'-half-{args.half}'

    # Check each solver command before starting the worker pool.
    checked = set()
    for _, task in tasks:
        backend, argv = task.get('backend', 'cadical'), task.get('solver_argv')
        key = (backend, json.dumps(argv))
        if key not in checked:
            solver.prepare(backend, argv)
            checked.add(key)
        if args.timeout is not None:
            task['timeout'] = args.timeout

    args.out.mkdir(parents=True, exist_ok=True)
    retry_path = args.out / f'timed-out{suffix}.jsonl'
    print(f'Running {len(tasks)} tasks with up to {args.workers} workers', flush=True)
    failed = False
    with retry_path.open('w') as retry, closing(run_rows(tasks, args.out, args.resume, args.workers)) as completed:
        for index, row in completed:
            task = row['task']
            status = row['status']
            label = task.get('label') or row['instance']['options']['encoding']
            seconds = analysis.wall_seconds(row)
            time_str = f'{seconds:.3f}s' if seconds is not None else 'N/A'
            conflicts = row.get('conflicts')
            conflicts_str = f'{conflicts:,}' if conflicts is not None else 'N/A'
            print(f'{index:5d} | f=0x{task["hex"]:<4} | k={task["k"]:<2} | '
                  f'{label:<24} | {status:<7} | time={time_str:<10} | conflicts={conflicts_str}', flush=True)
            if status == 'TIMEOUT':
                retry.write(json.dumps(task, sort_keys=True) + '\n')
                retry.flush()
            if 'error' in row:
                print(f'{row["error"]} ({row["directory"]})', flush=True)
            failed |= status not in ('SAT', 'UNSAT')
    if failed:
        raise RuntimeError(f'Some tasks ended incomplete. Timed-out jobs saved to {retry_path}')


def main():
    p = argparse.ArgumentParser(description='Exact AND/complemented-edge circuits; no experiment runs implicitly.')
    sub = p.add_subparsers(dest='command', required=True)
    npn = sub.add_parser('npn', help='Generate a complete NPN representative set (n <= 4)')
    npn.add_argument('-n', type=int, default=4)
    npn.add_argument('--out', type=Path, required=True)
    feat = sub.add_parser('features', help='Boolean and exact NPN stabilizer features')
    feat.add_argument('-n', type=int, default=4)
    source = feat.add_mutually_exclusive_group(required=True)
    source.add_argument('--hex')
    source.add_argument('--functions', type=Path)
    feat.add_argument('--stabilizer-elements', action='store_true')
    feat.add_argument('--cofactor-minima', type=Path, help='EXACT reproduction JSON for n-1')
    feat.add_argument('--out', type=Path, required=True)
    for cmd in ('emit', 'solve', 'minimum'):
        x = sub.add_parser(cmd)
        x.add_argument('-n', type=int, default=4)
        x.add_argument('--hex', required=True)
        if cmd == 'minimum':
            x.add_argument('--max-gates', type=int, default=10)
        else:
            x.add_argument('-k', type=int, required=True)
        x.add_argument('--out', type=Path, required=True)
        add_options(x)
        if cmd != 'emit':
            add_solver(x)
    rep = sub.add_parser('reproduce', help='Find every minimum, then check full coverage and worst-case size')
    rep.add_argument('-n', type=int, default=4)
    rep.add_argument('--functions', type=Path, required=True)
    rep.add_argument('--max-gates', type=int, default=10)
    rep.add_argument('--expect-max', type=int)
    rep.add_argument('--workers', type=int, default=1,
                     help='Number of parallel truth-table searches (default: 1)')
    rep.add_argument('--allow-subset', action='store_true')
    rep.add_argument('--half', type=int, choices=(1, 2), help='Search one half of the supplied functions')
    rep.add_argument('--out', type=Path, required=True)
    add_options(rep)
    add_solver(rep)
    rep.set_defaults(timeout=300)
    manifest = sub.add_parser('manifest', help='Materialize a matrix without running it')
    manifest.add_argument('--minima', type=Path, required=True)
    manifest.add_argument('--config', type=Path, required=True)
    manifest.add_argument('--out', type=Path, required=True)
    run = sub.add_parser('run', help='Run independent JSONL manifest rows, optionally sharded')
    run.add_argument('--manifest', type=Path, required=True)
    run.add_argument('--out', type=Path, required=True)
    run.add_argument('--resume', action='store_true')
    run.add_argument('--workers', type=int, default=1, help='Number of concurrent solver calls')
    run.add_argument('--timeout', type=positive_seconds, help='Override the per-task solver time limit')
    run.add_argument('--half', type=int, choices=(1, 2), help='Run every task for one half of a full manifest')
    run.add_argument('--shard-index', type=int, default=0)
    run.add_argument('--shards', type=int, default=1)
    verify = sub.add_parser('verify', help='Simulate a witness independently')
    verify.add_argument('witness', type=Path)
    verify.add_argument('--hex', required=True)
    inspect = sub.add_parser('inspect', help='Circuit depth, fanouts, restriction losses and optional automorphisms')
    inspect.add_argument('witness', type=Path)
    inspect.add_argument('--automorphisms', action='store_true')
    inspect.add_argument('--out', type=Path, required=True)
    check = sub.add_parser('check-proof', help='Run drat-trim on an UNSAT artifact directory')
    check.add_argument('directory', type=Path)
    check.add_argument('--checker', default='drat-trim')
    check.add_argument('--timeout', type=float)
    check.add_argument('--lrat', action='store_true')
    aggregate = sub.add_parser('aggregate')
    aggregate.add_argument('--runs', type=Path, nargs='+', required=True)
    aggregate.add_argument('--out', type=Path, required=True)
    aggregate.add_argument('--parquet', action='store_true')
    plot = sub.add_parser('plot', help='Plot conflicts or runtime for matched benchmark configurations')
    plot.add_argument('--runs', type=Path, nargs='+', required=True)
    plot_mode = plot.add_mutually_exclusive_group(required=True)
    plot_mode.add_argument('--x', help='Manifest configuration label for the x-axis')
    plot_mode.add_argument('--all', action='store_true', help='Plot every pair of configuration labels')
    plot.add_argument('--y', help='Manifest configuration label for the y-axis')
    plot.add_argument('--metric', choices=('conflicts', 'runtime'), default='conflicts',
                      help='Measurement to compare (default: conflicts)')
    plot.add_argument('--out', type=Path, required=True, help='Plot file, or output directory with --all')
    args = p.parse_args()
    try:
        dispatch(args)
    except (ValueError, OSError, RuntimeError, ImportError) as exc:
        p.exit(2, f'error: {exc}\n')


def dispatch(a):
    cmd = a.command
    if cmd == 'npn':
        values = list(boolean.representatives(a.n))
        if len(values) != EXPECTED_CLASSES[a.n]:
            raise ValueError('NPN class count disagrees with expected reference')
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(''.join(boolean.hex_tt(a.n, f) + '\n' for f in values))
        dump(a.out.with_suffix('.meta.json'), dict(n=a.n, count=len(values), sha256=digest(a.out),
             convention='bit t = f(x0,...), xi=(t>>i)&1; minimum integer in each NPN orbit'))
        print(f'Wrote {len(values)} NPN representatives to {a.out}')
    elif cmd == 'features':
        values = tables(a.functions) if a.functions else [int(a.hex, 16)]
        minima = None
        if a.cofactor_minima:
            records = json.loads(a.cofactor_minima.read_text())['functions']
            models = {row.get('model', 'aig') for row in records}
            if len(models) != 1:
                raise ValueError('Cofactor minima must use one circuit model')
            cofactor_model = models.pop()
            minima = {}
            for row in records:
                if row['n'] != a.n - 1 or row['status'] != 'EXACT':
                    raise ValueError('Cofactor minima must all be EXACT at dimension n-1')
                minima[boolean.canonical(a.n - 1, int(row['hex'], 16))] = row['minimum']
        a.out.parent.mkdir(parents=True, exist_ok=True)
        with a.out.open('w') as stream:
            for f in values:
                row = boolean.features(a.n, f, a.stabilizer_elements)
                if minima is not None:
                    for co in row['cofactors']:
                        key = int(co['npn'], 16)
                        if key not in minima:
                            raise ValueError('Cofactor class missing from minima file')
                        co['minimum'] = minima[key]
                        co['model'] = cofactor_model
                stream.write(json.dumps(row, sort_keys=True) + '\n')
        print(f'Wrote features for {len(values)} functions')
    elif cmd == 'emit':
        instance = Instance(a.n, int(a.hex, 16), a.k, options(a))
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / 'instance.cnf').write_text(instance.cnf.dimacs())
        dump(a.out / 'instance.json', instance.metadata())
        dump(a.out / 'variables.json', instance.cnf.names)
        print(json.dumps(instance.metadata(), indent=2))
    elif cmd == 'solve':
        row = run_task(task_from(a), a.out, a.resume)
        print(json.dumps(row, indent=2))
        if row['status'] not in ('SAT', 'UNSAT'):
            raise RuntimeError(f'Run ended with {row["status"]}')
    elif cmd in ('minimum', 'reproduce'):
        values = tables(a.functions) if cmd == 'reproduce' else [int(a.hex, 16)]
        workers = getattr(a, 'workers', 1)
        if workers < 1:
            raise ValueError('--workers must be at least 1')
        if a.max_gates < 0:
            raise ValueError('--max-gates must be nonnegative')
        for f in values:
            boolean.validate(a.n, f)
        coverage = False
        if cmd == 'reproduce' and not a.allow_subset:
            if a.n not in EXPECTED_CLASSES:
                raise ValueError('Full reproduction coverage supported only through n=4')
            classes = {boolean.canonical(a.n, f) for f in values}
            if len(classes) != len(values) or len(classes) != EXPECTED_CLASSES[a.n]:
                raise ValueError('Functions must cover every NPN class exactly once; use --allow-subset for pilot runs')
            coverage = True
        half = getattr(a, 'half', None)
        if half is not None:
            if a.expect_max is not None:
                raise ValueError('--expect-max requires a full reproduction. Remove it when running one half.')
            members = half_members(values, half)
            values = [f for f in values if f in members]
            coverage = False
            print(f'Half {half}: {len(values)} functions', flush=True)
        if workers > 1 and len(set(values)) != len(values):
            raise ValueError('Parallel reproduction requires distinct truth tables')
        a.out.mkdir(parents=True, exist_ok=True)
        report = dict(n=a.n, model=a.model, full_npn_coverage=coverage, functions=[], complete=False,
                      observed_maximum=None, claim_verified=False)
        if half is not None:
            report['half'] = half
        # Validate solver arguments before the first task.
        a.hex = boolean.hex_tt(a.n, values[0]) if values else '0'
        template = task_from(a, k=0)
        solver.prepare(template['backend'], template.get('solver_argv'))
        search = partial(minimum_step, n=a.n, root=a.out / 'runs',
                         options=options(a), backend=template['backend'],
                         solver_argv=template.get('solver_argv'),
                         timeout=template.get('timeout'), resume=a.resume,
                         progress=cmd == 'reproduce')
        rows = [None] * len(values)
        timed_out = {}
        if cmd == 'reproduce':
            dump(a.out / 'timed-out.json', dict(n=a.n, functions=[]))
        with closing(minimum_rows(values, search, workers, a.max_gates)) as completed:
            for index, row in completed:
                rows[index] = row
                report['functions'] = [r for r in rows if r is not None]
                dump(a.out / 'minima.json', report)
                if cmd == 'reproduce' and row['runs'] and row['runs'][-1]['status'] == 'TIMEOUT':
                    k = row['runs'][-1]['k']
                    timed_out[index] = dict(hex=row['hex'], k=k)
                    dump(a.out / 'timed-out.json',
                         dict(n=a.n, functions=[timed_out[i] for i in sorted(timed_out)]))
                    print(f'{row["hex"]}: TIMEOUT at k={k}', flush=True)
                else:
                    print(f'{row["hex"]}: {row["status"]}, minimum={row["minimum"]}', flush=True)
                    if 'error' in row:
                        print(row['error'], flush=True)
        report['complete'] = bool(values) and all(r['status'] == 'EXACT' for r in report['functions'])
        report['observed_maximum'] = max((r['minimum'] for r in report['functions'] if r['status'] == 'EXACT'), default=None)
        expected = getattr(a, 'expect_max', None)
        report['claim_verified'] = coverage and report['complete'] and (expected is None or expected == report['observed_maximum'])
        report['expected_maximum'] = expected
        dump(a.out / 'minima.json', report)
        if not report['complete'] or (expected is not None and (not coverage or report['observed_maximum'] != expected)):
            raise RuntimeError('Reproduction incomplete or expected maximum not established; see minima.json')
    elif cmd == 'manifest':
        minima = json.loads(a.minima.read_text())['functions']
        config = json.loads(a.config.read_text())
        variants = [(v['name'], Options(**v.get('options', {}))) for v in config['variants']]
        tasks = []
        for row in minima:
            if row['status'] != 'EXACT':
                raise ValueError('Manifest requires EXACT minima; unresolved functions cannot be silently omitted')
            for delta in config.get('deltas', [-1, 0]):
                k = row['minimum'] + delta
                if k < 0:
                    continue
                for name, opt in variants:
                    if opt.model != row.get('model', 'aig'):
                        raise ValueError('Manifest model differs from minima model; synthesize minima in the same model first')
                    for backend in config['solvers']:
                        task = dict(n=row['n'], hex=row['hex'], k=k, minimum=row['minimum'],
                                    options=asdict(opt), **backend)
                        task['label'] = name + ':' + backend.get('label', 'solver')
                        tasks.append(task)
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(''.join(json.dumps(t, sort_keys=True) + '\n' for t in tasks))
        print(f'Wrote {len(tasks)} tasks; no solvers launched')
    elif cmd == 'run':
        run_manifest(a)
    elif cmd == 'verify':
        witness = json.loads(a.witness.read_text())
        actual = circuit.simulate(witness)
        if actual != int(a.hex, 16):
            raise ValueError(f'Witness mismatch: computed {boolean.hex_tt(witness["n"], actual)}')
        print('VERIFIED: every truth-table assignment matches')
    elif cmd == 'inspect':
        dump(a.out, circuit.analyze(json.loads(a.witness.read_text()), a.automorphisms))
    elif cmd == 'check-proof':
        result_path = a.directory / 'result.json'
        row = json.loads(result_path.read_text())
        if row['status'] != 'UNSAT':
            raise ValueError('Proof checking requires an UNSAT result')
        result = solver.check_proof(a.directory, a.checker, a.timeout, a.lrat)
        result.update(cnf_sha256=digest(a.directory / 'instance.cnf'), proof_sha256=digest(a.directory / 'proof.drat'))
        dump(a.directory / 'proof-check.json', result)
        print(json.dumps(result, indent=2))
        if result['status'] != 'VERIFIED':
            raise RuntimeError('Proof not verified')
    elif cmd == 'aggregate':
        a.out.mkdir(parents=True, exist_ok=True)
        raw = list(analysis.load_results(*a.runs))
        rows = [analysis.flatten(r) for r in raw]
        analysis.write_csv(a.out / 'runs.csv', rows)
        dump(a.out / 'summary.json', analysis.summarize(rows))
        (a.out / 'runs.jsonl').write_text(''.join(json.dumps(r, sort_keys=True) + '\n' for r in raw))
        if a.parquet:
            import pandas as pd
            frame = pd.DataFrame(rows)
            frame['solver'] = frame['solver'].map(str)
            frame.to_parquet(a.out / 'runs.parquet', index=False)
        print(f'Aggregated {len(rows)} runs')
    elif cmd == 'plot':
        from .plot import scatter, scatter_all
        rows = analysis.load_results(*a.runs)
        if a.all:
            if a.y is not None:
                raise ValueError('--all selects the labels automatically. Remove --y.')
            scatter_all(rows, a.out, a.metric)
        else:
            if a.y is None:
                raise ValueError('--x requires --y')
            scatter(rows, a.x, a.y, a.out, a.metric)
