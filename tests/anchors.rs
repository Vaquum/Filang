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

#[test]
fn existing_open_generator_uses_the_same_family_compiler() {
    let mut cfg = filang::config::Config::parse(include_str!("../examples/btc4h.cfg")).unwrap();
    cfg.generated = 64;
    let (g, rows, _) = filang::search::generate(&cfg).unwrap();
    let roots = rows
        .iter()
        .filter(|r| r.group == "generated")
        .take(16)
        .map(|r| r.root)
        .collect::<Vec<_>>();
    let d = Data {
        timestamps: (0..1501).collect(),
        columns: std::array::from_fn(|j| {
            (0..1501)
                .map(|t| 100.0 + j as f64 + (t as f64 / (7.0 + j as f64)).sin() + 0.001 * t as f64)
                .collect()
        }),
        interval: 1,
        digest: "open-generator-corpus".into(),
    };
    let direct = engine::evaluate(&g, &d, &roots, 32 * 1024 * 1024).unwrap();
    let store = family::prepare(
        &g,
        &d,
        &family::boundaries(&g, &roots),
        32 * 1024 * 1024,
        Backend::resolve("auto").unwrap(),
        None,
    )
    .unwrap();
    for root in roots {
        let p = family::Program::compile(&g, root, &store, None).unwrap();
        let value = p
            .execute(&store, None, &[], Backend::resolve("auto").unwrap(), true)
            .unwrap()
            .1
            .unwrap();
        for (a, b) in value.iter().zip(&direct.values[&root]) {
            assert!(a.to_bits() == b.to_bits() || (a.is_nan() && b.is_nan()));
        }
    }
}
#[test]
fn parity_gate_binds_evidence_catalog_engine_and_data() {
    use filang::{anchor_run, hash::sha256};
    use std::fs;
    let dir = std::env::temp_dir().join(format!("filang-gate-test-{}", std::process::id()));
    fs::create_dir_all(&dir).unwrap();
    let mut fields = vec![
        ("version", "1".to_owned()),
        ("status", "PASS".to_owned()),
        ("data_sha256", "fixture".to_owned()),
        ("engine_sha256", anchor_run::engine_id().unwrap()),
        ("catalog_sha256", anchor_run::catalog_id().unwrap()),
    ];
    for (name, key) in [
        ("manifest.json", "manifest_sha256"),
        ("metrics.bin", "metrics_sha256"),
        ("verification.json", "verification_sha256"),
    ] {
        fs::write(
            dir.join(name),
            b"unit test identity fixture, not external parity evidence",
        )
        .unwrap();
        fields.push((key, sha256(&fs::read(dir.join(name)).unwrap())));
    }
    let text = fields
        .iter()
        .map(|(k, v)| format!("{k}={v}\n"))
        .collect::<String>();
    let path = dir.join("gate.txt");
    fs::write(&path, &text).unwrap();
    fs::write(dir.join("gate.txt.sha256"), sha256(text.as_bytes())).unwrap();
    assert!(anchor_run::validate_gate(path.to_str().unwrap(), "fixture").is_ok());
    assert!(anchor_run::validate_gate(path.to_str().unwrap(), "another-dataset").is_err());
    fs::write(dir.join("metrics.bin"), b"altered").unwrap();
    assert!(anchor_run::validate_gate(path.to_str().unwrap(), "fixture").is_err());
    fs::remove_dir_all(dir).unwrap();
}
