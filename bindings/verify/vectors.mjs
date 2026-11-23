const axes = ["volume", "trades", "delta", "size", "imbalance"];

function equal(actual, expected, label) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${label}: got ${JSON.stringify(actual)}, expected ${JSON.stringify(expected)}`);
  }
}

export function verifyVectors(engine, chained, dimensioned) {
  let checked = 0;
  for (const vector of [...chained.vectors, ...dimensioned.vectors]) {
    const width = vector.bars.length;
    equal(engine.load(vector.bars), {slots: width}, vector.name);
    for (const reading of ["recorded", "chained"]) {
      const base = vector[reading === "chained" ? "chained" : "as_recorded"];
      for (let bits = 0; bits < (vector.parts ? 32 : 1); bits++) {
        const dimensions = axes.filter((_, i) => bits & (1 << i));
        const parts = dimensions.map((axis) => vector.parts[axis]);
        const expected = parts.includes(null) ? null : [base, ...parts].join("|");
        const label = [vector.name, reading, ...dimensions].join(" ");
        const result = engine.at(width - 1, width, {reading, dimensions});
        equal(result?.code ?? null, expected, label);
        if (result) {
          equal(engine.inspect(expected), result, label);
          equal(result.words.length, 4 + dimensions.length, label);
          equal(engine.counts(expected, {reading}), {
            matched: 1, false_count: 0, unknown: width - 1,
          }, label);
          equal(engine.positions(expected, {reading}), [width - 1], label);
        }
        checked++;
      }
    }
  }
  return checked;
}
