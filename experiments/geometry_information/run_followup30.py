#!/usr/bin/env python3
"""Produce the frozen F30-D1 matched score-adaptation follow-up.

Only the original selected 30m R1a predictions are fitted by this follow-up.
Source admission and a published clean implementation are mandatory. All
consumed predecessor/native bytes are copied into a self-contained scoped
bundle; raw Parquet and prepared CSV remain externally pinned inputs.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time
import traceback

THREAD_VARIABLES = ("VECLIB_MAXIMUM_THREADS", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS",
                    "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")
for _thread_variable in THREAD_VARIABLES:
    os.environ[_thread_variable] = "2"

import numpy as np

import common
import followup30 as d


PROTOCOL_SHA256 = "4099e7a6620387d0fbe2267819ca0d37dff0f52da3e6bf8689705e979adf497b"
FREEZE_COMMIT = "ed7e0b9bccedebc6bda75d7ab701829a6a708c5f"
PROTOCOL_PATH = "experiments/geometry_information/followup30_protocol.json"
YEARS = (2023, 2024, 2025, 2026)


def file_record(path):
    return {"bytes": Path(path).stat().st_size, "sha256": d.digest(path)}


def bounded(root, relative):
    root, relative = Path(root).resolve(), Path(relative)
    d.require(not relative.is_absolute() and ".." not in relative.parts, "artifact path must be relative and contained")
    path = (root / relative).resolve()
    d.require(root in path.parents, "artifact path escapes its root")
    return path


def validate_output_destination(output, input_roots):
    """Prevent a fresh run from adding files inside any immutable input tree."""
    output = Path(output).resolve()
    for source in input_roots:
        source = Path(source).resolve()
        d.require(output != source and output not in source.parents and source not in output.parents,
                  "output must not overlap an immutable input root: "+str(source))
    return output


def assert_numeric(actual, expected, label):
    actual, expected = np.asarray(actual), np.asarray(expected)
    d.require(actual.shape == expected.shape and actual.dtype == expected.dtype, label+" shape/dtype")
    if expected.dtype.kind in "biu":
        d.require(np.array_equal(actual, expected), label+" exact values")
    else:
        d.require(np.array_equal(np.isnan(actual), np.isnan(expected)), label+" NaN placement")
        mask = np.isfinite(expected)
        d.require(np.isfinite(actual[mask]).all() and np.all(np.abs(actual[mask]-expected[mask]) <= 1e-10+1e-10*np.abs(expected[mask])),
                  label+" numerical values")


def validate_phase(arrays, sidecar, fold, phase, source, keys, original_protocol_sha):
    year, n = fold["year"], source["rows"]
    d.require(set(arrays) == set(d.SOURCE_ARRAYS), "original prediction member coverage")
    d.require(set(sidecar["arrays"]) == set(arrays), "original prediction sidecar member coverage")
    for name, dtype in d.SOURCE_ARRAYS.items():
        a = arrays[name]
        d.require(a.shape == (n,) and a.dtype.str == dtype, "original prediction shape/dtype "+name)
        d.require(d.array_record(a) == sidecar["arrays"][name], "original prediction array identity "+name)
    start, end = d.epoch(fold[f"{phase}_start"]), d.epoch(fold[f"{phase}_end_exclusive"])
    expected = common.phase_labels(source, keys["valid"], start, end)
    for name, values in expected.items():
        assert_numeric(arrays[name], values, "original phase "+name)
    forecast = arrays["phase_mask"] & arrays["causal_feature_valid"]
    for name in ("p_B", "p_G", "logit_B", "logit_G", "p_unconditional", "p_lag1"):
        d.require(np.array_equal(np.isfinite(arrays[name]), forecast), "original full-row availability "+name)
        d.require(np.isnan(arrays[name][~forecast]).all(), "invalid original forecast must be NaN")
        if name.startswith("p_"):
            d.require(np.all((arrays[name][forecast] > 0) & (arrays[name][forecast] < 1)), "original probability domain")
    for family in d.FAMILIES:
        assert_numeric(arrays[f"p_{family}"][forecast], d.sigmoid(arrays[f"logit_{family}"][forecast]), "original logistic link")
    expected_sidecar = {"schema": "filang-information-predictions-v1", "minutes": 30, "outer_year": year,
        "phase": phase, "phase_start": start, "phase_end_exclusive": end,
        "source_sha256": source["sha256"], "protocol_sha256": original_protocol_sha,
        "native_keys_sha256": keys["keys_sha256"]}
    for name, value in expected_sidecar.items():
        d.require(sidecar[name] == value, "original prediction sidecar "+name)
    return expected


def validate_prediction_model(binding, model, phase, expected_file_sha):
    stage = "inner" if phase == "validation" else "refit"
    d.require(phase in ("validation", "outer") and model["stage"] == stage, "prediction model vintage")
    d.require(binding == {"fit_id": model["fit_id"], "coefficient_sha256": model["coefficient_sha256"],
        "path": model["path"], "file_sha256": expected_file_sha}, "prediction model vintage/binding")


def load_archived_source(provenance_path, expected_sha256, data_root, source_specification):
    """Bind archived provenance while validating relocatable source bytes.

    Fresh preparation metadata can contain different absolute local paths. Its
    bytes are not the archived provenance identity and are not substituted for
    that record. The archived record's raw/CSV hashes, counts and gaps remain
    authoritative for the files actually opened at the supplied data root.
    """
    d.require(d.digest(provenance_path) == expected_sha256, "original archived source provenance binding")
    return common.load_source(data_root, source_specification, d.read_json(provenance_path))


def admit_inputs(r1a_root, data_root, keys_root, protocol, out):
    """Admit immutable consumed bytes and copy exactly those bytes into out."""
    r1a_root, data_root, keys_root = (Path(p).resolve() for p in (r1a_root, data_root, keys_root))
    predecessor = protocol["predecessor"]
    consumed, copies = {}, {}
    for name, identity in predecessor["required_root_files"].items():
        path = bounded(r1a_root, name)
        d.require(file_record(path) == identity, "pinned original root identity "+name)
        consumed[name] = identity
    manifest = d.read_json(r1a_root / "manifest.json")
    d.require(manifest["schema"] == "filang-information-run-manifest-v1", "original manifest schema")
    d.require((r1a_root / "manifest.sha256").read_text() == d.digest(r1a_root / "manifest.json")+"\n", "original manifest seal")

    def consume(relative):
        path = bounded(r1a_root, relative)
        identity = file_record(path)
        if relative not in predecessor["required_root_files"]:
            d.require(relative in manifest["files"], "unsealed consumed original file "+relative)
            record = manifest["files"][relative]
            d.require(identity == {k: record[k] for k in ("bytes", "sha256")}, "original manifest file identity "+relative)
        else:
            d.require(identity == predecessor["required_root_files"][relative], "original root changed "+relative)
        consumed[relative] = identity
        return path

    old_run, old_analysis, old_audit = (d.read_json(consume(name)) for name in ("run.json", "analysis.json", "verification.json"))
    old_protocol = d.read_json(consume("protocol.json"))
    old_sha = predecessor["protocol_sha256"]
    d.require(old_run["status"] == old_analysis["status"] == "COMPLETE_PENDING_INDEPENDENT_AUDIT", "original complete producer status")
    d.require(old_run["freeze_commit"] == predecessor["freeze_commit"] and old_run["protocol_sha256"] == old_sha,
              "original freeze binding")
    d.require(old_run["implementation"]["git_head"] == predecessor["execution_commit"], "original execution binding")
    d.require(old_run["implementation"]["worktree_status_porcelain"] == "", "original clean execution")
    d.require(d.object_sha(old_run["implementation"]["files"]) == old_run["implementation"]["sha256"], "original implementation hash")
    d.require(old_protocol["attempt_id"] == "R1a" and old_analysis["protocol_sha256"] == old_sha, "original attempt/analysis binding")
    d.require(old_audit["schema"] == "filang-geometry-information-verification-v1" and old_audit["status"] == "PASS"
              and old_audit["stage"] == "full" and old_audit["scientific_models_checked"] is True, "original full audit required")
    d.require(old_audit["protocol_sha256"] == old_sha
              and old_audit["producer_manifest_sha256"] == d.digest(r1a_root / "manifest.json")
              and old_audit["analysis_sha256"] == d.digest(r1a_root / "analysis.json"), "original audit exact binding")
    d.require(old_audit["audited_timeframes"] == [15, 30, 60, 120, 240] and old_audit["audited_outer_years"] == list(YEARS),
              "original audit timeframe/year coverage")
    required_coverage = {"native_keys": 458972, "candidate_fits": 640, "refit_fits": 40, "outer_predictions": 20,
                         "validation_predictions": 20, "ledger_replays": 960, "all_records": True, "sampled": False}
    d.require(old_audit["coverage"] == required_coverage and all(v is True for v in old_audit["checks"].values()), "original audit complete checks")
    provenance_path = consume("provenance.json")
    source = load_archived_source(provenance_path, old_run["source_provenance_sha256"], data_root, protocol["data"]["source"])
    native_folder = keys_root / "30m"
    keys = common.decode_keys(native_folder, source, d.epoch(protocol["data"]["history_start"]), d.epoch(protocol["data"]["end_exclusive"]))
    native_pins = protocol["data"]["native"]
    d.require(keys["keys_sha256"] == native_pins["keys_sha256"] and keys["context_sha256"] == native_pins["context_sha256"]
              and keys["manifest_sha256"] == native_pins["manifest_sha256"] and len(keys["indices"]) == native_pins["records"]
              and (native_folder / "keys.bin").stat().st_size == native_pins["keys_bytes"], "exact original native artifact binding")
    for name in ("features.json", "30m/features.json"):
        consume(name)
    global_selected = d.read_json(consume("selected.json"))["selections"]
    timeframe_selected = d.read_json(consume("30m/selected.json"))["selections"]
    d.require(len(global_selected) == 40 and len(timeframe_selected) == 8, "original selection record coverage")
    phases, phase_bindings = {}, []
    selected_models = {}
    for fold in protocol["target_and_phases"]["outer_folds"]:
        year = fold["year"]
        choices = {}
        for family in d.FAMILIES:
            path = f"30m/{year}/{family}/selected.json"
            choice = d.read_json(consume(path))
            d.require(choice["outer_year"] == year and choice["family"] == family and choice["minutes"] == 30, "selection ownership")
            d.require(sum(record == choice for record in global_selected) == 1
                      and sum(record == choice for record in timeframe_selected) == 1, "global/scoped selection identity")
            choices[family] = choice
            for stage in ("inner", "refit"):
                relative = choice[f"{stage}_model_path"]
                model = d.read_json(consume(relative))
                d.require(relative == model["path"] and model["fit_id"] == choice[f"{stage}_fit_id"], "selected model identity")
                d.require(model["minutes"] == 30 and model["outer_year"] == year and model["family"] == family
                          and model["stage"] == stage and model["n"] == choice["n"] and model["lambda"] == choice["lambda"],
                          "selected model vintage/parameters")
                bounds = ("inner_train_start", "inner_train_end_exclusive") if stage == "inner" else ("refit_start", "refit_end_exclusive")
                d.require(model["fit_start"] == d.epoch(fold[bounds[0]]) and model["fit_end_exclusive"] == d.epoch(fold[bounds[1]]),
                          "selected model fitting phase")
                d.require(model["accepted"] is True and model["protocol_sha256"] == old_sha
                          and model["source_sha256"] == source["sha256"] and model["native_keys_sha256"] == keys["keys_sha256"],
                          "selected model acceptance/input binding")
                theta = np.asarray([model["intercept"], *model["coefficients"]], dtype=np.float64)
                d.require(np.isfinite(theta).all() and len(theta) == len(common.feature_names(model["n"], family))+1
                          and d.array_sha(theta) == model["coefficient_sha256"], "selected coefficient identity")
                selected_models[year, family, stage] = model
        for phase in ("validation", "outer"):
            relative = f"30m/{year}/{phase}.npz"
            path, sidecar_path = consume(relative), consume(relative[:-4]+".json")
            sidecar, arrays = d.read_json(sidecar_path), d.read_npz(path)
            d.require(sidecar["npz_sha256"] == d.digest(path) and sidecar["npz_bytes"] == path.stat().st_size, "original sidecar file identity")
            validate_phase(arrays, sidecar, fold, phase, source, keys, old_sha)
            d.require(set(sidecar["models"]) == set(d.FAMILIES), "original sidecar model coverage")
            stage = "inner" if phase == "validation" else "refit"
            for family in d.FAMILIES:
                binding, model = sidecar["models"][family], selected_models[year, family, stage]
                validate_prediction_model(binding, model, phase, d.digest(consume(model["path"])))
            phases[year, phase] = arrays
            phase_bindings.append({"year": year, "phase": phase, "prediction_path": relative,
                "prediction_sha256": d.digest(path), "sidecar_path": relative[:-4]+".json", "sidecar_sha256": d.digest(sidecar_path),
                "models": sidecar["models"]})
        consume(f"30m/{year}/classification_daily.npz")
    for relative, identity in sorted(consumed.items()):
        target = out / "predecessor" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bounded(r1a_root, relative), target)
        d.require(file_record(target) == identity, "copied predecessor byte identity")
        copies[str(target.relative_to(out))] = {**identity, "origin_kind": "predecessor", "origin_relative": relative}
    for name in ("keys.bin", "context.json", "manifest.json", "manifest.sha256", "timings.json"):
        path, target = native_folder / name, out / "native" / "30m" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        identity = file_record(path)
        d.require(file_record(target) == identity, "copied native byte identity")
        copies[str(target.relative_to(out))] = {**identity, "origin_kind": "native", "origin_relative": "30m/"+name}
    receipt = {"schema": "filang-followup30-inputs-v1", "protocol_sha256": d.digest(out / "protocol.json"),
        "scope": "Exact-byte scoped R1a selected 30m bundle; original complete audit covers unconsumed candidates and other timeframes.",
        "predecessor_root": str(r1a_root), "data_root": str(data_root), "keys_root": str(keys_root),
        "predecessor_manifest_sha256": d.digest(r1a_root / "manifest.json"),
        "predecessor_analysis_sha256": d.digest(r1a_root / "analysis.json"),
        "predecessor_audit_sha256": d.digest(r1a_root / "verification.json"),
        "predecessor_protocol_sha256": old_sha, "predecessor_execution_commit": predecessor["execution_commit"],
        "copied_files": copies, "phases": phase_bindings,
        "external_sources": {"prepared_csv": {"path": source["path"], **file_record(source["path"])},
            "raw_parquet": {"path": str(data_root / "raw" / protocol["data"]["source"]["filename"]),
                **file_record(data_root / "raw" / protocol["data"]["source"]["filename"])},
            "source_specification": protocol["data"]["source"]},
        "coverage": {"source_rows": source["rows"], "native_keys": len(keys["indices"]),
                     "original_prediction_phases": len(phases), "selected_models": len(selected_models),
                     "selection_records": 8, "copied_files": len(copies)}}
    d.write_json(out / "inputs.json", receipt)
    return phases, source, receipt, old_analysis


def runtime_receipt():
    import scipy
    from contextlib import redirect_stdout
    from threadpoolctl import threadpool_info
    import platform
    stream = io.StringIO()
    with redirect_stdout(stream):
        np.show_config()
    return {"python": sys.version, "numpy": np.__version__, "scipy": scipy.__version__,
            "platform": platform.platform(), "machine": platform.machine(), "processor": platform.processor(),
            "thread_environment": {name: os.environ.get(name) for name in THREAD_VARIABLES},
            "threadpool_info": threadpool_info(), "numpy_configuration": stream.getvalue()}


def git_identity(repo, protocol_path, freeze):
    def git(*args):
        return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout
    d.require(freeze == FREEZE_COMMIT and d.digest(protocol_path) == PROTOCOL_SHA256, "unrecognized frozen follow-up protocol")
    frozen = subprocess.run(["git", "show", f"{freeze}:{PROTOCOL_PATH}"], cwd=repo, check=True, capture_output=True).stdout
    d.require(frozen == protocol_path.read_bytes(), "protocol differs from published freeze")
    head, status = git("rev-parse", "HEAD").strip(), git("status", "--porcelain")
    d.require(status == "", "clean committed worktree required")
    subprocess.run(["git", "merge-base", "--is-ancestor", freeze, head], cwd=repo, check=True, capture_output=True)
    d.require(git("branch", "--remotes", "--contains", freeze).strip(), "freeze has no published remote reference")
    d.require(git("branch", "--remotes", "--contains", head).strip(), "implementation must be published before execution")
    files = {"experiments/geometry_information/"+name: d.digest(repo / "experiments/geometry_information" / name)
             for name in ("run_followup30.py", "followup30.py", "common.py")}
    return {"git_commit": head, "worktree_status_porcelain": status, "files": files, "sha256": d.object_sha(files)}


def seal_run(out):
    files = {}
    for path in sorted(out.rglob("*")):
        if path.is_file() and path.relative_to(out).as_posix() not in ("manifest.json", "manifest.sha256"):
            files[path.relative_to(out).as_posix()] = file_record(path)
    d.write_json(out / "manifest.json", {"schema": "filang-followup30-run-manifest-v1", "files": files})
    (out / "manifest.sha256").write_text(d.digest(out / "manifest.json")+"\n")


def raw_reconciliation(daily, old_analysis, original_root):
    old = next(row for row in old_analysis["timeframes"] if row["minutes"] == 30)
    annual = []
    for row in old["folds"]:
        year = row["year"]
        use = daily["outer_year"] == year
        old_daily = d.read_npz(original_root / f"30m/{year}/classification_daily.npz")
        for name in ("day", "binary_count"):
            assert_numeric(daily[name][use], old_daily[name], "original daily reconciliation "+name)
        for family in d.FAMILIES:
            assert_numeric(daily[f"raw_loss_sum_{family}"][use], old_daily[f"loss_sum_{family}"], "original daily score reconciliation")
        assert_numeric(daily["raw_paired_loss_sum"][use], old_daily["paired_loss_sum"], "original daily paired reconciliation")
        count = int(daily["binary_count"][use].sum())
        numerator = float(daily["raw_paired_loss_sum"][use].sum())
        gain = numerator/count
        d.require(abs(gain-row["gain"]) <= 1e-10, "original annual gain reconciliation")
        d.require(count == row["scores"]["B"]["binary_count"] == row["scores"]["G"]["binary_count"], "original annual score counts")
        for family in d.FAMILIES:
            reference_sum = row["scores"][family]["loss_sum"]
            d.require(abs(float(daily[f"raw_loss_sum_{family}"][use].sum())-reference_sum) <= 1e-10+1e-10*abs(reference_sum),
                      "original annual score numerator reconciliation")
        annual.append({"year": year, "count": count, "numerator": numerator, "gain": gain,
                       "original_gain": row["gain"], "absolute_error": abs(gain-row["gain"])})
    numerator, count = float(daily["raw_paired_loss_sum"].sum()), int(daily["binary_count"].sum())
    gain = numerator/count
    reference = 0.0005687510773535314
    d.require(abs(gain-reference) <= 1e-10, "published raw pooled gain reconciliation")
    return {"status": "PASS", "annual": annual, "pooled_count": count, "pooled_numerator": numerator,
            "pooled_gain": gain, "reference_gain": reference, "absolute_error": abs(gain-reference)}


def produce(protocol, out, phases, source, inputs, implementation, old_analysis):
    bindings = {(row["year"], row["phase"]): row for row in inputs["phases"]}
    fits, adapters = [], {}
    fitting_began = time.perf_counter()
    for fold in protocol["target_and_phases"]["outer_folds"]:
        year, arrays = fold["year"], phases[fold["year"], "validation"]
        selected = arrays["binary_mask"]
        rows = np.flatnonzero(selected).astype(np.int64)
        labels = (arrays["direction"][selected] == 1).astype(np.uint8)
        for family in d.FAMILIES:
            z = arrays[f"logit_{family}"][selected]
            metadata = {"schema": "filang-followup30-adapter-v1", "year": year, "family": family,
                "lambda": protocol["models"]["lambda"], "initial_parameters": [0.0, 1.0],
                "protocol_sha256": PROTOCOL_SHA256, "implementation_sha256": implementation["sha256"],
                "source_prediction_path": bindings[year, "validation"]["prediction_path"],
                "source_prediction_sha256": bindings[year, "validation"]["prediction_sha256"],
                "source_model": bindings[year, "validation"]["models"][family],
                "training_start": d.epoch(fold["validation_start"]),
                "training_end_exclusive": d.epoch(fold["validation_end_exclusive"]),
                "sample_count": len(rows), "sample_up_count": int(labels.sum()), "sample_down_count": int(len(rows)-labels.sum()),
                "sample_rows_sha256": d.array_sha(rows), "sample_logits_sha256": d.array_sha(z),
                "sample_labels_sha256": d.array_sha(labels)}
            metadata["fit_id"] = d.object_sha(metadata)
            path = out / str(year) / "adapters" / (family+".json")
            try:
                record = {**metadata, **d.fit_adapter(z, labels, penalty=protocol["models"]["lambda"],
                    max_updates=protocol["models"]["optimizer"]["max_updates"],
                    gradient_acceptance=protocol["models"]["optimizer"]["gradient_max_acceptance"])}
                d.write_json(path, record)
                fits.append(record)
                with (out / "fits.jsonl").open("wb") as stream:
                    for fit in fits:
                        stream.write(d.json_bytes(fit))
                d.require(record["accepted"], "required affine adapter rejected")
                adapters[year, family] = record
            except Exception:
                if not path.exists():
                    record = {**metadata, "accepted": False, "exception": traceback.format_exc()}
                    d.write_json(path, record)
                    fits.append(record)
                    with (out / "fits.jsonl").open("wb") as stream:
                        for fit in fits:
                            stream.write(d.json_bytes(fit))
                raise
        print(f"accepted 30m {year} adapters", flush=True)
    fitting_seconds = time.perf_counter()-fitting_began
    transformed, prediction_began = {}, time.perf_counter()
    for fold in protocol["target_and_phases"]["outer_folds"]:
        year = fold["year"]
        models = {family: adapters[year, family] for family in d.FAMILIES}
        for phase in ("validation", "outer"):
            original = phases[year, phase]
            arrays = d.transformed_arrays(original, models, source["ohlc"][:, 0])
            transformed[year, phase] = arrays
            relative = f"{year}/{phase}.npz"
            identity = d.write_npz(out / relative, arrays)
            binding = bindings[year, phase]
            sidecar = {"schema": "filang-followup30-predictions-v1", "year": year, "phase": phase,
                "phase_start": d.epoch(fold[f"{phase}_start"]), "phase_end_exclusive": d.epoch(fold[f"{phase}_end_exclusive"]),
                "source_prediction_path": binding["prediction_path"], "source_prediction_sha256": binding["prediction_sha256"],
                "source_sidecar_path": binding["sidecar_path"], "source_sidecar_sha256": binding["sidecar_sha256"],
                "source_sha256": source["sha256"], "native_keys_sha256": protocol["data"]["native"]["keys_sha256"],
                "protocol_sha256": PROTOCOL_SHA256, "implementation_sha256": implementation["sha256"],
                "adapter_records": {family: {"path": f"{year}/adapters/{family}.json",
                    "sha256": d.digest(out / str(year) / "adapters" / (family+".json")), "fit_id": models[family]["fit_id"]}
                    for family in d.FAMILIES}, "npz_sha256": identity["sha256"], "npz_bytes": identity["bytes"], "arrays": identity["arrays"]}
            d.write_json(out / relative.replace(".npz", ".json"), sidecar)
    prediction_seconds = time.perf_counter()-prediction_began
    diagnostic_began = time.perf_counter()
    diagnostics, daily, memberships = d.build_diagnostics(transformed, protocol["target_and_phases"]["outer_folds"])
    reconciliation = raw_reconciliation(daily, old_analysis, out / "predecessor")
    d.require(len(daily["day"]) == 1376 and len(diagnostics["periods"]) == 55, "complete diagnostic calendar coverage")
    d.write_json(out / "diagnostics.json", diagnostics)
    d.write_npz(out / "daily.npz", daily)
    with (out / "daily.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["utc_date", *daily])
        writer.writeheader()
        for i, day in enumerate(daily["day"]):
            writer.writerow({"utc_date": dt.datetime.fromtimestamp(int(day)*86400, dt.timezone.utc).date().isoformat(),
                             **{name: values[i].item() for name, values in daily.items()}})
    for year, arrays in memberships.items():
        d.write_npz(out / str(year) / "diagnostic-membership.npz", arrays)
    diagnostic_seconds = time.perf_counter()-diagnostic_began
    bootstrap_began = time.perf_counter()
    bootstrap, original_encoding = {}, None
    settings = protocol["primary_inference"]["bootstrap"]
    for block in (settings["primary_block_days"], *settings["sensitivity_block_days"]):
        summary, arrays, encoding = d.ratio_bootstrap(daily, block, replicates=settings["replicates"], base_seed=settings["base_seed"])
        d.write_npz(out / f"bootstrap-{block}.npz", arrays)
        bootstrap[str(block)] = summary
        if original_encoding is None:
            original_encoding = encoding
        d.require(encoding == original_encoding, "bootstrap encodings agree across block lengths")
    d.write_json(out / "bootstrap-exact.json", original_encoding)
    criteria = d.decisions(diagnostics, bootstrap)
    coverage = {"adapter_fits": len(fits), "accepted_adapter_fits": sum(fit["accepted"] for fit in fits),
                "prediction_phases": len(transformed), "prediction_array_members": sum(len(a) for a in transformed.values()),
                "native_keys": inputs["coverage"]["native_keys"], "source_rows": source["rows"],
                "calendar_days": len(daily["day"]), "periods": len(diagnostics["periods"]),
                "magnitude_cells": len(diagnostics["magnitude_cells"]), "decision_cells": len(diagnostics["decision_cells"]),
                "score_cells": len(diagnostics["score_cells"]), "score_boundaries": len(diagnostics["score_boundaries"]),
                "distributions": len(diagnostics["distribution"]), "correction_distributions": len(diagnostics["corrections"]),
                "sample_censuses": len(diagnostics["sample_census"]), "weighted_gains": len(diagnostics["weighted_gains"]),
                "past_means": len(diagnostics["past_means"]), "bootstrap_cases": len(bootstrap),
                "exact_tail_bits": len(bootstrap)*settings["replicates"], "all_records": True, "sampled": False}
    analysis = {"schema": "filang-followup30-analysis-v1", "status": "COMPLETE_PENDING_INDEPENDENT_AUDIT",
                "experiment_id": protocol["experiment_id"], "attempt_id": protocol["attempt_id"],
                "protocol_sha256": PROTOCOL_SHA256, "freeze_commit": FREEZE_COMMIT,
                "implementation_sha256": implementation["sha256"], "inputs_sha256": d.digest(out / "inputs.json"),
                "diagnostics_sha256": d.digest(out / "diagnostics.json"), "coverage": coverage, "bootstrap": bootstrap,
                **criteria, "raw_reconciliation": reconciliation, "outcome": "inconclusive",
                "outcome_if_verified": criteria["primary"]["outcome_if_verified"],
                "audit_required": "Every required independent check must PASS before conditional outcomes or continuation can be promoted."}
    d.write_json(out / "analysis.json", analysis)
    return {"fitting_seconds": fitting_seconds, "prediction_serialization_seconds": prediction_seconds,
            "diagnostic_serialization_seconds": diagnostic_seconds, "bootstrap_serialization_seconds": time.perf_counter()-bootstrap_began}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("r1a-run", "data-dir", "keys-dir", "protocol", "out"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--freeze-commit", required=True)
    parser.add_argument("--blas-threads", type=int, default=2)
    args = parser.parse_args()
    d.require(args.blas_threads == 2, "frozen operational thread setting is two")
    for name in THREAD_VARIABLES:
        os.environ[name] = "2"
    from threadpoolctl import threadpool_limits
    began, cpu_began = time.perf_counter(), time.process_time()
    repo = Path(__file__).resolve().parents[2]
    protocol_path = args.protocol.resolve()
    d.require(protocol_path == repo / PROTOCOL_PATH, "protocol must be the repository's admitted reference")
    implementation = git_identity(repo, protocol_path, args.freeze_commit)
    protocol = d.read_json(protocol_path)
    d.require(protocol["schema"] == "filang-30m-signal-followup-protocol-v1" and protocol["attempt_id"] == "F30-D1", "protocol attempt/schema")
    d.require([fold["year"] for fold in protocol["target_and_phases"]["outer_folds"]] == list(YEARS), "frozen outer folds")
    validate_output_destination(args.out, (args.r1a_run, args.data_dir, args.keys_dir))
    d.require(not args.out.exists(), "fresh output required")
    args.out.mkdir(parents=True)
    out = args.out.resolve()
    shutil.copyfile(protocol_path, out / "protocol.json")
    run = {"schema": "filang-followup30-run-v1", "status": "RUNNING", "attempt_id": protocol["attempt_id"],
        "experiment_id": protocol["experiment_id"], "protocol_sha256": PROTOCOL_SHA256, "freeze_commit": FREEZE_COMMIT,
        "protocol_repository_path": PROTOCOL_PATH, "implementation": implementation,
        "verification_dependencies": {"experiments/geometry_information/verify_round1.py": d.digest(Path(__file__).with_name("verify_round1.py"))},
        "command": [sys.executable, *sys.argv], "settings": {"workers": 1, "blas_threads": 2}, "runtime": runtime_receipt(),
        "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "deviations": []}
    d.write_json(out / "run.json", run)
    try:
        admission_began = time.perf_counter()
        phases, source, inputs, old_analysis = admit_inputs(args.r1a_run, args.data_dir, args.keys_dir, protocol, out)
        admission_seconds = time.perf_counter()-admission_began
        with threadpool_limits(limits=2):
            stages = produce(protocol, out, phases, source, inputs, implementation, old_analysis)
        d.require(git_identity(repo, protocol_path, args.freeze_commit) == implementation, "implementation changed during producer")
        # Detect source mutation before the immutable producer seal.
        for relative, record in inputs["copied_files"].items():
            d.require(file_record(out / relative) == {key: record[key] for key in ("bytes", "sha256")}, "copied input changed during execution")
        for record in (inputs["external_sources"]["prepared_csv"], inputs["external_sources"]["raw_parquet"]):
            d.require(file_record(record["path"]) == {key: record[key] for key in ("bytes", "sha256")}, "external input changed during execution")
        run.update(status="COMPLETE_PENDING_INDEPENDENT_AUDIT", completed_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                   stage_timings={"admission_seconds": admission_seconds, **stages,
                                  "total_seconds_before_final_seal": time.perf_counter()-began},
                   cpu_seconds=time.process_time()-cpu_began,
                   peak_rss_bytes=int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)*(1 if sys.platform == "darwin" else 1024))
        d.write_json(out / "run.json", run)
        seal_run(out)
        print("COMPLETE_PENDING_INDEPENDENT_AUDIT "+str(out), flush=True)
    except Exception:
        error = traceback.format_exc()
        d.write_json(out / "failure.json", {"schema": "filang-followup30-failure-v1", "outcome": "inconclusive", "traceback": error})
        if not (out / "analysis.json").exists():
            d.write_json(out / "analysis.json", {"schema": "filang-followup30-analysis-v1", "status": "FAILED",
                "attempt_id": protocol["attempt_id"], "protocol_sha256": PROTOCOL_SHA256, "outcome": "inconclusive",
                "outcome_if_verified": "inconclusive", "failure": "failure.json"})
        run.update(status="FAILED", completed_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                   elapsed_seconds=time.perf_counter()-began, failure="failure.json")
        d.write_json(out / "run.json", run)
        seal_run(out)
        raise


if __name__ == "__main__":
    main()
