import json
import sys
import tempfile
import unittest
from pathlib import Path

from aig_exact.experiment import run_task
from aig_exact.plot import paired_times


class BenchmarkTests(unittest.TestCase):
    def test_minimum_mismatch_is_saved_as_error(self):
        task = dict(n=2, hex='8', k=1, minimum=1, backend='external',
                    solver_argv=[sys.executable, '-c', 'print("s UNSATISFIABLE"); raise SystemExit(20)', '{cnf}'])
        with tempfile.TemporaryDirectory() as out:
            result = run_task(task, out)
            path = Path(result['directory'])
            self.assertEqual(result['status'], 'ERROR')
            self.assertEqual(result['expected_status'], 'SAT')
            self.assertEqual(result['solver_status'], 'UNSAT')
            saved = json.loads((path / 'result.json').read_text())
            self.assertEqual(saved['status'], 'ERROR')
            self.assertEqual(saved['solver_status'], 'UNSAT')
            self.assertEqual((path / 'solver.stdout').read_text(), 's UNSATISFIABLE\n')

    def test_plot_keeps_budgets_paired_and_excludes_incomplete_results(self):
        def run(label, f, k, status, seconds):
            return dict(run_id=f'{label}-{f}-{k}', status=status, solve_wall_seconds=seconds,
                        task=dict(label=label, n=2, hex=f, minimum=1, k=k,
                                  options=dict(model='paper')))

        rows = [
            run('x', '8', 1, 'SAT', 1), run('y', '8', 1, 'SAT', 4),
            run('y', '8', 0, 'UNSAT', 2), run('x', '8', 0, 'UNSAT', 5),
            run('x', '6', 1, 'SAT', 1), run('y', '6', 1, 'TIMEOUT', 10),
            run('x', 'a', 0, 'UNSAT', 3), run('y', 'a', 1, 'SAT', 2),
        ]
        times, missing, incomplete = paired_times(rows, 'x', 'y')
        self.assertEqual(times, {'SAT': [(1, 4)], 'UNSAT': [(5, 2)]})
        self.assertEqual((missing, incomplete), (2, 1))
