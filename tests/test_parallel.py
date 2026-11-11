import importlib.util
import json
from functools import partial
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from aig_exact.cli import minimum_rows


def recorded_step(f, k, log):
    with Path(log).open('a') as stream:
        stream.write(f'{f},{k}\n')
    return dict(n=2, hex=f'{f:x}', status='CONTINUE' if k == 0 else 'EXACT',
                minimum=None if k == 0 else 1,
                runs=[dict(k=k, status='UNSAT' if k == 0 else 'SAT', run_id=f'{f}-{k}')])


class ParallelTests(unittest.TestCase):
    def test_next_budget_goes_to_back_of_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory, 'steps.txt')
            rows = list(minimum_rows([1, 2, 3], partial(recorded_step, log=log), 1, 2))
            self.assertEqual(log.read_text().splitlines(),
                             ['1,0', '2,0', '3,0', '1,1', '2,1', '3,1'])
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(len(row['runs']) == 2 for _, row in rows))

    @unittest.skipUnless(importlib.util.find_spec('pysat'), 'Requires python-sat')
    def test_slow_function_does_not_block_others_and_can_be_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            functions = root / 'functions.txt'
            functions.write_text('0\n1\n3\n6\n')
            solver = root / 'controlled_solver.py'
            solver.write_text("""
import json
from pathlib import Path
import sys
import time
from pysat.formula import CNF
from pysat.solvers import Solver

cnf_path = Path(sys.argv[1])
task = json.loads((cnf_path.parent / 'task.json').read_text())
if task['hex'] == '0' and not Path(sys.argv[2]).exists():
    time.sleep(60)
with Solver(name='cadical195', bootstrap_with=CNF(from_file=str(cnf_path)).clauses) as solver:
    sat = solver.solve()
    print('s SATISFIABLE' if sat else 's UNSATISFIABLE')
    if sat:
        print('v', *solver.get_model(), 0)
""")
            permit = root / 'permit-slow-function'
            argv = json.dumps([sys.executable, str(solver), '{cnf}', str(permit)])
            output = root / 'results'
            common = [sys.executable, '-m', 'aig_exact', 'reproduce', '-n', '2',
                      '--max-gates', '3', '--backend', 'external', '--solver-argv', argv,
                      '--workers', '2', '--timeout', '2']
            run = subprocess.run(common + ['--functions', str(functions), '--out', str(output)],
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
            self.assertLess(run.stdout.index('3: EXACT'), run.stdout.index('0: TIMEOUT'))
            report = json.loads((output / 'minima.json').read_text())
            self.assertEqual([row['status'] for row in report['functions']],
                             ['INCOMPLETE', 'EXACT', 'EXACT', 'EXACT'])
            deferred = output / 'timed-out.json'
            self.assertEqual(json.loads(deferred.read_text())['functions'], [dict(hex='0', k=0)])
            self.assertFalse(list(output.rglob('.lock')))
            permit.touch()
            original_report = (output / 'minima.json').read_bytes()
            retry = root / 'retry'
            run = subprocess.run(common + ['--functions', str(deferred), '--allow-subset',
                                           '--out', str(retry)],
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            rows = json.loads((retry / 'minima.json').read_text())['functions']
            self.assertEqual([(row['hex'], row['minimum']) for row in rows], [('0', 0)])
            self.assertEqual((output / 'minima.json').read_bytes(), original_report)
