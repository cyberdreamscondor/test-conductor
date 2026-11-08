from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

OUTPUT_DIR_ENV_VAR = "TEST_CONDUCTOR_OUTPUT_DIR"
DEFAULT_OUTPUT_DIR_NAME = "test-output"
TESTS_DIR_NAME = "tests"

LOG_FILE_NAME = "test-log.txt"
SAVE_LOG_CHOICES = ("failed", "always", "never")

ALLURE_RESULTS_DIR_NAME = "allure-results"
ALLURE_REPORT_DIR_NAME = "allure-report"
ALLURE_HISTORY_DIR_NAME = "history"
CATEGORIES_FILE_NAME = "categories.json"

FAILURE_CATEGORIES = [
    {
        "name": "Chrome could not be launched",
        "matchedStatuses": ["failed", "broken"],
        "traceRegex": "(?s).*ChromeNotFoundError.*",
    },
    {
        "name": "The UI never became ready",
        "matchedStatuses": ["failed", "broken"],
        "traceRegex": "(?s).*WaitTimeout.*",
    },
    {
        "name": "UI automation error",
        "matchedStatuses": ["failed", "broken"],
        "traceRegex": "(?s).*(COMError|ElementNotFoundError|ElementAmbiguousError).*",
    },
    {
        "name": "Test data or config problem",
        "matchedStatuses": ["failed", "broken"],
        "traceRegex": "(?s).*(UnknownMenuItem|MissingConfigValue|MissingConfigAttribute).*",
    },
    {
        "name": "Profile isolation broken",
        "matchedStatuses": ["failed"],
        "messageRegex": "(?s).*framework-managed.*",
    },
    {
        "name": "Expected menu entry missing",
        "matchedStatuses": ["failed"],
        "messageRegex": "(?s).*not found. Present:.*",
    },
]

_ILLEGAL_IN_SEGMENT = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_segment(text: str) -> str:
    """Make one path segment safe on every supported platform."""
    cleaned = _ILLEGAL_IN_SEGMENT.sub("_", text).strip(" .")
    return cleaned or "unnamed"


def output_path_for(
    test_file: Path,
    test_name: str,
    rootdir: Path,
    output_root: Path,
    tests_dir_name: str = TESTS_DIR_NAME,
) -> Path:
    """Where one test's artifacts belong, mirroring the tests tree."""
    resolved = Path(test_file).resolve()
    try:
        relative = resolved.relative_to(Path(rootdir).resolve())
    except ValueError:
        relative = Path(resolved.name)

    parts = list(relative.parts)
    if parts and parts[0] == tests_dir_name:
        parts = parts[1:]

    if not parts:
        parts = [resolved.name]

    directories = [_safe_segment(part) for part in parts[:-1]]
    module_stem = _safe_segment(Path(parts[-1]).stem)
    leaf = _safe_segment(test_name)

    path = Path(output_root).joinpath(*directories, module_stem)

    if leaf != module_stem:
        path = path / leaf
    return path


def _resolve_output_root(config: pytest.Config) -> Path:
    """The artifact root: option, then environment, then ini, then default."""
    from_cli = config.getoption("output_dir", default=None)
    if from_cli:
        return Path(from_cli).expanduser().resolve()

    from_env = os.environ.get(OUTPUT_DIR_ENV_VAR)
    if from_env:
        return Path(from_env).expanduser().resolve()

    from_ini = config.getini("output_dir")
    if from_ini:
        return (Path(config.rootpath) / str(from_ini)).resolve()

    return (Path(config.rootpath) / DEFAULT_OUTPUT_DIR_NAME).resolve()


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("test-conductor", "Test-Conductor")
    group.addoption(
        "--output-dir",
        dest="output_dir",
        default=None,
        metavar="PATH",
        help=(
            "Directory for test artifacts: reports, screenshots, logs. "
            "Each test gets its own subdirectory mirroring the tests tree. "
            f"Overrides ${OUTPUT_DIR_ENV_VAR} and the output_dir ini setting."
        ),
    )
    parser.addini(
        "output_dir",
        "Default artifact directory for this suite, relative to rootdir.",
        default="",
    )
    group.addoption(
        "--no-allure",
        dest="no_allure",
        action="store_true",
        default=False,
        help=(
            "Do not point allure-pytest at the artifact directory. Allure "
            "results are written automatically whenever allure-pytest is "
            "installed; this switches that off without uninstalling it."
        ),
    )
    group.addoption(
        "--save-log",
        dest="save_log",
        choices=SAVE_LOG_CHOICES,
        default="failed",
        help=(
            f"Write each test's captured stdout, stderr, log and traceback to "
            f"{LOG_FILE_NAME} in its output directory. "
            "'failed' (the default) only for tests that fail, 'always' for "
            "every test, 'never' to switch it off."
        ),
    )


def _allure_is_installed() -> bool:
    """Is allure-pytest importable? Checked without importing it."""
    return importlib.util.find_spec("allure_pytest") is not None


