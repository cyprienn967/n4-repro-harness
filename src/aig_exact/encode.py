"""AIG-specific SSV-style, MSV-style and DITT-style full truth-table encoders.

These are controlled adaptations, not a copy of Percy's general-gate encoders.
Source IDs: 0=false, 1..n=inputs, n+1..n+k=AND gates.
A circuit literal is 2*source_id + complement_bit (AIGER convention).
"""
from dataclasses import dataclass, asdict
from itertools import product
from .boolean import validate, stabilizer
from .cnf import CNF


@dataclass(frozen=True)
class Options:
    encoding: str = 'ssv'
    cardinality: str = 'sequential'
    fanin_order: bool = True
    no_trivial: bool = False
    no_duplicates: bool = False
    all_used: bool = False
    target_symmetry: bool = False

    @property
    def minimal_only(self):
        return self.no_trivial or self.no_duplicates or self.all_used


class Instance:
    def __init__(self, n, f, k, options=Options()):
        validate(n, f)
        if k < 0:
            raise ValueError('k must be nonnegative')
        if options.encoding not in ('ssv', 'msv', 'ditt'):
            raise ValueError('Unknown encoding')
        if options.target_symmetry and not options.fanin_order:
            raise ValueError('target_symmetry requires fanin_order')
        self.n, self.f, self.k, self.options = n, f, k, options
        self.cnf = c = CNF()
        self.values = [[c.var(f'value:{g}:{t}') for t in range(1 << n)] for g in range(k)]
        self.pairs, self.ports, self.joints = [], [], []
        self.uses = [[] for _ in range(k)]
        first_stabilizer = stabilizer(n, f) if options.target_symmetry and k else []
        for g in range(k):
            choices = list(range(2 * (n + 1 + g)))
            pair_choices = list(product(choices, repeat=2))
            if options.fanin_order:
                pair_choices = [(a, b) for a, b in pair_choices if a <= b]
            if options.no_trivial:
                pair_choices = [(a, b) for a, b in pair_choices
                                if a // 2 != b // 2 and a // 2 and b // 2]
            if g == 0 and first_stabilizer:
                def moved(lit, p, neg):
                    s, phase = divmod(lit, 2)
                    if s == 0:
                        return lit
                    return 2 * (p[s - 1] + 1) + (phase ^ ((neg >> (s - 1)) & 1))
                pair_choices = [(a, b) for a, b in pair_choices if (a, b) == min(
                    tuple(sorted((moved(a, p, neg), moved(b, p, neg))))
                    for p, neg, _ in first_stabilizer)]
            pairset = set(pair_choices)
            joint = {}
            if options.encoding == 'ssv':
                pairs = {pair: c.var(f'pair:{g}:{pair[0]}:{pair[1]}') for pair in pair_choices}
                c.exactly_one(list(pairs.values()), options.cardinality)
                ports = None
                for pair, sel in pairs.items():
                    joint[pair] = sel
                    for t in range(1 << n):
                        c.and_gate(self.values[g][t], self.value(pair[0], t),
                                   self.value(pair[1], t), (sel,))
                    for s in {a // 2 for a in pair}:
                        if s > n:
                            self.uses[s - n - 1].append(sel)
            else:
                pairs = None
                ports = [{a: c.var(f'port:{g}:{port}:{a}') for a in choices} for port in range(2)]
                for port in ports:
                    c.exactly_one(list(port.values()), options.cardinality)
                    for a, sel in port.items():
                        if a // 2 > n:
                            self.uses[a // 2 - n - 1].append(sel)
                for a, b in product(choices, repeat=2):
                    if (a, b) not in pairset:
                        c.add(-ports[0][a], -ports[1][b])
                if options.encoding == 'msv':
                    for a, b in pair_choices:
                        for t in range(1 << n):
                            c.and_gate(self.values[g][t], self.value(a, t), self.value(b, t),
                                       (ports[0][a], ports[1][b]))
                else:
                    port_values = [[c.var(f'port-value:{g}:{p}:{t}') for t in range(1 << n)]
                                   for p in range(2)]
                    for p in range(2):
                        for a, sel in ports[p].items():
                            for t in range(1 << n):
                                c.equal(port_values[p][t], self.value(a, t), (sel,))
                    for t in range(1 << n):
                        c.and_gate(self.values[g][t], port_values[0][t], port_values[1][t])
                if options.no_duplicates:
                    for a, b in pair_choices:
                        q = c.var(f'joint:{g}:{a}:{b}')
                        c.add(-q, ports[0][a])
                        c.add(-q, ports[1][b])
                        c.add(q, -ports[0][a], -ports[1][b])
                        joint[a, b] = q
            if options.no_duplicates:
                # Sort both orders so this toggle is also sound with fanin_order=False.
                for pair, sel in joint.items():
                    normalized = tuple(sorted(pair))
                    for earlier in self.joints:
                        for previous in (normalized, normalized[::-1]):
                            if previous in earlier:
                                c.add(-sel, -earlier[previous])
            self.pairs.append(pairs)
            self.ports.append(ports)
            self.joints.append(joint)
        self.output = {a: c.var(f'output:{a}') for a in range(2 * (n + k + 1))}
        c.exactly_one(list(self.output.values()), options.cardinality)
        for a, sel in self.output.items():
            for t in range(1 << n):
                v = self.value(a, t)
                c.add(-sel, v if ((f >> t) & 1) else -v)
            if a // 2 > n:
                self.uses[a // 2 - n - 1].append(sel)
        if options.all_used:
            # Every gate has a later consumer or is the output; acyclicity implies reachability.
            for uses in self.uses:
                c.add(*uses)

    def value(self, lit, t):
        s, phase = divmod(lit, 2)
        if s == 0:
            result = -self.cnf.true
        elif s <= self.n:
            result = self.cnf.true if ((t >> (s - 1)) & 1) else -self.cnf.true
        else:
            result = self.values[s - self.n - 1][t]
        return -result if phase else result

    def metadata(self):
        return dict(n=self.n, truth_table=self.f, k=self.k, options=asdict(self.options),
                    query='minimal-search' if self.options.minimal_only else 'at-most',
                    **self.cnf.stats())

    def decode(self, model):
        positive = {v for v in model if v > 0}
        gates = []
        def selected(mapping):
            found = [a for a, sel in mapping.items() if sel in positive]
            if len(found) != 1:
                raise ValueError('Missing or invalid SAT model selector')
            return found[0]
        for pairs, ports in zip(self.pairs, self.ports):
            gates.append(list(selected(pairs)) if pairs is not None else
                         [selected(ports[0]), selected(ports[1])])
        return dict(n=self.n, gates=gates, output=selected(self.output))
