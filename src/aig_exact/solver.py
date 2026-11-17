"""Solver boundary: preserve UNKNOWN/errors; never infer UNSAT from missing models."""
import os
import re
import shutil
import signal
import subprocess
import time
from functools import lru_cache
from hashlib import file_digest
from pathlib import Path


CADICAL_ARGV = ('cadical', '-v', '--seed=0', '{cnf}')


@lru_cache(maxsize=32)
def binary_info(path, stamp, check_version):
    with open(path, 'rb') as stream:
        info = dict(solver_binary_sha256=file_digest(stream, 'sha256').hexdigest())
    if check_version:
        try:
            version = subprocess.check_output([path, '--version'], text=True, timeout=5).strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f'Could not read CaDiCaL version from {path}') from exc
        match = re.fullmatch(r'(\d+)\.\d+\.\d+(?:[-+][\w.-]+)?', version)
        if match is None or int(match[1]) < 3:
            raise ValueError(f'CaDiCaL 3 or newer is required, found {version!r} at {path}')
        info['cadical_version'] = version
    return info


def prepare(backend, argv=None):
    """Resolve the executable that will be run and fingerprint it for resume."""
    if backend not in ('cadical', 'external'):
        raise ValueError('Use backend cadical or external. Regenerate any PySAT manifests.')
    if argv is None and backend == 'cadical':
        argv = list(CADICAL_ARGV)
    if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) for arg in argv):
        raise ValueError('Solver argv must be a nonempty JSON array of strings')
    if not any('{cnf}' in arg for arg in argv[1:]):
        raise ValueError('Solver argv must pass {cnf} to the executable')
    binary = shutil.which(argv[0])
    if binary is None:
        hint = '. Build CaDiCaL 3+ and put it on PATH (see README)' if backend == 'cadical' else ''
        raise FileNotFoundError(f'Solver executable {argv[0]!r} not found{hint}')
    path = Path(binary).absolute()
    stat = path.stat()
    stamp = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    info = binary_info(str(path), stamp, backend == 'cadical')
    return [str(path), *argv[1:]], info


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
        # CaDiCaL -v also prints indented counters for warmup and other phases.
        # Those must not replace the top-level totals.
        patterns = [rf'^(?:c )?{key}[ \t]*:[ \t]*([\d,]+)',
                    rf'^(?:c )?{key}[ \t]+([\d,]+)']
        for pattern in patterns:
            found = re.findall(pattern, text, re.I | re.M)
            if found:
                result[key] = int(found[-1].replace(',', ''))
                break
    for key, pattern in {
        'solver_cpu_seconds': r'(?:process-time|total process time since initialization)\s*:\s*([\d.]+)',
        'solver_peak_memory_mb': r'(?:maximum resident set size|maximum-resident-set-size)(?: of process)?\s*:\s*([\d.]+)',
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
    # Waiting on the pipes avoids timeout polling rounding short solve times.
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          start_new_session=True) as process:
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
    wall = time.perf_counter() - started
    (directory / 'solver.stdout').write_bytes(stdout)
    (directory / 'solver.stderr').write_bytes(stderr)
    text, errors = stdout.decode(errors='replace'), stderr.decode(errors='replace')
    if timed_out:
        status, model = 'TIMEOUT', []
    else:
        status, model = parse_output(text, process.returncode)
    return dict(status=status, model=model, solve_wall_seconds=wall,
                solver_argv=command, returncode=process.returncode, **parse_stats(text + '\n' + errors))


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
