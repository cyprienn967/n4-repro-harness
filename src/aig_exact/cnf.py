"""Small deterministic CNF builder. Signed integers are SAT literals."""
from collections import Counter


class CNF:
    def __init__(self):
        self.names = []
        self.clauses = []
        self.true = self.var('true')
        self.add(self.true)

    def var(self, name):
        self.names.append(name)
        return len(self.names)

    def add(self, *lits):
        assert all(isinstance(x, int) and 0 < abs(x) <= len(self.names) for x in lits)
        clause = list(dict.fromkeys(lits))
        if not any(-x in clause for x in clause):
            self.clauses.append(clause)

    def exactly_one(self, lits, method='sequential'):
        self.add(*lits)
        if method == 'pairwise':
            for i, a in enumerate(lits):
                for b in lits[i + 1:]:
                    self.add(-a, -b)
        elif method == 'sequential':
            # Sinz ladder, including the zero/one-choice boundary cases.
            if len(lits) <= 1:
                return
            ladder = [self.var(f'amo:{len(self.names)}:{i}') for i in range(len(lits) - 1)]
            self.add(-lits[0], ladder[0])
            for i in range(1, len(lits) - 1):
                self.add(-lits[i], ladder[i])
                self.add(-ladder[i - 1], ladder[i])
                self.add(-lits[i], -ladder[i - 1])
            self.add(-lits[-1], -ladder[-1])
        else:
            raise ValueError(method)

    def equal(self, a, b, guards=()):
        self.add(*(-g for g in guards), -a, b)
        self.add(*(-g for g in guards), a, -b)

    def and_gate(self, z, a, b, guards=()):
        prefix = [-g for g in guards]
        self.add(*prefix, -z, a)
        self.add(*prefix, -z, b)
        self.add(*prefix, z, -a, -b)

    def dimacs(self):
        return f'p cnf {len(self.names)} {len(self.clauses)}\n' + ''.join(
            ' '.join(map(str, c)) + ' 0\n' for c in self.clauses)

    def stats(self):
        return dict(variables=len(self.names), clauses=len(self.clauses),
                    literals=sum(map(len, self.clauses)),
                    clause_lengths=dict(Counter(map(len, self.clauses))))
