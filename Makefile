.PHONY: build test demo data search evaluate stress
PYTHON ?= python3
build:
	cargo build --release --locked --offline
test:
	cargo fmt --all -- --check
	cargo test --locked --offline
	cargo clippy --locked --offline --all-targets -- -D warnings
demo: build
	./target/release/filang demo --out runs/demo
data:
	$(PYTHON) scripts/prepare_hf.py
search: build
	./target/release/filang search --config examples/btc4h.cfg
evaluate: build
	./target/release/filang evaluate --data data/btc4h/evaluation.csv --selection runs/btc4h/frozen.tsv --out runs/btc4h-evaluation
stress: build
	./target/release/filang evaluate --data data/btc4h/evaluation.csv --selection runs/btc4h/frozen.tsv --out runs/btc4h-stress --fee-bps 10 --slip-bps 10
