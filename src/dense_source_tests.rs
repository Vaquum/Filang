use super::*;
use crate::{dense_bank::Entry, rules::Mask};

struct FixtureSource {
    labels: Vec<String>,
    entries: Vec<Vec<Entry>>,
    counts: Vec<u128>,
}
impl BankSource for FixtureSource {
    fn labels(&self) -> &[String] {
        &self.labels
    }
    fn addresses(&self, bank: usize) -> Result<u128> {
        self.counts
            .get(bank)
            .copied()
            .ok_or_else(|| "fixture bank".into())
    }
    fn prepare(
        &self,
        _data: &Data,
        range: std::ops::Range<usize>,
        context: &str,
        bank: usize,
        banks: &Path,
        _backend: Backend,
    ) -> Result<()> {
        let path = record_path(banks, "bank", bank, "bin");
        if path.exists() {
            let prior = dense_bank::load(&path, &bank_context(context, bank), 1 << 20)?;
            if prior.len() != self.entries[bank].len()
                || prior
                    .iter()
                    .zip(&self.entries[bank])
                    .any(|(a, b)| a.mask != b.mask || a.count != b.count || a.first != b.first)
            {
                return Err("fixture bank changed".into());
            }
            return Ok(());
        }
        dense_bank::save(
            &self.entries[bank],
            bank_rows(&range),
            &bank_context(context, bank),
            &path,
        )?;
        Ok(())
    }
    fn validate_coordinate(&self, bank: usize, co: Coordinate, _banks: &Path) -> Result<()> {
        if bank >= self.entries.len()
            || co.atom >= self.entries[bank].len() as u64
            || co.qualifier != 0
            || co.cutoff != 0
        {
            return Err("fixture catalogue coordinate".into());
        }
        Ok(())
    }
    fn best_json(&self, best: &Best, rules: &[String], _banks: &Path) -> Result<String> {
        Ok(format!(
            "{{\"source\":\"fixture\",\"banks\":[{},{}],\"rule\":{},\"atoms\":[{},{}],\"score\":{}}}",
            best.families[0], best.families[1], quote(&rules[best.template]),
            best.coordinates[0].atom, best.coordinates[1].atom, num(best.score)
        ))
    }
    fn export_best(&self, best: &Best, rules: &[String], banks: &Path, out: &Path) -> Result<()> {
        fs::write(out.join("best.json"), self.best_json(best, rules, banks)?)
            .map_err(|e| e.to_string())
    }
    fn summary_fields(&self, _banks: &Path) -> Result<String> {
        Ok("\"source\":\"fixture\"".into())
    }
}

fn fixture() -> (Data, ExecutionConfig, FixtureSource) {
    let mut csv = String::from("timestamp,open,high,low,close,volume\n");
    for t in 0..18 {
        writeln!(
            csv,
            "{},{},{},{},{},1",
            t * 3600,
            100 + t,
            103 + t,
            99 + t,
            102 + t
        )
        .unwrap();
    }
    let data = Data::parse(&csv, 3600).unwrap();
    let rows = data.len() - 2;
    let mut entries = Vec::new();
    let mut counts = Vec::new();
    for bank in 0..2 {
        let mut empty = Mask::empty(rows);
        let mut varying = Mask::empty(rows);
        for t in 0..rows {
            empty.set(t, false, true);
            varying.set(t, t % (bank + 2) == 1, true);
        }
        let absent = if bank == 0 { (1u128 << 70) + 3 } else { 2 };
        let present = if bank == 0 { 2 } else { 3 };
        entries.push(vec![
            Entry {
                mask: empty,
                count: absent,
                first: Coordinate::default(),
            },
            Entry {
                mask: varying,
                count: present,
                first: Coordinate {
                    atom: 1,
                    ..Coordinate::default()
                },
            },
        ]);
        counts.push(absent + present);
    }
    let config = ExecutionConfig {
        rules: vec!["(and s0 s1)".into(), "(or s0 s1)".into()],
        memory: 16 << 20,
        bank_budget: 1 << 20,
        tree_budget: 1 << 20,
        block: 1,
        max_nodes: 1000,
        costs: Costs {
            fee_bps: 10.,
            slip_bps: 10.,
        },
        allow_same_bank: false,
    };
    (
        data,
        config,
        FixtureSource {
            labels: vec!["a".into(), "b".into()],
            entries,
            counts,
        },
    )
}

