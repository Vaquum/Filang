"""Recomputes every code in dimension-vectors.json from its bars, sharing no code with the study engine.

Run from anywhere: python3 study/verify/dimension-vectors.py
"""
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
ORDER = ['volume', 'trades', 'delta', 'size', 'imbalance']
REFERENCE = {'delta', 'imbalance'}


def price_code(bars, chained):
    rows, directions = [], []
    for k, bar in enumerate(bars):
        o, h, l, c = bar[:4]
        if chained and k:
            o = bars[k - 1][3]
            l, h = min(l, o), max(h, o)
        rows.append([l, min(o, c), max(o, c), h])
        directions.append('u' if c > o else 'd' if c < o else 'z')
    rank = {v: r for r, v in enumerate(sorted({v for row in rows for v in row}))}
    return 'g1:o:' + ';'.join(','.join([*(str(rank[v]) for v in row), d]) for row, d in zip(rows, directions))


def value(name, v, b, n):
    if name == 'volume':
        return v
    if name == 'trades':
        return n
    if name == 'delta':
        return 2 * b - v
    if name == 'size':
        return v / n if n > 0 else None
    return (2 * b - v) / v if v > 0 else None


def part(bars, name):
    read = [value(name, float(bar[4]), float(bar[5]), float(bar[6])) for bar in bars]
    values = [x for x in read if x is not None]
    if len(values) != len(read):
        return None
    points = values + ([0.0] if name in REFERENCE else [])
    rank = {v: r for r, v in enumerate(sorted(set(points)))}
    text = name + ':' + ','.join(str(rank[x]) for x in values)
    return text + ('/' + str(rank[0.0]) if name in REFERENCE else '')


def main():
    document = json.loads((HERE / 'dimension-vectors.json').read_text())
    assert document['dimensions'] == ORDER, 'the dimension order changed'
    checked = 0
    for vector in document['vectors']:
        bars = vector['bars']
        assert price_code(bars, False) == vector['as_recorded'], vector['name']
        assert price_code(bars, True) == vector['chained'], vector['name']
        for name in ORDER:
            assert part(bars, name) == vector['parts'][name], (vector['name'], name, part(bars, name))
            checked += 1
    print(f"dimension vectors: {len(document['vectors'])} windows, {checked} parts recomputed and equal")


if __name__ == '__main__':
    main()
