"""Solver boundary: preserve UNKNOWN/errors; never infer UNSAT from missing models."""
import os
import re
import shlex
import signal
import subprocess
import time
from pathlib import Path


def parse_output(text, returncode):
    statuses = set(re.findall(r'^s\s+(SATISFIABLE|UNSATISFIABLE|UNKNOWN)\s*$', text, re.M))
    translated = {'SATISFIABLE': 'SAT', 'UNSATISFIABLE': 'UNSAT', 'UNKNOWN': 'UNKNOWN'}
    status = translated[next(iter(statuses))] if len(statuses) == 1 else 'ERROR'
    expected = {10: 'SAT', 20: 'UNSAT'}
    if returncode in expected:
        if status not in (expected[returncode], 'ERROR'):
            return 'ERROR', []
        # Standard solver exit code is valid even if no status line is printed.
        if not statuses:
            status = expected[returncode]
    elif returncode != 0:
        status = 'ERROR'
    model = [int(s) for line in text.splitlines() if line.startswith('v ')
             for s in line[2:].split() if int(s) != 0]
    return status, model


def parse_stats(text):
    result = {}
    for key in ('conflicts', 'decisions', 'propagations', 'restarts'):
        patterns = [rf'\b{key}\s*:\s*([\d,]+)', rf'\b{key}\s+([\d,]+)']
        for pattern in patterns:
            found = re.findall(pattern, text, re.I)
            if found:
                result[key] = int(found[-1].replace(',', ''))
                break
    for key, pattern in {
        'solver_cpu_seconds': r'process-time\s*:\s*([\d.]+)',
        'solver_peak_memory_mb': r'(?:maximum resident set size|maximum-resident-set-size)\s*:\s*([\d.]+)',
    }.items():
        found = re.findall(pattern, text, re.I)
        if found:
            result[key] = float(found[-1])
    return result


def external(argv, directory, timeout):
    """argv is a JSON array; placeholders are substituted per argument, no shell."""
    directory = Path(directory).resolve()
    cnf, proof = directory / 'instance.cnf', directory / 'proof.drat'
    command = [s.replace('{cnf}', str(cnf)).replace('{proof}', str(proof)) for s in argv]
    if not any('{cnf}' in s for s in argv):
        raise ValueError('External solver argv must contain {cnf}')
    started = time.perf_counter()
    with (directory / 'solver.stdout').open('w') as stdout, (directory / 'solver.stderr').open('w') as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    wall = time.perf_counter() - started
    text = (directory / 'solver.stdout').read_text(errors='replace')
    errors = (directory / 'solver.stderr').read_text(errors='replace')
    status, model = parse_output(text, process.returncode)
    if timed_out:
        status, model = 'TIMEOUT', []
    return dict(status=status, model=model, solve_wall_seconds=wall,
                solver_argv=command, returncode=process.returncode, **parse_stats(text + '\n' + errors))


def embedded(instance, name, directory):
    from pysat.solvers import Solver
    started = time.perf_counter()
    # Build/solve times separated: bootstrap clauses are counted in solver init.
    with Solver(name=name, bootstrap_with=instance.cnf.clauses, use_timer=True) as solver:
        initialized = time.perf_counter()
        sat = solver.solve()
        finished = time.perf_counter()
        result = dict(status='SAT' if sat else 'UNSAT', model=solver.get_model() if sat else [],
                      solve_wall_seconds=finished - initialized,
                      solver_init_wall_seconds=initialized - started,
                      solver_cpu_seconds=solver.time_accum(), **solver.accum_stats())
    Path(directory, 'solver.stdout').write_text('s ' + ('SATISFIABLE' if sat else 'UNSATISFIABLE') + '\n')
    return result


def check_proof(directory, checker, timeout=None, lrat=False):
    directory = Path(directory).resolve()
    proof = directory / 'proof.drat'
    if not proof.exists():
        raise ValueError('No proof.drat in this run')
    cmd = [checker, str(directory / 'instance.cnf'), str(proof)]
    if lrat:
        cmd += ['-L', str(directory / 'proof.lrat')]
    started = time.perf_counter()
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        text = run.stdout + '\n' + run.stderr
        # drat-trim returns zero on success; also demand its explicit verdict.
        verified = run.returncode == 0 and bool(re.search(r'^s VERIFIED\s*$', text, re.M))
        status = 'VERIFIED' if verified else 'FAILED'
    except subprocess.TimeoutExpired as exc:
        text = str(exc)
        status = 'TIMEOUT'
    (directory / 'proof-check.log').write_text(text)
    return dict(status=status, checker_argv=cmd, wall_seconds=time.perf_counter() - started)
