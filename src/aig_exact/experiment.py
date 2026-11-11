"""Deterministic per-task artifacts; no shared append-only writes between workers."""
import hashlib
import json
import math
import platform
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from . import __version__
from .boolean import hex_tt
from .encode import Instance, Options
from . import circuit, solver


def dump(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def provenance():
    root = Path(__file__).resolve().parent
    source_hash = hashlib.sha256()
    for path in sorted(root.glob('*.py')):
        source_hash.update(path.name.encode())
        source_hash.update(path.read_bytes())
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, stderr=subprocess.DEVNULL).decode().strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    return dict(version=__version__, source_sha256=source_hash.hexdigest(), git_commit=commit,
                python=sys.version, platform=platform.platform())


def run_task(task, root, resume=False, *, progress=False):
    allowed = {'n', 'hex', 'k', 'options', 'backend', 'solver', 'solver_argv', 'timeout', 'label'}
    if set(task) - allowed:
        raise ValueError(f'Unknown task fields: {set(task) - allowed}')
    task = dict(task)
    timeout = task.get('timeout')
    if timeout is not None and (not math.isfinite(timeout) or timeout <= 0):
        raise ValueError('timeout must be a positive, finite number of seconds')
    n, f, k = task['n'], int(task['hex'], 16), task['k']
    options = Options(**task.get('options', {}))
    prov = provenance()
    # Include binary bytes in cache identity, so a changed external executable
    # cannot accidentally reuse an earlier result.
    backend = task.get('backend', 'pysat')
    if backend not in ('pysat', 'external'):
        raise ValueError('backend must be pysat or external')
    if backend == 'pysat':
        import importlib.metadata
        prov['python_sat_version'] = importlib.metadata.version('python-sat')
    else:
        import shutil
        binary = shutil.which(task['solver_argv'][0])
        if binary is None:
            raise FileNotFoundError(task['solver_argv'][0])
        prov['solver_binary_sha256'] = digest(binary)
    # A definitive answer can be reused when only the time limit changes.
    identity = dict(task={key: value for key, value in task.items() if key != 'timeout'},
                    source=prov['source_sha256'],
                    solver_binary=prov.get('solver_binary_sha256'),
                    python_sat=prov.get('python_sat_version'))
    run_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
    directory = Path(root) / run_id
    directory.mkdir(parents=True, exist_ok=True)
    # Exclusive ownership prevents two workers corrupting one task directory.
    lock = directory / '.lock'
    try:
        descriptor = lock.open('x')
    except FileExistsError:
        raise RuntimeError(f'Task already running or stale lock: {lock}') from None
    try:
        descriptor.close()
        result_path = directory / 'result.json'
        if resume and result_path.exists():
            previous = json.loads(result_path.read_text())
            if previous['status'] in ('SAT', 'UNSAT') and all(
                (directory / name).exists() and digest(directory / name) == sha
                for name, sha in previous.get('artifact_sha256', {}).items()
            ):
                return previous
        elif result_path.exists():
            raise FileExistsError(f'{result_path} exists; use --resume or a new output directory')
        if progress:
            print(f'{task["hex"]}: starting k={k}', flush=True)
        # Erase only stale outputs owned by this task before a retry.
        for name in ('result.json', 'witness.json', 'witness.aag', 'proof.drat', 'proof.lrat', 'proof-check.json', 'proof-check.log', 'model.json', 'solver.stdout', 'solver.stderr'):
            (directory / name).unlink(missing_ok=True)
        dump(directory / 'task.json', task)
        started = time.perf_counter()
        instance = Instance(n, f, k, options)
        encode_seconds = time.perf_counter() - started
        (directory / 'instance.cnf').write_text(instance.cnf.dimacs())
        dump(directory / 'variables.json', instance.cnf.names)
        dump(directory / 'instance.json', instance.metadata())
        result = dict(run_id=run_id, task=task, provenance=prov, directory=str(directory.resolve()),
                      encode_wall_seconds=encode_seconds, instance=instance.metadata(),
                      timestamp_utc=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat())
        try:
            solved = (solver.embedded(instance, task.get('solver', 'cadical195'), directory, timeout)
                      if backend == 'pysat' else
                      solver.external(task['solver_argv'], directory, timeout))
            model = solved.pop('model')
            dump(directory / 'model.json', model)
            result.update(solved)
            if result['status'] == 'SAT':
                witness = instance.decode(model)
                if circuit.simulate(witness) != f:
                    raise ValueError('Independent simulation rejected SAT witness')
                witness = circuit.compact(witness)
                dump(directory / 'witness.json', witness)
                (directory / 'witness.aag').write_text(circuit.aag(witness))
                result['witness_verified'] = True
                result['circuit'] = circuit.analyze(witness)
        except Exception as exc:
            result.update(status='ERROR', error=f'{type(exc).__name__}: {exc}')
        proof = directory / 'proof.drat'
        result['proof_available'] = proof.exists()
        result['proof_bytes'] = proof.stat().st_size if proof.exists() else None
        result['proof_verified'] = False
        files = ['task.json', 'instance.cnf', 'instance.json', 'variables.json', 'model.json',
                 'solver.stdout', 'solver.stderr', 'witness.json', 'witness.aag', 'proof.drat']
        result['artifact_sha256'] = {name: digest(directory / name) for name in files if (directory / name).exists()}
        dump(result_path, result)
        return result
    finally:
        lock.unlink(missing_ok=True)


def minimum_step(n, f, k, root, options, backend='pysat', solver_name='cadical195',
                 solver_argv=None, timeout=None, resume=False, *, progress=False):
    """Solve one gate count and return a minimum-search step."""
    task = dict(n=n, hex=hex_tt(n, f), k=k, options=asdict(options), backend=backend)
    if backend == 'pysat':
        task['solver'] = solver_name
    else:
        task['solver_argv'] = solver_argv
    if timeout is not None:
        task['timeout'] = timeout
    try:
        record = run_task(task, root, resume, progress=progress)
    except (ValueError, OSError, RuntimeError, ImportError) as exc:
        return dict(n=n, hex=hex_tt(n, f), status='INCOMPLETE', minimum=None,
                    runs=[dict(k=k, status='ERROR', run_id=None)],
                    error=f'{type(exc).__name__}: {exc}')
    status = {'SAT': 'EXACT', 'UNSAT': 'CONTINUE'}.get(record['status'], 'INCOMPLETE')
    if record['status'] == 'SAT' and record['circuit']['reachable_gates'] != k:
        raise ValueError('Smaller witness contradicts previous UNSAT sizes')
    return dict(n=n, hex=hex_tt(n, f), status=status,
                minimum=k if status == 'EXACT' else None,
                runs=[dict(k=k, status=record['status'], run_id=record['run_id'])])


def minimum(n, f, max_k, root, options, backend='pysat', solver_name='cadical195',
            solver_argv=None, timeout=None, resume=False, *, progress=False):
    """Try ALL lower sizes. An unknown/error interrupts exactness; never skipped."""
    runs = []
    for k in range(max_k + 1):
        row = minimum_step(n, f, k, root, options, backend, solver_name,
                           solver_argv, timeout, resume, progress=progress)
        runs.extend(row['runs'])
        if row['status'] != 'CONTINUE':
            return dict(row, runs=runs)
    return dict(n=n, hex=hex_tt(n, f), status='ABOVE_LIMIT', minimum=None, runs=runs)
