use super::*;

#[test]
fn bitwise_qualifiers_match_scalar_at_word_edges_and_invalid_gaps() {
    let mut random = 0xa568d2f903bc417eu64;
    for len in [0, 1, 2, 31, 63, 64, 65, 127, 128, 129, 257] {
        for prefix in [0, 1, 17, 63, 64, 65] {
            let mut mask = Mask::empty(len);
            for t in 0..len {
                random = random.wrapping_mul(6364136223846793005).wrapping_add(1);
                mask.set(
                    t,
                    random >> 33 & 1 != 0,
                    t >= prefix && random >> 12 & 7 != 0,
                );
            }
            let mut qualifiers = vec![Qualifier::Plain, Qualifier::Onset];
            for n in [1, 2, 3, 5, 7, 16, 31, 63, 64, 65, 127, 128, 129, 100000] {
                qualifiers.push(Qualifier::Recent(n));
                qualifiers.push(Qualifier::Persist(n));
            }
            for &q in &qualifiers {
                assert_eq!(
                    qualify(&mask, q).unwrap(),
                    mask.qualify(q).unwrap(),
                    "len={len} prefix={prefix} q={q:?}"
                );
            }
            // Long true runs must survive persistence across word boundaries;
            // random masks alone rarely produce even one such positive result.
            for gap in [None, Some(64), Some(128)] {
                for t in 0..len {
                    mask.set(t, gap != Some(t), t >= prefix);
                }
                for &q in &qualifiers {
                    assert_eq!(
                        qualify(&mask, q).unwrap(),
                        mask.qualify(q).unwrap(),
                        "long run len={len} prefix={prefix} gap={gap:?} q={q:?}"
                    );
                }
            }
        }
    }
    let mask = Mask::empty(65);
    assert!(qualify(&mask, Qualifier::Persist(0)).is_err());
    assert!(qualify(&mask, Qualifier::Recent(100001)).is_err());
}

fn fixture() -> (Data, Config) {
    let start = data::date("2020-01-01").unwrap();
    let mut csv = String::from("timestamp,open,high,low,close,volume\n");
    for t in 0..32i64 {
        let open = 100 + t * 7 % 11;
        let close = if t % 5 == 0 { open } else { open + t % 3 - 1 };
        let high = open.max(close) + t % 2;
        let low = open.min(close) - (t + 1) % 2;
        writeln!(csv, "{},{open},{high},{low},{close},1", start + t * 86400).unwrap();
    }
    let data = Data::parse(&csv, 86400).unwrap();
    let config = Config::parse(concat!(
        "version=1\ndata=fixture.csv\ninterval_seconds=86400\nstart=2020-01-11\nend=2020-02-02\n",
        "mode=unoriented\nwindows=0,1,2,3,4,5;0\nqualifiers=plain,persist:2,recent:3,onset\n",
        "rules=(and s0 s1);(or s0 s1)\nallow_same_bank=false\nnumeric_mib=16\nbank_mib=2\n",
        "tree_mib=2\nprepare_mib=4\ntask_states=1\nmax_task_nodes=100000\nfee_bps=10\nslip_bps=10\n"
    ))
    .unwrap();
    (data, config)
}
fn directory(label: &str) -> std::path::PathBuf {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    std::env::temp_dir().join(format!(
        "filang-geometry-preparation-{label}-{}-{stamp}",
        std::process::id()
    ))
}

