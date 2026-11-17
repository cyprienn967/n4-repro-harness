"""Run the same CaDiCaL version used by the CLI on small test CNFs."""
import subprocess

from aig_exact.solver import parse_output, prepare

try:
    CADICAL = prepare('cadical')[0][0]
except (OSError, ValueError):
    CADICAL = None


def solve(cnf, assumptions=()):
    dimacs = cnf.dimacs()
    if assumptions:
        _, clauses = dimacs.split('\n', 1)
        dimacs = f'p cnf {len(cnf.names)} {len(cnf.clauses) + len(assumptions)}\n' + clauses
        dimacs += ''.join(f'{lit} 0\n' for lit in assumptions)
    run = subprocess.run([CADICAL, '-q'], input=dimacs, capture_output=True, text=True, timeout=15)
    status, model = parse_output(run.stdout, run.returncode)
    if status not in ('SAT', 'UNSAT'):
        raise AssertionError(f'CaDiCaL returned {status}: {run.stdout}\n{run.stderr}')
    return status == 'SAT', model
