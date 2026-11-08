from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import yaml

CONFIG_SUFFIXES = (".yaml", ".yml")


class MissingConfigValue(LookupError):
    pass


class MissingConfigAttribute(MissingConfigValue, AttributeError):
    pass


def _wrap(value: Any, source: Path, trail: str) -> Any:
    """Make nested data dot-reachable, leaving leaf values untouched."""
    if isinstance(value, Mapping):
        return ConfigNode(value, source, trail)
    if isinstance(value, list):
        return [_wrap(item, source, f"{trail}[{index}]") for index, item in enumerate(value)]
    return value


class ConfigNode(Mapping[str, Any]):
    def __init__(self, data: Mapping[str, Any], source: Path, trail: str = "") -> None:
        self._data = dict(data)
        self._source = source
        self._trail = trail

    def _path_to(self, key: str) -> str:
        return f"{self._trail}.{key}" if self._trail else key

    def _missing(self, key: str) -> str:
        """The message for a value that is not there."""
        if self._data:
            available = ", ".join(sorted(self._data))
        else:
            where = f"'{self._trail}'" if self._trail else "the file"
            available = f"(nothing - {where} is empty or absent)"
        location = f"'{self._trail}'" if self._trail else "the top level"
        return f"{self._source}: no '{key}' in {location}. Available: {available}"

    def __getitem__(self, key: str) -> Any:
        try:
            value = self._data[key]
        except KeyError:
            raise MissingConfigValue(self._missing(key)) from None
        return _wrap(value, self._source, self._path_to(key))

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            value = self._data[name]
        except KeyError:
            raise MissingConfigAttribute(self._missing(name)) from None
        return _wrap(value, self._source, self._path_to(name))

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def get(self, key: object, default: Any = None, /) -> Any:
        """A value with a fallback, for genuinely optional settings."""
        if not isinstance(key, str) or key not in self._data:
            return default
        return self[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        where = self._trail or "<root>"
        return f"ConfigNode({where}, {sorted(self._data)})"


class TestConfig:
    __test__ = False

    def __init__(self, path: Path, data: Mapping[str, Any] | None) -> None:
        self._path = path
        self._root = ConfigNode(data or {}, path)

    @property
    def path(self) -> Path:
        """Where the config was looked for, whether or not it was found."""
        return self._path

    @property
    def exists(self) -> bool:
        """Was a config file actually present?"""
        return self._path.is_file()

    @property
    def sections(self) -> list[str]:
        """Top-level section names, for diagnostics."""
        return sorted(self._root)

    def section(self, name: str) -> ConfigNode:
        """A named mapping from the config. Absent means empty, not an error."""
        value = self._root.get(name, {})
        if isinstance(value, ConfigNode):
            return value
        if isinstance(value, Mapping):
            return ConfigNode(value, self._path, name)
        raise MissingConfigValue(
            f"{self._path}: section '{name}' must be a mapping, got {type(value).__name__}"
        )

    def get(self, name: str, default: Any = None) -> Any:
        """A top-level value, with a fallback. For optional settings."""
        return self._root.get(name, default)

    def __getattr__(self, name: str) -> Any:
        """Dotted access to a top-level entry; an absent name gives an empty node."""
        if name.startswith("_"):
            raise AttributeError(name)
        value = self._root.get(name, None)
        if value is None and name not in self._root:
            return ConfigNode({}, self._path, name)
        return value

    def __repr__(self) -> str:
        state = "loaded" if self.exists else "absent"
        return f"TestConfig({self._path}, {state}, sections={self.sections})"


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
    return candidates[0]


def load_test_config(test_file: Path, tests_root: Path, configs_root: Path) -> TestConfig:
    """Load the config for one test file. A missing file yields an empty config."""
    path = config_path_for(test_file, tests_root, configs_root)
    if not path.is_file():
        return TestConfig(path, None)

    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if data is None:
        return TestConfig(path, None)
    if not isinstance(data, Mapping):
        raise MissingConfigValue(
            f"{path}: the top level of a config must be a mapping, got {type(data).__name__}"
        )
    return TestConfig(path, data)
