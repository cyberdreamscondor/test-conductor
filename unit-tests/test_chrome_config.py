"""Unit tests for Chrome discovery and launch-argument construction.

No Chrome is launched here and none needs to be installed: a fake executable is
a file created by tmp_path. That is deliberate - these tests must pass on a
Linux CI runner with no browser at all.

`monkeypatch` and `tmp_path` are pytest's built-in fixtures. monkeypatch undoes
every change it makes when the test ends, so an environment variable set in one
test cannot leak into another.
"""

import pytest

from chrome_config import (
    CHROME_PATH_ENV_VAR,
    DEFAULT_LAUNCH_FLAGS,
    ChromeConfig,
    ChromeNotFoundError,
    find_chrome_executable,
)


@pytest.fixture
def fake_chrome(tmp_path):
    """A file standing in for chrome.exe; only its existence matters."""
    executable = tmp_path / "chrome.exe"
    executable.write_text("not really chrome")
    return executable


# --- discovery ---------------------------------------------------------------


def test_explicit_path_wins(fake_chrome, monkeypatch):
    """An explicit choice must beat every discovered one."""
    monkeypatch.setenv(CHROME_PATH_ENV_VAR, "C:/some/other/chrome.exe")
    assert find_chrome_executable(fake_chrome) == fake_chrome


def test_environment_variable_is_used_when_no_explicit_path(fake_chrome, monkeypatch):
    """A runner sets one variable instead of patching code."""
    monkeypatch.setenv(CHROME_PATH_ENV_VAR, str(fake_chrome))
    assert find_chrome_executable() == fake_chrome


def test_missing_explicit_path_fails_loudly(tmp_path, monkeypatch):
    """A bad override must not fall back to a browser nobody chose."""
    monkeypatch.delenv(CHROME_PATH_ENV_VAR, raising=False)
    missing = tmp_path / "nope.exe"

    with pytest.raises(ChromeNotFoundError) as failure:
        find_chrome_executable(missing)

    assert "nope.exe" in str(failure.value)


def test_missing_environment_path_fails_loudly(tmp_path, monkeypatch):
    """A typo in CI configuration must fail, not pick another browser."""
    monkeypatch.setenv(CHROME_PATH_ENV_VAR, str(tmp_path / "nope.exe"))

    with pytest.raises(ChromeNotFoundError) as failure:
        find_chrome_executable()

    assert CHROME_PATH_ENV_VAR in str(failure.value)


def test_failure_message_lists_what_was_searched(monkeypatch):
    """'Chrome not found' is unactionable without the locations tried."""
    monkeypatch.delenv(CHROME_PATH_ENV_VAR, raising=False)
    # Force every discovery route to fail, including the registry on Windows.
    monkeypatch.setattr("chrome_config._registry_chrome_path", lambda: None)
    monkeypatch.setattr("chrome_config._WINDOWS_CANDIDATES", (r"{ProgramFiles}\nowhere.exe",))

    with pytest.raises(ChromeNotFoundError) as failure:
        find_chrome_executable()

    message = str(failure.value)
    assert "Searched:" in message
    assert "nowhere.exe" in message
    assert CHROME_PATH_ENV_VAR in message, "the message should say how to fix it"


# --- launch arguments --------------------------------------------------------


def test_command_line_always_isolates_the_profile(fake_chrome, tmp_path):
    """Without --user-data-dir the automation drives the real Chrome profile."""
    config = ChromeConfig(executable=fake_chrome)
    profile = tmp_path / "profile"

    arguments = config.command_line(profile)

    assert f"--user-data-dir={profile}" in arguments


def test_command_line_starts_with_the_executable(fake_chrome, tmp_path):
    """argv[0] must be the program itself."""
    config = ChromeConfig(executable=fake_chrome)
    assert config.command_line(tmp_path)[0] == str(fake_chrome)


def test_default_flags_suppress_first_run_dialogs(fake_chrome, tmp_path):
    """A welcome screen on top of the UI makes every locator fail."""
    arguments = ChromeConfig(executable=fake_chrome).command_line(tmp_path)

    for flag in DEFAULT_LAUNCH_FLAGS:
        assert flag in arguments


def test_debugging_port_is_absent_unless_requested(fake_chrome, tmp_path):
    """CDP changes how Chrome behaves, so it stays opt-in."""
    arguments = ChromeConfig(executable=fake_chrome).command_line(tmp_path)
    assert not any("remote-debugging-port" in argument for argument in arguments)


def test_debugging_port_is_included_when_requested(fake_chrome, tmp_path):
    """CDP can only be enabled at launch, so the flag must be emitted."""
    config = ChromeConfig(executable=fake_chrome, remote_debugging_port=9222)
    assert "--remote-debugging-port=9222" in config.command_line(tmp_path)


def test_url_comes_last(fake_chrome, tmp_path):
    """Chrome treats the first non-flag argument as the URL to open."""
    config = ChromeConfig(executable=fake_chrome, initial_url="https://example.com")
    assert config.command_line(tmp_path)[-1] == "https://example.com"


def test_extra_flags_are_appended(fake_chrome, tmp_path):
    """An escape hatch for switches the config class knows nothing about."""
    config = ChromeConfig(executable=fake_chrome, extra_flags=("--lang=de",))
    arguments = config.command_line(tmp_path)

    assert "--lang=de" in arguments
    assert arguments.index("--lang=de") < len(arguments) - 1, "the URL must still be last"


# --- immutability ------------------------------------------------------------


def test_config_cannot_be_mutated(fake_chrome):
    """A config a test can mutate mid-run cannot be reasoned about."""
    config = ChromeConfig(executable=fake_chrome)

    with pytest.raises(Exception):  # noqa: B017 - dataclasses raise FrozenInstanceError
        config.ui_timeout = 999


def test_with_changes_returns_a_new_config(fake_chrome):
    """Deriving a copy leaves the original alone for the next test."""
    original = ChromeConfig(executable=fake_chrome)
    slower = original.with_changes(ui_timeout=60.0)

    assert slower.ui_timeout == 60.0
    assert original.ui_timeout == 10.0
    assert slower.executable == original.executable