def allure_results_dir(config: pytest.Config) -> Path | None:
    """Where this run's Allure results belong, or None when Allure is off."""
    if not _allure_is_installed() or config.getoption("no_allure", default=False):
        return None

    chosen = getattr(config.option, "allure_report_dir", None)
    if chosen:
        return Path(chosen).expanduser().resolve()
    return _resolve_output_root(config) / ALLURE_RESULTS_DIR_NAME


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Register the log writer and point Allure at the artifact directory."""
    config.pluginmanager.register(_TestLogWriter(config), "test-conductor-log-writer")

    results = allure_results_dir(config)
    if results is not None:
        config.option.allure_report_dir = str(results)


def allure_report_dir(config: pytest.Config) -> Path:
    """Where `allure generate` is expected to put the HTML report."""
    return _resolve_output_root(config) / ALLURE_REPORT_DIR_NAME


def _carry_history_forward(results: Path, report: Path) -> None:
    """Copy the previous report's history in, which is what makes trends work."""
    source = report / ALLURE_HISTORY_DIR_NAME
    if not source.is_dir():
        return

    shutil.copytree(source, results / ALLURE_HISTORY_DIR_NAME, dirs_exist_ok=True)


def pytest_sessionfinish(session: pytest.Session) -> None:
    """Write the failure categories beside the results, after any cleaning."""
    results = allure_results_dir(session.config)
    if results is None:
        return

    results.mkdir(parents=True, exist_ok=True)
    (results / CATEGORIES_FILE_NAME).write_text(
        json.dumps(FAILURE_CATEGORIES, indent=2), encoding="utf-8"
    )
    _carry_history_forward(results, allure_report_dir(session.config))


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: pytest.Config) -> None:
    """Print the two commands that turn the results into a report."""
    results = allure_results_dir(config)
    if results is None or not any(results.glob("*-result.json")):
        return

    report = allure_report_dir(config)
    terminalreporter.write_sep("-", "Allure")
    terminalreporter.write_line(f'allure generate "{results}" --clean -o "{report}"')
    terminalreporter.write_line(f'allure open "{report}"')


def pytest_report_header(config: pytest.Config) -> list[str]:
    """Print the artifact locations in the run header."""
    lines = [f"output-dir: {_resolve_output_root(config)}"]

    results = allure_results_dir(config)
    if results is not None:
        lines.append(f"allure-results: {results}")
    return lines


def _part(title: str, text: str | None) -> str:
    """One labelled block, or nothing at all when there is no content."""
    if not text or not text.strip():
        return ""
    return f"\n--- {title} ---\n{text.rstrip()}"


def _render(nodeid: str, reports: list[pytest.TestReport], failed: bool) -> str:
    """Assemble one test's captured output into readable text."""
    total = sum(report.duration for report in reports)
    lines = [
        f"test:     {nodeid}",
        f"outcome:  {'failed' if failed else 'passed'}",
        f"duration: {total:.2f}s",
    ]

    for title, content in reports[-1].sections:
        block = _part(title, content)
        if block:
            lines.append(block)

    for report in reports:
        if report.failed:
            block = _part(f"traceback ({report.when})", report.longreprtext)
            if block:
                lines.append(block)

    return "\n".join(lines) + "\n"


class _TestLogWriter:
    def __init__(self, config: pytest.Config) -> None:
        self._config = config
        self._mode = config.getoption("save_log", default="failed")
        self._root: Path | None = None
        self._reports: dict[str, list[pytest.TestReport]] = {}

    def _output_root(self) -> Path:
        if self._root is None:
            self._root = _resolve_output_root(self._config)
        return self._root

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if self._mode == "never":
            return

        self._reports.setdefault(report.nodeid, []).append(report)
        if report.when != "teardown":
            return

        reports = self._reports.pop(report.nodeid, [])
        failed = any(item.failed for item in reports)
        if self._mode == "failed" and not failed:
            return

        rootdir = Path(self._config.rootpath)
        directory = output_path_for(
            test_file=rootdir / report.nodeid.split("::")[0],
            test_name=report.nodeid.split("::")[-1],
            rootdir=rootdir,
            output_root=self._output_root(),
        )
        directory.mkdir(parents=True, exist_ok=True)
        (directory / LOG_FILE_NAME).write_text(
            _render(report.nodeid, reports, failed), encoding="utf-8"
        )


@pytest.fixture(scope="session")
def output_root(pytestconfig: pytest.Config) -> Path:
    """The run's artifact root, created once per session."""
    root = _resolve_output_root(pytestconfig)
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def output_dir(request: pytest.FixtureRequest, output_root: Path) -> Path:
    """This test's own artifact directory, created on request."""
    path = output_path_for(
        test_file=request.path,
        test_name=request.node.name,
        rootdir=Path(request.config.rootpath),
        output_root=output_root,
    )
    path.mkdir(parents=True, exist_ok=True)
    return path
