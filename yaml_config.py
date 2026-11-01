"""Per-test configuration loaded from YAML.

A test that writes `has_item("Settings")` has hardcoded a string belonging to
the application, not to the test logic. Chrome renames menu entries between
versions and translates them per locale, so such a value must be editable as
data rather than code.

Layout convention in a suite repository:

    tests/menus/test_app_menu_closes.py
    configs/menus/test_app_menu_closes.yaml

Same relative path, same stem, different root and extension. The mapping is
mechanical, so neither the test nor the framework has to be told where a
config lives.

A config is optional. A test with no config file runs on framework defaults.
But asking for a value that is not there is always an error: silently
substituting None would let a test pass while asserting nothing.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import yaml

CONFIG_SUFFIXES = (".yaml", ".yml")


class MissingConfigValue(LookupError):
    """A test asked for a configuration value that its YAML file does not have."""


class ConfigSection(Mapping):
    """One mapping inside a config file, with errors that name their source."""

    def __init__(self, name: str, data: Mapping[str, Any], source: Path):
        self._name = name
        self._data = dict(data)
        self._source = source

    def __getitem__(self, key: str) -> Any:
        try:
            return self._data[key]
        except KeyError:
            # The message carries the file, the section and what IS available.
            # "KeyError: 'menu_item'" on its own tells you nothing about which
            # of fifty config files is wrong.
            available = ", ".join(sorted(self._data)) or "(section is empty)"
            raise MissingConfigValue(
                f"{self._source}: no '{key}' in section '{self._name}'. Available: {available}"
            ) from None

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"ConfigSection({self._name!r}, {self._data!r})"


class TestConfig:
    """The configuration belonging to one test."""

    def __init__(self, path: Path, data: Mapping[str, Any] | None):
        self._path = path
        self._data = dict(data or {})

    @property
    def path(self) -> Path:
        """Where the config was looked for, whether or not it was found."""
        return self._path

    @property
    def exists(self) -> bool:
        """Was a config file actually present?"""
        return self._path.is_file()

    @property
    def expected(self) -> ConfigSection:
        """The 'expected' section: the values a test asserts against."""
        return self.section("expected")

    def section(self, name: str) -> ConfigSection:
        """A named mapping from the config. Absent means empty, not an error."""
        value = self._data.get(name) or {}
        if not isinstance(value, Mapping):
            raise MissingConfigValue(
                f"{self._path}: section '{name}' must be a mapping, got {type(value).__name__}"
            )
        return ConfigSection(name, value, self._path)

    def get(self, name: str, default: Any = None) -> Any:
        """A top-level value, with a fallback. For optional settings."""
        return self._data.get(name, default)

    def __repr__(self) -> str:
        state = "loaded" if self.exists else "absent"
        return f"TestConfig({self._path}, {state})"


def config_path_for(test_file: Path, tests_root: Path, configs_root: Path) -> Path:
    """Map a test file to its config file, preserving the folder structure."""
    test_file = Path(test_file).resolve()
    tests_root = Path(tests_root).resolve()
    configs_root = Path(configs_root).resolve()

    try:
        relative = test_file.relative_to(tests_root)
    except ValueError:
        raise ValueError(
            f"{test_file} is not inside the tests root {tests_root}, "
            "so its config path cannot be derived."
        ) from None

    candidates = [configs_root / relative.with_suffix(suffix) for suffix in CONFIG_SUFFIXES]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]  # the .yaml path, for the error message when missing


def load_test_config(test_file: Path, tests_root: Path, configs_root: Path) -> TestConfig:
    """Load the config for one test file. A missing file yields an empty config."""
    path = config_path_for(test_file, tests_root, configs_root)
    if not path.is_file():
        return TestConfig(path, None)

    text = path.read_text(encoding="utf-8")
    # safe_load, never load: yaml.load can construct arbitrary Python objects
    # from the document, which turns a config file into code execution.
    data = yaml.safe_load(text)
    if data is None:
        return TestConfig(path, None)  # empty or comment-only file
    if not isinstance(data, Mapping):
        raise MissingConfigValue(
            f"{path}: the top level of a config must be a mapping, got {type(data).__name__}"
        )
    return TestConfig(path, data)