#[test]
fn causal_prefix_complement_and_u128_memberships_reconstruct_scalar_masks() {
    let (data, config) = fixture();
    let range = config.validate_data(&data).unwrap();
    let cut = range.end - 2;
    let dir = directory("parity");
    fs::create_dir(&dir).unwrap();
    let _lock = dense_io::Lock::acquire(&dir).unwrap();
    let context = "d".repeat(64);
    let source = Source::new(&config).unwrap();
    source
        .prepare(&data, range.clone(), &context, 0, &dir, Backend::Scalar)
        .unwrap();
    let committed = fs::read(record_path(&dir, "prepared", 0, "chk")).unwrap();
    source
        .prepare(&data, range.clone(), &context, 0, &dir, Backend::Scalar)
        .unwrap();
    assert_eq!(
        committed,
        fs::read(record_path(&dir, "prepared", 0, "chk")).unwrap()
    );
    let metadata = read_marker(&config, &range, &context, 0, &dir, true).unwrap();
    assert!(metadata.unobserved_patterns > u64::MAX as u128);
    let entries = dense_bank::load(
        &record_path(&dir, "bank", 0, "bin"),
        &bank_context(&context, 0),
        config.bank_budget,
    )
    .unwrap();
    let members = String::from_utf8(
        dense_io::read(
            &record_path(&dir, "members", 0, "tsv"),
            config.prepare_budget,
        )
        .unwrap(),
    )
    .unwrap();
    let mut total = 0u128;
    let mut memberships = 0u64;
    for line in members.lines().skip(1) {
        let fields = line.split('\t').collect::<Vec<_>>();
        let id = fields[0].parse::<u64>().unwrap();
        let qindex = fields[1].parse::<usize>().unwrap();
        let state = fields[2].parse::<usize>().unwrap();
        let multiplicity = fields[3].parse::<u128>().unwrap();
        let (pattern, kind, expected_multiplicity) = source.pattern(0, id, &dir).unwrap();
        assert_eq!(multiplicity, expected_multiplicity);
        let mut raw = Mask::empty(cut);
        for t in 5..cut {
            let rows = config.windows[0]
                .iter()
                .map(|&lag| {
                    let i = t - lag;
                    [
                        data.columns[0][i],
                        data.columns[1][i],
                        data.columns[2][i],
                        data.columns[3][i],
                    ]
                })
                .collect::<Vec<_>>();
            raw.set(t, pattern.matches_ohlc(&rows).unwrap(), true);
        }
        if kind == "unobserved" {
            assert!(raw.bits.iter().all(|&w| w == 0));
        }
        let expected = raw
            .qualify(config.qualifiers[qindex])
            .unwrap()
            .slice(range.start, cut)
            .unwrap();
        assert!(
            expected.at(0).1,
            "warmup must supply complete qualifier history"
        );
        assert_eq!(expected, entries[state].mask);
        total += multiplicity;
        memberships += 1;
    }
    assert_eq!(memberships, metadata.physical_memberships);
    assert_eq!(total, config.per_bank(0).unwrap());
    assert_eq!(entries.iter().map(|e| e.count).sum::<u128>(), total);
    assert!(entries
        .iter()
        .any(|e| e.count >= metadata.unobserved_patterns * config.qualifiers.len() as u128));
    assert!(metadata.states < metadata.physical_memberships);
    assert!(source
        .validate_coordinate(
            0,
            Coordinate {
                atom: metadata.catalogue_records,
                qualifier: 0,
                cutoff: 0
            },
            &dir
        )
        .is_err());
    let stats = record_path(&dir, "preparation", 0, "json");
    fs::OpenOptions::new()
        .append(true)
        .open(stats)
        .unwrap()
        .write_all(b" ")
        .unwrap();
    assert!(source
        .prepare(&data, range, &context, 0, &dir, Backend::Scalar)
        .unwrap_err()
        .contains("statistics changed"));
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn geometry_resource_and_boundary_rejections_are_explicit() {
    let (mut data, mut config) = fixture();
    assert!(config.logical().unwrap() > u64::MAX as u128);
    let range = config.validate_data(&data).unwrap();
    let dir = directory("budget");
    fs::create_dir(&dir).unwrap();
    config.prepare_budget = 1024;
    assert!(
        prepare_bank(&config, &data, range, &"f".repeat(64), 0, &dir)
            .unwrap_err()
            .contains("preparation budget exceeded")
    );
    assert!(!record_path(&dir, "prepared", 0, "chk").exists());
    fs::remove_dir_all(dir).unwrap();
    config.prepare_budget = 4 << 20;
    config.start += 1;
    assert!(config.validate_data(&data).is_err());
    config.start -= 1;
    data.timestamps.push(config.end);
    assert!(config.validate_data(&data).is_err());
    config.windows = vec![vec![0, 1], vec![0, 1]];
    assert!(config.validate().is_err());
    config.windows = vec![vec![0, 2, 1], vec![0]];
    assert!(config.validate().is_err());
    config.windows = vec![vec![0, 1], vec![0]];
    config.qualifiers.push(config.qualifiers[0]);
    assert!(config.validate().is_err());
}
