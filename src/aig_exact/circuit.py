"""Independent scalar AIG interpreter and witness analysis (no encoder imports)."""
from collections import Counter


def validate(circuit):
    n = circuit['n']
    if not isinstance(n, int) or not 0 <= n <= 5:
        raise ValueError('Invalid input count')
    for i, pair in enumerate(circuit['gates']):
        if len(pair) != 2 or any(not isinstance(a, int) or not 0 <= a < 2 * (n + i + 1) for a in pair):
            raise ValueError('Non-topological or invalid gate')
    if not isinstance(circuit['output'], int) or not 0 <= circuit['output'] < 2 * (n + len(circuit['gates']) + 1):
        raise ValueError('Invalid output')


def simulate(circuit):
    validate(circuit)
    n = circuit['n']
    result = 0
    for assignment in range(1 << n):
        signals = [False] + [bool((assignment >> i) & 1) for i in range(n)]
        def read(lit):
            return signals[lit // 2] ^ bool(lit & 1)
        for a, b in circuit['gates']:
            signals.append(read(a) and read(b))
        result |= int(read(circuit['output'])) << assignment
    return result


def reachable(circuit):
    n = circuit['n']
    live = set()
    def visit(s):
        if s <= n or s in live:
            return
        live.add(s)
        for a in circuit['gates'][s - n - 1]:
            visit(a // 2)
    visit(circuit['output'] // 2)
    return live


def compact(circuit):
    validate(circuit)
    n = circuit['n']
    live = reachable(circuit)
    mapping = {i: i for i in range(n + 1)}
    gates = []
    def remap(a):
        return 2 * mapping[a // 2] + (a & 1)
    for i, pair in enumerate(circuit['gates'], n + 1):
        if i in live:
            gates.append([remap(a) for a in pair])
            mapping[i] = n + len(gates)
    return dict(n=n, gates=gates, output=remap(circuit['output']))


def aag(circuit):
    c = compact(circuit)
    n, gates = c['n'], c['gates']
    lines = [f'aag {n + len(gates)} {n} 0 1 {len(gates)}']
    lines += [str(2 * i) for i in range(1, n + 1)]
    lines += [str(c['output'])]
    lines += [f'{2 * (n + i + 1)} {max(pair)} {min(pair)}' for i, pair in enumerate(gates)]
    return '\n'.join(lines) + '\n'


def restricted(circuit, variable, value):
    """Constant propagation, identities, complements and structural hashing only.

    The input remains declared (unused). Gate loss is a property of this witness,
    not a universal elimination theorem about every circuit for the function.
    """
    n = circuit['n']
    mapping = {i: 2 * i for i in range(n + 1)}
    mapping[variable + 1] = value
    gates, cache = [], {}
    def read(a):
        return mapping[a // 2] ^ (a & 1)
    for i, (a, b) in enumerate(circuit['gates'], n + 1):
        a, b = sorted((read(a), read(b)))
        if a == 0 or b == 0 or a == (b ^ 1):
            out = 0
        elif a == 1:
            out = b
        elif b == 1 or a == b:
            out = a
        else:
            if (a, b) not in cache:
                gates.append([a, b])
                cache[a, b] = 2 * (n + len(gates))
            out = cache[a, b]
        mapping[i] = out
    return compact(dict(n=n, gates=gates, output=read(circuit['output'])))


def analyze(circuit, automorphisms=False):
    c = compact(circuit)
    n = c['n']
    depths = [0] * (n + 1)
    fanout = Counter()
    for pair in c['gates']:
        depths.append(1 + max(depths[a // 2] for a in pair))
        fanout.update(a // 2 for a in pair)
    fanout[c['output'] // 2] += 1
    result = dict(declared_gates=len(circuit['gates']), reachable_gates=len(c['gates']),
                  depth=depths[c['output'] // 2], gate_fanouts=[fanout[i] for i in range(n + 1, len(depths))],
                  complemented_edges=sum(a & 1 for pair in c['gates'] for a in pair) + (c['output'] & 1),
                  restrictions=[dict(variable=i, value=b,
                                     remaining_gates=len(restricted(c, i, b)['gates']),
                                     eliminated_gates=len(c['gates']) - len(restricted(c, i, b)['gates']))
                                for i in range(n) for b in (0, 1)])
    if automorphisms:
        import networkx as nx
        graph = nx.DiGraph()
        for i in range(n + 1):
            graph.add_node(('s', i), color=f'input:{i}')
        for i, pair in enumerate(c['gates'], n + 1):
            graph.add_node(('s', i), color='gate')
            for port, lit in enumerate(pair):
                edge = ('wire', i, port)
                graph.add_node(edge, color=f'phase:{lit & 1}')
                graph.add_edge(('s', lit // 2), edge)
                graph.add_edge(edge, ('s', i))
        graph.add_node('output', color=f'output:{c["output"] & 1}')
        graph.add_edge(('s', c['output'] // 2), 'output')
        matcher = nx.algorithms.isomorphism.DiGraphMatcher(
            graph, graph, node_match=lambda a, b: a['color'] == b['color'])
        # Count distinct signal maps; identical parallel incidence wires do not
        # introduce additional circuit-vertex automorphisms.
        maps = {tuple(m[('s', i)] for i in range(n + len(c['gates']) + 1))
                for m in matcher.isomorphisms_iter()}
        result['fixed_input_phase_preserving_automorphisms'] = len(maps)
    return result
