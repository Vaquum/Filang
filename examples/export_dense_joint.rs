//! Export a small dense domain into the ordinary joint runtime for a matched oracle.
//! This is authoring only: both evaluators receive the same ordinary expressions.
use filang::{cohort, dense_run::Config, Result};
use std::{env, fmt::Write, fs, path::Path};
fn run() -> Result<()> {
    let args: Vec<_> = env::args().collect();
    if args.len() != 3 {
        return Err("export_dense_joint DENSE_CONFIG NEW_OUTPUT_DIRECTORY".into());
    }
    let c = Config::parse(&fs::read_to_string(&args[1]).map_err(|e| e.to_string())?)?;
    let dir = Path::new(&args[2]);
    fs::create_dir(dir).map_err(|e| e.to_string())?;
    let count = 2 * c.families.len() * c.atoms() as usize * c.qualifiers.len();
    if count > 4096 {
        return Err("ordinary joint fixed-catalog limit: use small oracle domain".into());
    }
    let mut text = String::new();
    for slot in 0..2 {
        for (f, kind) in c.families.iter().enumerate() {
            for atom in 0..c.atoms() {
                let (n, a, b) = c.parameters(kind, atom)?;
                let (mut g, ids) = cohort::stripe(kind, n, a)?;
                let r = cohort::output(&mut g, kind, ids, b, cohort::defaults(kind)?.1)?;
                let expr = g.expression(g.nodes[r].args[0]);
                for (q, qual) in c.qualifier_text.split(',').enumerate() {
                    writeln!(
                        &mut text,
                        "{slot}\tf{f}-a{atom}-q{q}\t{kind}\tthreshold:gt\t{qual}\t{}\t{expr}\t-",
                        c.grid(kind)?.text()
                    )
                    .map_err(|e| e.to_string())?;
                }
            }
        }
    }
    fs::write(dir.join("parameters.tsv"), text).map_err(|e| e.to_string())?;
    fs::write(dir.join("rules.txt"), c.rules.join("\n") + "\n").map_err(|e| e.to_string())?;
    // Source date spelling is retained exactly from the validated input config.
    let raw = fs::read_to_string(&args[1]).map_err(|e| e.to_string())?;
    let val = |key: &str| {
        raw.lines()
            .filter_map(|l| l.split_once('='))
            .find(|(k, _)| *k == key)
            .map(|(_, v)| v)
            .ok_or_else(|| format!("missing {key}"))
    };
    let cfg=format!("version=1\ndata={}\nout=unused\nparameters={}\ntemplates={}\nstart={}\nend={}\ninterval_seconds=14400\ncosts={}:{}\nmemory_mib=128\ncache_mib=0\ndifferent_tags=true\nplan=cofactor\nbackend=auto\noutput=boxes\ncapture=true\ngate=unused\nmax_boxes=100000000\n",c.data,dir.join("parameters.tsv").display(),dir.join("rules.txt").display(),val("start")?,val("end")?,c.costs.fee_bps,c.costs.slip_bps);
    fs::write(dir.join("sweep.cfg"), cfg).map_err(|e| e.to_string())?;
    println!("{count} options; {} logical strategies", c.logical()?);
    Ok(())
}
fn main() {
    if let Err(e) = run() {
        eprintln!("{e}");
        std::process::exit(1)
    }
}
