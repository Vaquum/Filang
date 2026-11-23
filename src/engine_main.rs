use filang::Result;
use std::{collections::HashMap, fs};

fn main() {
    match entry() {
        Ok(answer) => println!("{answer}"),
        Err(error) => {
            eprintln!("filang-engine: {error}");
            std::process::exit(1);
        }
    }
}

fn entry() -> Result<String> {
    let mut args = std::env::args().skip(1);
    let mut flags = HashMap::new();
    while let Some(key) = args.next() {
        if !key.starts_with("--") {
            return Err(format!("expected flag, got {key}"));
        }
        let value = args
            .next()
            .ok_or_else(|| format!("missing value for {key}"))?;
        if flags.insert(key.clone(), value).is_some() {
            return Err(format!("duplicate flag {key}"));
        }
    }
    engine_cli(flags)
}

fn take(flags: &mut HashMap<String, String>, key: &str) -> Result<String> {
    flags.remove(key).ok_or_else(|| format!("missing {key}"))
}

fn finish(flags: &HashMap<String, String>) -> Result<()> {
    match flags.keys().min() {
        Some(key) => Err(format!("unexpected flag {key}")),
        None => Ok(()),
    }
}

fn engine_cli(mut flags: HashMap<String, String>) -> Result<String> {
    use filang::engine_session::Session;

    let mut operation = take(&mut flags, "--operation")?;
    let mut session = Session::default();
    if matches!(
        operation.as_str(),
        "counts" | "neighbourhood" | "positions" | "classify" | "at" | "check" | "study"
    ) {
        let bars = take(&mut flags, "--bars")?;
        let interval = take(&mut flags, "--interval-ms")?;
        let instrument = flags
            .remove("--instrument")
            .unwrap_or_else(|| "BTCUSDT".into());
        let csv = fs::read_to_string(bars).map_err(|e| e.to_string())?;
        session.call(format!("load-csv\n{interval}\t{instrument}\n{csv}").as_bytes())?;
        if let Some(path) = flags.remove("--calendar") {
            let tsv = if path == "pinned" {
                String::new()
            } else {
                fs::read_to_string(path).map_err(|e| e.to_string())?
            };
            session.call(format!("calendar\n{tsv}").as_bytes())?;
        }
        if let Some(path) = flags.remove("--definition") {
            let definition = fs::read_to_string(path).map_err(|e| e.to_string())?;
            let sha = take(&mut flags, "--definition-sha256")?;
            session.call(format!("install-definition\n{sha}\n{definition}").as_bytes())?;
        }
    }
    let mode = flags.remove("--mode").unwrap_or_else(|| "oriented".into());
    let reading = flags
        .remove("--reading")
        .unwrap_or_else(|| "recorded".into());
    let axes = flags.remove("--dimensions").unwrap_or_default();
    let payload = match operation.as_str() {
        "version" | "catalogue" | "drawing-protocol" => String::new(),
        "inspect" => take(&mut flags, "--pattern")?,
        "distance" => {
            let left = take(&mut flags, "--pattern")?;
            let right = take(&mut flags, "--other")?;
            format!("{left}\t{right}")
        }
        "domain" => {
            let width = take(&mut flags, "--width")?;
            format!("{width}\t{mode}\t{axes}")
        }
        "counts" | "neighbourhood" => {
            let pattern = take(&mut flags, "--pattern")?;
            let radius = flags.remove("--radius").unwrap_or_else(|| "0".into());
            if operation == "counts" && radius == "0" {
                format!("{reading}\t{pattern}")
            } else {
                if operation == "counts" {
                    operation = "counts-within".into();
                }
                format!("{reading}\t{radius}\t{pattern}")
            }
        }
        "positions" | "classify" => {
            let pattern = take(&mut flags, "--pattern")?;
            let start = flags.remove("--start").unwrap_or_else(|| "0".into());
            let limit = flags.remove("--limit").unwrap_or_else(|| "100".into());
            let radius = flags.remove("--radius").unwrap_or_else(|| "0".into());
            if radius == "0" {
                format!("{reading}\t{start}\t{limit}\t{pattern}")
            } else {
                operation.push_str("-within");
                format!("{reading}\t{start}\t{limit}\t{radius}\t{pattern}")
            }
        }
        "at" => {
            let end = take(&mut flags, "--end-slot")?;
            let width = take(&mut flags, "--width")?;
            format!("{end}\t{width}\t{mode}\t{reading}\t{axes}")
        }
        "study" | "check" => {
            let path = take(&mut flags, "--query")?;
            let query = fs::read_to_string(path).map_err(|e| e.to_string())?;
            if operation == "study" {
                let candidate = flags.remove("--candidate").unwrap_or_else(|| "-".into());
                format!("{candidate}\n{query}")
            } else {
                query
            }
        }
        "read-drawing" => {
            let path = take(&mut flags, "--input")?;
            let packet = fs::read_to_string(path).map_err(|e| e.to_string())?;
            let expected = flags.remove("--pattern").unwrap_or_default();
            format!("{expected}\n{packet}")
        }
        "draw" => {
            let path = take(&mut flags, "--input")?;
            fs::read_to_string(path)
                .map_err(|e| e.to_string())?
                .trim_end_matches(['\n', '\r'])
                .to_owned()
        }
        _ => return Err(format!("unknown engine operation {operation}")),
    };
    finish(&flags)?;
    session.call(format!("{operation}\n{payload}").as_bytes())
}
