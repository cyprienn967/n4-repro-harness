"""Haaswijk et al. (TCAD 2020), Sections III-A--D, two-input/single-output case.

Signals x_1..x_n are primary inputs; steps x_(n+1)..x_(n+r) are normal
operators. Operator bit f_i_pq uses index 2*p+q, with f_i_00 fixed to zero.
SSV and DITT deliberately use at-least-one selection, as in the paper.
"""
from dataclasses import asdict
from itertools import combinations, product
from .boolean import validate
from .cnf import CNF


class PaperInstance:
    def __init__(self, n, f, k, options):
        validate(n, f)
        if k < 0:
            raise ValueError('k must be nonnegative')
        self.n, self.f, self.k, self.options = n, f, k, options
        self.cnf = c = CNF()
        self.output_phase = f & 1
        self.target = f ^ (((1 << (1 << n)) - 1) if self.output_phase else 0)
        self.values = {i: {t: c.var(f'x:{i}:{t}') for t in range(1, 1 << n)}
                       for i in range(n + 1, n + k + 1)}
        self.operators = {i: {(p, q): c.var(f'f:{i}:{p}{q}')
                              for p, q in ((0, 1), (1, 0), (1, 1))}
                          for i in self.values}
        self.pairs, self.members, self.ports, self.port_values = {}, {}, {}, {}
        self.uses = {i: [] for i in range(n + k + 1)}
        for i in self.values:
            pairs = list(combinations(range(1, i), 2))
            if options.encoding == 'ssv':
                selectors = {pair: c.var(f's:{i}:{pair[0]}:{pair[1]}') for pair in pairs}
                c.add(*selectors.values())
                self.pairs[i] = {pair: (sel,) for pair, sel in selectors.items()}
                for (j, h), sel in selectors.items():
                    self.uses[j].append((i, sel))
                    self.uses[h].append((i, sel))
            elif options.encoding == 'msv':
                selectors = {j: c.var(f's:{i}:{j}') for j in range(1, i)}
                self.members[i] = selectors
                c.exactly_two(list(selectors.values()))
                self.pairs[i] = {(j, h): (selectors[j], selectors[h]) for j, h in pairs}
                for j, sel in selectors.items():
                    self.uses[j].append((i, sel))
            else:
                ports = [{j: c.var(f's:{i}:{port}:{j}') for j in range(1, i)}
                         for port in (1, 2)]
                self.ports[i] = ports
                for port in ports:
                    c.add(*port.values())
                    for j, sel in port.items():
                        self.uses[j].append((i, sel))
                # Strictly increasing operands, including the boundary j=i-1.
                for j in range(1, i):
                    for h in range(1, j + 1):
                        c.add(-ports[0][j], -ports[1][h])
                self.pairs[i] = {(j, h): (ports[0][j], ports[1][h]) for j, h in pairs}
                inputs = [{t: c.var(f'x:{i}:port:{port}:{t}') for t in range(1, 1 << n)}
                          for port in (1, 2)]
                self.port_values[i] = inputs
                for port, values in zip(ports, inputs):
                    for j, sel in port.items():
                        for t, value in values.items():
                            c.equal(value, self.value(j, t), (sel,))
                for t in self.values[i]:
                    self.operator_relation(i, t, inputs[0][t], inputs[1][t], ())
            if options.encoding != 'ditt':
                for (j, h), guards in self.pairs[i].items():
                    for t in self.values[i]:
                        self.operator_relation(i, t, self.value(j, t), self.value(h, t), guards)

        # Trivial zero-step targets are handled explicitly before gate synthesis.
        sources = range(0, n + 1) if k == 0 else self.values
        self.output = {i: c.var(f'g:1:{i}') for i in sources}
        c.add(*self.output.values())
        for i, sel in self.output.items():
            for t in range(1, 1 << n):
                value = self.value(i, t)
                c.add(-sel, value if (self.target >> t) & 1 else -value)
        self.symmetry_clauses()

    def value(self, source, t):
        if source == 0:
            return -self.cnf.true
        if source <= self.n:
            return self.cnf.true if (t >> (source - 1)) & 1 else -self.cnf.true
        return self.values[source][t]

    def operator_relation(self, i, t, left, right, guards):
        # The eight assignments (a,b,c) in the paper's main-clause schema.
        for a, b, c in product((0, 1), repeat=3):
            operator = self.operators[i].get((b, c), -self.cnf.true)
            self.cnf.add(*(-g for g in guards),
                         -self.values[i][t] if a else self.values[i][t],
                         -left if b else left, -right if c else right,
                         operator if a else -operator)

    def symmetry_clauses(self):
        c, enabled = self.cnf, self.options.symmetries
        for i, op in self.operators.items():
            f01, f10, f11 = op[0, 1], op[1, 0], op[1, 1]
            if 'N' in enabled:
                c.add(f01, f10, f11)
                c.add(f01, -f10, -f11)
                c.add(-f01, f10, -f11)
            if 'A' in enabled:
                c.add(self.output[i], *(sel for _, sel in self.uses[i]))
            if 'R' in enabled:
                for (j, h), guards in self.pairs[i].items():
                    for later in range(i + 1, self.n + self.k + 1):
                        for reused in (j, h):
                            other = self.pairs[later][reused, i]
                            c.add(*(-v for v in guards + other))
            if i == self.n + self.k:
                continue
            if 'C' in enabled:
                for (j, h), guards in self.pairs[i].items():
                    for (j2, h2), other in self.pairs[i + 1].items():
                        if (h2, j2) < (h, j):
                            # Both selections are negated: the printed C formula
                            # omits a bar on its second literal (cf. Percy).
                            c.add(*(-v for v in guards + other))
            if 'O' in enabled:
                self.order_operators(i)
        if 'S' in enabled:
            for p, q in combinations(range(1, self.n + 1), 2):
                if not self.symmetric(p, q):
                    continue
                for i, pairs in self.pairs.items():
                    earlier = [sel for step, sel in self.uses[p] if step < i]
                    for pair, guards in pairs.items():
                        if q in pair and p not in pair:
                            c.add(*(-v for v in guards), *earlier)

    def order_operators(self, i):
        """Strict lexicographic order of (f11, f10, f01) for equal fanin pairs."""
        c = self.cnf
        left = [self.operators[i][key] for key in ((1, 1), (1, 0), (0, 1))]
        right = [self.operators[i + 1][key] for key in ((1, 1), (1, 0), (0, 1))]
        equals = []
        for a, b in zip(left, right):
            equal = c.var(f'op-equal:{i}:{len(equals)}')
            c.add(-equal, -a, b)
            c.add(-equal, a, -b)
            c.add(equal, a, b)
            c.add(equal, -a, -b)
            equals.append(equal)
        for pair, guards in self.pairs[i].items():
            prefix = [-v for v in guards + self.pairs[i + 1][pair]]
            for bit, (a, b) in enumerate(zip(left, right)):
                c.add(*prefix, *(-e for e in equals[:bit]), -a, b)
            c.add(*prefix, *(-e for e in equals))

    def symmetric(self, p, q):
        p, q = p - 1, q - 1
        for t in range(1 << self.n):
            swapped = t
            if ((t >> p) ^ (t >> q)) & 1:
                swapped ^= (1 << p) | (1 << q)
            if ((self.target >> t) ^ (self.target >> swapped)) & 1:
                return False
        return True

    def metadata(self):
        return dict(n=self.n, truth_table=self.f, k=self.k, options=asdict(self.options),
                    model='paper', gate_basis='arbitrary-normal-two-input',
                    normalized_target=self.target, output_phase=self.output_phase,
                    query='minimal-search' if self.options.symmetries else 'paper-chain',
                    selection_semantics='exactly-two' if self.options.encoding == 'msv' else 'at-least-one',
                    **self.cnf.stats())

    def decode(self, model):
        positive = {v for v in model if v > 0}
        gates, operators = [], []
        for i, pairs in self.pairs.items():
            selected = next((pair for pair, guards in pairs.items()
                             if all(v in positive for v in guards)), None)
            if selected is None:
                raise ValueError('Missing valid operand selection')
            gates.append([2 * j for j in selected])
            operators.append(sum(1 << (2 * p + q) for (p, q), var in self.operators[i].items()
                                 if var in positive))
        output = next((i for i, var in self.output.items() if var in positive), None)
        if output is None:
            raise ValueError('Missing output selection')
        return dict(model='paper', n=self.n, gates=gates, operators=operators,
                    output=2 * output + self.output_phase)
