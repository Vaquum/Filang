use super::*;
fn config(count: usize, cutoffs: u64) -> String {
    format!("version=1\ndata=unused.csv\nstart=1970-02-10\nend=1970-02-20\nfamilies=sma,ema\ncoefficients={count}\ncutoffs={cutoffs}\nqualifiers=plain,persist:2,recent:3\nrules=(and s0 s1);(or s0 s1);(and s0 (not s1))\nnumeric_mib=32\nbank_mib=16\ntree_mib=32\ntask_states=3\nmax_task_nodes=1000000\nfee_bps=10\nslip_bps=10\n")
}
#[test]
fn dense_domains_and_u128_are_exact() {
    let text = config(41, 20001).replace(
        "families=sma,ema",
        &format!("families={}", cohort::KINDS.join(",")),
    );
    let c = Config::parse(&text).unwrap();
    assert_eq!(c.atoms(), 5043);
    assert_eq!(c.logical().unwrap(), 24722229265522193070u128);
    assert!(c.logical().unwrap() > u64::MAX as u128);
    assert_eq!(c.parameters("sma", 0).unwrap(), (199, -0.01, 0.));
    assert_eq!(
        c.parameters("sma", c.atoms() - 1).unwrap(),
        (201, 0.01, 0.1)
    );
    assert!(Config::parse(&config(7, 20001)).is_err());
    assert!(Config::parse(&config(3, 2)).is_err());
}
#[test]
fn prepared_aliases_and_committed_task_replay() {
    use crate::{engine, rules::Predicate};
    let dir = std::env::temp_dir().join(format!("filang-dense-run-{}", std::process::id()));
    fs::create_dir_all(&dir).unwrap();
    let lock = dense_io::Lock::acquire(&dir).unwrap();
    let raw = include_str!("../tests/fixtures/cohort_ohlcv.csv")
        .lines()
        .take(301)
        .collect::<Vec<_>>()
        .join("\n")
        + "\n";
    let d = Data::parse(&raw, 14400).unwrap();
    let c = Config::parse(&config(3, 3)).unwrap();
    let range = d.index(c.start)..d.len();
    let context = "b".repeat(64);
    for f in 0..2 {
        prepared(&c, &d, range.clone(), &context, f, &dir, Backend::Scalar).unwrap();
        prepared(&c, &d, range.clone(), &context, f, &dir, Backend::Scalar).unwrap();
        let entries = dense_bank::load(
            &record_path(&dir, "bank", f, "bin"),
            &bank_context(&context, f),
            c.bank_budget,
        )
        .unwrap();
        let bytes = dense_io::read(&record_path(&dir, "members", f, "bin"), 1 << 24).unwrap();
        let mut r = Reader::new(&bytes);
        assert_eq!(r.bytes(8).unwrap(), b"FDALIAS1");
        assert_eq!(r.bytes(64).unwrap(), bank_context(&context, f).as_bytes());
        for v in [
            c.atoms(),
            c.qualifiers.len() as u64,
            c.cutoffs,
            bank_rows(&range) as u64,
        ] {
            assert_eq!(r.u64().unwrap(), v);
        }
        let mut coverage = 0u128;
        let mut next = (0, 0, 0);
        for _ in 0..(bytes.len() - 104) / 40 {
            let atom = r.u64().unwrap();
            let q = r.u64().unwrap();
            let lo = r.u64().unwrap();
            let hi = r.u64().unwrap();
            let id = r.u64().unwrap() as usize;
            assert_eq!((atom, q, lo), next);
            let (n, a, b) = c.parameters(&c.families[f], atom).unwrap();
            let (mut g, ids) = cohort::stripe(&c.families[f], n, a).unwrap();
            let root = cohort::output(
                &mut g,
                &c.families[f],
                ids,
                b,
                cohort::defaults(&c.families[f]).unwrap().1,
            )
            .unwrap();
            let xroot = g.nodes[root].args[0];
            let batch = engine::evaluate(&g, &d, &[xroot], c.memory).unwrap();
            for j in lo..hi {
                let want = Predicate::Threshold(Cmp::Gt)
                    .evaluate(
                        &batch.values[&xroot],
                        None,
                        c.grid(&c.families[f]).unwrap().value(j),
                        &[c.qualifiers[q as usize]],
                    )
                    .unwrap()
                    .slice(range.start, range.end - 2)
                    .unwrap();
                assert_eq!(want, entries[id].mask);
            }
            coverage += (hi - lo) as u128;
            if hi < c.cutoffs {
                next = (atom, q, hi);
            } else if q + 1 < c.qualifiers.len() as u64 {
                next = (atom, q + 1, 0);
            } else {
                next = (atom + 1, 0, 0);
            }
        }
        r.end().unwrap();
        assert_eq!(coverage, c.per_family());
        assert_eq!(entries.iter().map(|e| e.count).sum::<u128>(), coverage);
    }
    let a = dense_bank::load(
        &record_path(&dir, "bank", 0, "bin"),
        &bank_context(&context, 0),
        c.bank_budget,
    )
    .unwrap();
    let b = dense_bank::load(
        &record_path(&dir, "bank", 1, "bin"),
        &bank_context(&context, 1),
        c.bank_budget,
    )
    .unwrap();
    let left = Tree::new(&a, c.tree_budget).unwrap();
    let right = Tree::new(&b, c.tree_budget).unwrap();
    let market = crate::backtest::Market::new(&d, range.start, range.end, c.costs).unwrap();
    let p = Program::parse(&c.rules[1], 2).unwrap();
    let table = Table::from_program(&p).unwrap();
    dense_tree::visit(
        &left,
        &right,
        left.root,
        right.root,
        table,
        true,
        c.max_nodes,
        |r, words| {
            for i in left.nodes[r.left].lo..left.nodes[r.left].hi {
                for j in right.nodes[r.right].lo..right.nodes[r.right].hi {
                    let m = p.evaluate(
                        &[&a[left.order[i]].mask, &b[right.order[j]].mask],
                        Backend::Scalar,
                    )?;
                    assert_eq!(m.bits, words);
                    let pos = (0..m.len).map(|t| m.at(t).0).collect::<Vec<_>>();
                    let ledger = market.position_ledger(&pos)?;
                    let reference = crate::backtest::metrics_from_ledger(&ledger, d.interval)?;
                    let mut ex = Executor::new(
                        &d,
                        range.clone(),
                        vec![],
                        &[c.costs],
                        Backend::Scalar,
                        Scorer::Auto,
                        c.memory,
                    )?;
                    let got = ex.score_positions(words)?;
                    for (x, y) in metric_values(&reference, d.interval)
                        .iter()
                        .zip(metric_values(&got[0], d.interval))
                    {
                        assert!(
                            (x.is_nan() && y.is_nan()) || (x - y).abs() <= 1e-7 + 1e-9 * x.abs()
                        );
                    }
                }
            }
            Ok(())
        },
    )
    .unwrap();
    let t = task(
        &c,
        &d,
        range.clone(),
        &context,
        &dir,
        0,
        [0, 1],
        1,
        &left,
        &right,
        left.root,
        Backend::Scalar,
        true,
        true,
    )
    .unwrap();
    let again = task(
        &c,
        &d,
        range.clone(),
        &context,
        &dir,
        0,
        [0, 1],
        1,
        &left,
        &right,
        left.root,
        Backend::Scalar,
        true,
        true,
    )
    .unwrap();
    assert_eq!(t.encode(&context), again.encode(&context));
    assert!(task(
        &c,
        &d,
        range,
        &"a".repeat(64),
        &dir,
        0,
        [0, 1],
        1,
        &left,
        &right,
        left.root,
        Backend::Scalar,
        true,
        true
    )
    .is_err());
    drop(lock);
    fs::remove_dir_all(dir).unwrap();
}
