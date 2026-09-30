#!/usr/bin/env python3
"""Repeat the fixed ten-family grids per calendar year; report stress-only results.
Each year is tuned in-sample. Unrestricted maxima are not promotion decisions.
"""
from __future__ import annotations
import argparse, datetime, json, shutil, subprocess, sys, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from cohort_reference import KINDS, digest

YEARS = [(2024, '2025-01-01'), (2025, '2026-01-01'), (2026, '2026-09-28')]
NAMES = ['SMA(200)', 'EMA(24)', 'RSI(14)', 'MACD(12,26,9)', 'Bollinger(20)',
         'Stochastic(14,3,3)', 'ATR(14) / price', 'ROC(14)', 'CCI(20)', 'Rolling VWAP(20)']

def execute(command, log):
    log = Path(log)
    with log.open('w') as output:
        subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, check=True)

def verify_one(path):
    from verify_cohort_micro import verify
    return verify(path, Path(path) / 'verification.json')

def markdown(result):
    lines = ['# Annual indicator micro-sweeps: 10+10 costs', '',
             'BTCUSDT four-hour bars. 10 bps fees + 10 bps slippage per side.',
             'Each year is independently tuned on that same year (in-sample).',
             'Tuned = unrestricted descriptive maximum by same-year stressed log return.',
             'Difference = tuned minus reference in percentage points (pp).', '']
    for year, end in YEARS:
        suffix = ' — January 1–September 27 (partial year)' if year == 2026 else ''
        lines += [f'## {year}{suffix}', '',
                  '| Indicator | Reference return | Tuned return | Difference (pp) |',
                  '|---|---:|---:|---:|']
        for row in result['years'][str(year)]:
            lines.append(f"| {row['indicator']} | {row['reference_return_pct']:+.2f}% | "
                         f"{row['tuned_return_pct']:+.2f}% | {row['difference_pp']:+.2f} |")
        lines.append('')
    return '\n'.join(lines) + '\n'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['discover', 'verify'])
    parser.add_argument('--out', required=True)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    root = Path(args.out).resolve()
    if args.stage == 'verify':
        if not 1 <= args.workers <= 8 or not (root / 'annual_results.json').exists():
            raise ValueError('completed discovery and 1..8 reference workers required')
        paths = [str(root / str(year) / kind) for year, _ in YEARS for kind in KINDS]
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            checks = list(pool.map(verify_one, paths))
        (root / 'verification_index.json').write_text(json.dumps(
            {'status': 'PASS', 'annual_family_runs': 30, 'checks': checks}, indent=2) + '\n')
        return
    if root.exists():
        raise ValueError('use a fresh output directory')
    root.mkdir(parents=True)
    binary = str(Path('target/release/filang').resolve())
    full = Path('data/btc4h/evaluation.csv').resolve()
    source_rows = full.read_bytes().splitlines(keepends=True)
    result = {'status': 'PASS', 'role': 'annual_same_year_in_sample_tuning',
              'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
              'engine_sha256': digest(binary), 'full_data_sha256': digest(full),
              'reported_fee_bps_per_side': 10, 'reported_slippage_bps_per_side': 10,
              'difference_definition': 'tuned_return_pct - reference_return_pct (percentage points)',
              'parameter_addresses_per_family_year': 10091043, 'years': {}}
    (root / 'protocol.json').write_text(json.dumps(result, indent=2) + '\n')
    old = root / 'legacy-parity'
    execute([binary, 'anchor-parity', '--data', str(full), '--out', str(old)], root / 'legacy-native.log')
    execute([sys.executable, 'scripts/anchor_reference.py', '--data', str(full),
             '--manifest', str(old / 'manifest.json'), '--native', str(old),
             '--out', str(root / 'legacy-reference'), '--gate'], root / 'legacy-reference.log')
    for year, end in YEARS:
        target = root / str(year)
        target.mkdir()
        timestamp = int(datetime.datetime.fromisoformat(end).replace(tzinfo=datetime.timezone.utc).timestamp())
        prefix = target / 'data.csv'
        prefix.write_bytes(source_rows[0] + b''.join(
            row for row in source_rows[1:] if int(row.split(b',', 1)[0]) < timestamp))
        last = int(prefix.read_bytes().splitlines()[-1].split(b',', 1)[0])
        if last + 14400 != timestamp:
            raise ValueError('incomplete year prefix')
        copied = target / 'legacy-parity'
        copied.mkdir()
        for filename in ['gate.txt', 'gate.txt.sha256', 'manifest.json', 'metrics.bin', 'verification.json']:
            shutil.copy2(old / filename, copied / filename)
        execute([sys.executable, 'scripts/prepare_micro_gate.py', '--gate', str(copied / 'gate.txt'),
                 '--full', str(full), '--discovery', str(prefix)], target / 'prefix-gate.log')
        cohort = target / 'cohort-parity'
        execute([binary, 'cohort-parity', '--data', str(prefix), '--out', str(cohort),
                 '--start', f'{year}-01-01', '--end', end], target / 'cohort-native.log')
        execute([sys.executable, 'scripts/cohort_reference.py', '--run', str(cohort),
                 '--data', str(prefix)], target / 'cohort-reference.log')
        result['years'][str(year)] = []
        for kind, name in zip(KINDS, NAMES):
            changes = {'data': str(prefix), 'discovery_start': f'{year}-01-01',
                       'discovery_end': end, 'evaluation_start': end,
                       'evaluation_end': '2027-01-01', 'cohort_gate': str(cohort / 'gate.txt')}
            raw = Path(f'examples/micro10/{kind}.cfg').read_text()
            lines = []
            for line in raw.splitlines():
                key = line.split('=', 1)[0]
                lines.append(key + '=' + changes[key] if key in changes else line)
            cfg = target / (kind + '.cfg')
            cfg.write_text('\n'.join(lines) + '\n')
            clock = time.perf_counter()
            execute([binary, 'micro-sweep', '--config', str(cfg),
                     '--gate', str(copied / 'micro_gate.txt'), '--out', str(target / kind)],
                    target / (kind + '.log'))
            summary = json.loads((target / kind / 'summary.json').read_text())
            if not summary['coverage_complete'] or summary['full_parameter_addresses_resolved'] != 10091043:
                raise ValueError('incomplete annual grid')
            reference = summary['anchor']['stress']['net_return_pct']
            best = summary['descriptive_best_not_additionally_selected']
            tuned = best['stress']['net_return_pct']
            row = {'family': kind, 'indicator': name, 'year': year,
                   'start': f'{year}-01-01', 'end_exclusive': end,
                   'reference_return_pct': reference, 'tuned_return_pct': tuned,
                   'difference_pp': tuned - reference,
                   'relative_improvement_pct_abs_reference':
                       100 * (tuned - reference) / abs(reference) if reference else None,
                   'anchor': summary['anchor'], 'tuned': best,
                   'eligible_addresses': summary['eligible_addresses'],
                   'physical_regions': summary['physical_result_regions'],
                   'data_sha256': summary['data_sha256'],
                   'region_sha256': summary['region_sha256'],
                   'seconds': time.perf_counter() - clock}
            result['years'][str(year)].append(row)
            print(f'{year} {kind}: reference {reference:+.4f}% tuned {tuned:+.4f}% '
                  f'difference {tuned-reference:+.4f} pp', flush=True)
        (target / 'annual_results.json').write_text(json.dumps(result['years'][str(year)], indent=2) + '\n')
    result['parameter_addresses_covered'] = 30 * 10091043
    result['physical_regions'] = sum(r['physical_regions'] for rows in result['years'].values() for r in rows)
    (root / 'annual_results.json').write_text(json.dumps(result, indent=2) + '\n')
    (root / 'README.md').write_text(markdown(result))
    print('Annual discovery complete. No later-year validation or strategy promotion performed.', flush=True)

if __name__ == '__main__':
    main()
