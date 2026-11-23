"""Verify that an installed distribution and its native runtime match the release pin."""

from importlib.metadata import version
import sys

from filang_engine import Engine

expected = sys.argv[1]
assert version("filang") == expected
with Engine() as engine:
    assert engine.version() == {"abi": 1, "version": expected}
print(f"Installed filang {expected}, engine ABI 1")
