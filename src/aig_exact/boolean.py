"""Little-endian truth tables: bit t is f((t>>0)&1, ..., (t>>(n-1))&1)."""
from itertools import permutations
from math import factorial


def mask(n):
    return (1 << (1 << n)) - 1


def validate(n, f):
    if not 0 <= n <= 5 or not 0 <= f <= mask(n):
        raise ValueError("Require 0 <= n <= 5 and a truth table fitting 2**n bits")


def hex_tt(n, f):
    return f"{f:0{max(1, ((1 << n) + 3) // 4)}x}"


def inputs(n):
    return [sum(((t >> i) & 1) << t for t in range(1 << n)) for i in range(n)]


def transformations(n):
    """Input part only; output complement is enumerated separately when needed."""
    for p in permutations(range(n)):
        for neg in range(1 << n):
            yield p, neg


def transform(n, f, p, neg=0, out=0):
    """T(f)(x) = out XOR f(y), y_i = x_{p[i]} XOR neg_i."""
    result = 0
    for t in range(1 << n):
        y = sum((((t >> p[i]) & 1) ^ ((neg >> i) & 1)) << i for i in range(n))
        result |= (((f >> y) & 1) ^ out) << t
    return result


def orbit(n, f):
    m = mask(n)
    result = set()
    for p, neg in transformations(n):
        g = transform(n, f, p, neg)
        result.update((g, g ^ m))
    return result


def canonical(n, f):
    return min(orbit(n, f))


def stabilizer(n, f):
    result = []
    for p, neg in transformations(n):
        g = transform(n, f, p, neg)
        if g == f:
            result.append((p, neg, 0))
        if g ^ mask(n) == f:
            result.append((p, neg, 1))
    return result


def representatives(n):
    """Exhaustive orbit partition; intentionally restricted to n <= 4."""
    if not 0 <= n <= 4:
        raise ValueError("Full representative generation is limited to n <= 4")
    seen = set()
    for f in range(1 << (1 << n)):
        if f not in seen:
            seen.update(orbit(n, f))
            yield f


def cofactor(n, f, i, b):
    result = 0
    for t in range(1 << (n - 1)):
        low = t & ((1 << i) - 1)
        high = t >> i
        original = low | (b << i) | (high << (i + 1))
        result |= ((f >> original) & 1) << t
    return result


def features(n, f, include_stabilizer=False):
    validate(n, f)
    size = 1 << n
    coeff = [(f >> t) & 1 for t in range(size)]
    for i in range(n):
        for t in range(size):
            if t & (1 << i):
                coeff[t] ^= coeff[t ^ (1 << i)]
    monomials = [t for t, a in enumerate(coeff) if a]
    walsh = [sum((-1) ** (((f >> t) & 1) ^ ((a & t).bit_count() & 1))
                 for t in range(size)) for a in range(size)]
    autocorrelation = [sum((-1) ** (((f >> t) ^ (f >> (t ^ a))) & 1)
                              for t in range(size)) for a in range(size)]
    sensitivities = [sum(((f >> t) ^ (f >> (t ^ (1 << i)))) & 1 for i in range(n))
                     for t in range(size)]
    restrictions, influences, derivatives, unate = [], [], [], []
    for i in range(n):
        lo, hi = cofactor(n, f, i, 0), cofactor(n, f, i, 1)
        derivatives.append(hex_tt(n - 1, lo ^ hi))
        influences.append((lo ^ hi).bit_count() / (size // 2))
        positive = (lo & ~hi) == 0
        negative = (hi & ~lo) == 0
        unate.append(positive or negative)
        for b, g in enumerate((lo, hi)):
            restrictions.append(dict(variable=i, value=b, hex=hex_tt(n - 1, g),
                                     npn=hex_tt(n - 1, canonical(n - 1, g))))
    st = stabilizer(n, f)
    group_size = (1 << n) * factorial(n) * 2
    result = dict(n=n, hex=hex_tt(n, f), npn=hex_tt(n, canonical(n, f)),
                  weight=f.bit_count(), essential_variables=sum(x != 0 for x in influences),
                  degree=max((t.bit_count() for t in monomials), default=0),
                  anf_monomials=monomials, anf_count=len(monomials), walsh=walsh,
                  autocorrelation=autocorrelation, sensitivity=sensitivities,
                  max_sensitivity=max(sensitivities), influences=influences,
                  derivatives=derivatives, cofactors=restrictions, unate=all(unate),
                  monotone=all(((f >> t) & 1) <= ((f >> (t | (1 << i))) & 1)
                               for t in range(size) for i in range(n)),
                  npn_group_size=group_size, stabilizer_size=len(st),
                  orbit_size=group_size // len(st),
                  input_only_stabilizer_size=sum(o == 0 for _, _, o in st),
                  restriction_orbits=sorted({tuple(sorted((p[i], b ^ ((neg >> i) & 1))
                      for p, neg, _ in st)) for i in range(n) for b in (0, 1)}))
    if include_stabilizer:
        result['stabilizer'] = [dict(permutation=p, input_negations=neg, output_negation=o)
                                for p, neg, o in st]
    return result