fn directory(name: &str) -> PathBuf {
    let unique = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    std::env::temp_dir().join(format!(
        "filang-bank-source-{name}-{}-{unique}",
        std::process::id()
    ))
}

fn digest(summary: &str) -> &str {
    summary
        .split("\"result_digest\":\"")
        .nth(1)
        .unwrap()
        .split('"')
        .next()
        .unwrap()
}

#[test]
fn generic_source_u128_nonfourhour_and_multworker_resume_match() {
    let (data, config, source) = fixture();
    let parent = directory("resume");
    fs::create_dir(&parent).unwrap();
    let direct = parent.join("direct");
    let resumed = parent.join("resumed");
    let expected = 4 * source.counts[0] * source.counts[1];
    assert!(expected > u64::MAX as u128);
    let invoke = |out: &Path, resume, max_tasks, workers| {
        run_banks(
            "fixture-v1",
            out.to_str().unwrap(),
            &data,
            0..data.len(),
            "filang-fixture-v1",
            &config,
            &source,
            resume,
            false,
            max_tasks,
            workers,
            Backend::Scalar,
            true,
            true,
        )
        .unwrap()
    };
    let a = invoke(&direct, false, 0, 1);
    let paused = invoke(&resumed, false, 1, 1);
    assert!(paused.contains("\"status\":\"PAUSED\""));
    let b = invoke(&resumed, true, 0, 10);
    assert!(b.contains("\"coverage_complete\":true"));
    assert!(b.contains(&format!("\"resolved_strategy_addresses\":\"{expected}\"")));
    assert_eq!(digest(&a), digest(&b));
    assert_eq!(
        fs::read(direct.join("best.json")).unwrap(),
        fs::read(resumed.join("best.json")).unwrap()
    );
    assert_eq!(
        fs::read(direct.join("context.chk")).unwrap(),
        fs::read(resumed.join("context.chk")).unwrap()
    );
    let again = invoke(&resumed, true, 0, 3);
    assert_eq!(digest(&b), digest(&again));
    assert!(again.contains("\"new_tasks\":0"));
    fs::remove_dir_all(parent).unwrap();
}

#[test]
fn generic_source_same_bank_and_preparation_coverage_are_explicit() {
    let (data, mut config, mut source) = fixture();
    source.labels.remove(0);
    source.entries.remove(0);
    source.counts.remove(0);
    assert!(config.validate(&source).is_err());
    config.allow_same_bank = true;
    assert_eq!(config.validate(&source).unwrap(), 50);
    let out = directory("same");
    let first = run_banks(
        "fixture-same-v1",
        out.to_str().unwrap(),
        &data,
        0..data.len(),
        "filang-fixture-v1",
        &config,
        &source,
        false,
        false,
        0,
        2,
        Backend::Scalar,
        true,
        false,
    )
    .unwrap();
    let resumed = run_banks(
        "fixture-same-v1",
        out.to_str().unwrap(),
        &data,
        0..data.len(),
        "filang-fixture-v1",
        &config,
        &source,
        true,
        false,
        0,
        1,
        Backend::Scalar,
        true,
        false,
    )
    .unwrap();
    assert_eq!(digest(&first), digest(&resumed));
    assert!(first.contains("\"resolved_strategy_addresses\":\"50\""));
    fs::remove_dir_all(out).unwrap();
    source.counts[0] += 1;
    let bad = directory("bad-coverage");
    let err = run_banks(
        "fixture-bad-v1",
        bad.to_str().unwrap(),
        &data,
        0..data.len(),
        "filang-fixture-v1",
        &config,
        &source,
        false,
        true,
        0,
        1,
        Backend::Scalar,
        true,
        false,
    )
    .unwrap_err();
    assert!(err.contains("logical coverage mismatch"));
    fs::remove_dir_all(bad).unwrap();
    source.counts[0] = u128::MAX;
    assert!(config.validate(&source).is_err());
}
