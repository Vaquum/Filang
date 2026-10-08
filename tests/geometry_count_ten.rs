//! The count command reports the complete ten-bar domain exactly even though
//! the existing bank-pair sweep deliberately retains checked u128 arithmetic.
use std::process::Command;

#[test]
fn count_cli_preserves_decimal_strings_and_supports_ten_bars() {
    for (bars, mode, count) in [
        ("0", "unoriented", "1"),
        ("2", "unoriented", "2568"),
        ("2", "oriented", "7452"),
        (
            "10",
            "unoriented",
            "60654091922379541904994268730790100840968",
        ),
        (
            "10",
            "oriented",
            "44121589533882676853417959154810808313579452",
        ),
    ] {
        let output = Command::new(env!("CARGO_BIN_EXE_filang"))
            .args(["geometry-count", "--bars", bars, "--mode", mode])
            .output()
            .unwrap();
        assert!(output.status.success(), "{:?}", output);
        assert_eq!(
            String::from_utf8(output.stdout).unwrap().trim(),
            format!(
                "{{\"version\":1,\"bars\":{bars},\"mode\":\"{mode}\",\"complete_patterns\":\"{count}\"}}"
            )
        );
    }
}

#[test]
fn count_cli_rejects_unsupported_width_instead_of_truncating() {
    let output = Command::new(env!("CARGO_BIN_EXE_filang"))
        .args(["geometry-count", "--bars", "11", "--mode", "oriented"])
        .output()
        .unwrap();
    assert!(!output.status.success());
    assert!(String::from_utf8(output.stderr)
        .unwrap()
        .contains("at most ten candles"));
}
