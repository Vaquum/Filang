use filang::{
    anchors,
    data::Data,
    engine, family,
    kernels::Backend,
    lang::{Graph, Op},
};
#[test]
fn anchored_profiles_keep_every_legacy_definition_and_immutable_neighbors() {
    let (g, a) = anchors::catalog().unwrap();
    assert_eq!(a.len(), 18);
    let (ng, n) = anchors::neighborhood(2, 17).unwrap();
    for row in &a {
        assert!(n.iter().any(|v| v.key == row.key
            && ng.expression(v.root) == g.expression(row.root)
            && v.rules.len() == row.rules.len()));
    }
    assert!(anchors::neighborhood(33, 17).is_err());
    assert!(anchors::neighborhood(1, 4).is_err());
    for row in &a {
        let mut decoded = Graph::new();
        let root = decoded.parse(&g.expression(row.root)).unwrap();
        assert_eq!(decoded.identity(root), g.identity(row.root));
    }
}
#[test]
fn raw_profile_is_explicit_and_zero_cases_keep_their_contract() {
    let mut g = Graph::new();
    let c = g.source(3);
    let m = g.unary(Op::MeanSum(8), c);
    let s = g.unary(Op::StdSum(8), c);
    let zero = g.constant(0.0);
    let q = g.binary(Op::Div0, zero, zero);
    let d = Data {
        timestamps: (0..50).collect(),
        columns: std::array::from_fn(|_| vec![100.; 50]),
        interval: 1,
        digest: "flat".into(),
    };
    let plain = engine::evaluate(&g, &d, &[m, s, q], 1_000_000).unwrap();
    let fast = family::prepare(
        &g,
        &d,
        &[m, s, q],
        1_000_000,
        Backend::resolve("auto").unwrap(),
        None,
    )
    .unwrap();
    for id in [m, s, q] {
        for (a, b) in plain.values[&id].iter().zip(fast.series(id, None).unwrap()) {
            assert!(a.to_bits() == b.to_bits() || (a.is_nan() && b.is_nan()));
        }
    }
    assert_eq!(plain.values[&m][7], 100.);
    assert_eq!(plain.values[&s][7], 0.);
    assert_eq!(plain.values[&q][0], 0.);
    assert!(g.add(Op::MeanSum(0), vec![c]).is_err());
    assert!(g.add(Op::StdSum(0), vec![c]).is_err());
}
