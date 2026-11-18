import json

import pytest

from pytest_conductor import (
    ALLURE_HISTORY_DIR_NAME,
    ALLURE_REPORT_DIR_NAME,
    ALLURE_RESULTS_DIR_NAME,
    CATEGORIES_FILE_NAME,
    CI_ENV_VAR,
    DEFAULT_OUTPUT_DIR_NAME,
    INTERACTIVE_RUN,
    LOG_FILE_NAME,
    OUTPUT_DIR_ENV_VAR,
    output_path_for,
    report_commands,
    run_covers_whole_suite,
    should_open_report,
)


def test_the_output_tree_mirrors_the_test_tree(tmp_path):
    """Artifacts mirror tests/ exactly as configs/ does."""
    path = output_path_for(
        test_file=tmp_path / "tests" / "menus" / "test_app_menu_closes.py",
        test_name="test_app_menu_closes",
        rootdir=tmp_path,
        output_root=tmp_path / "out",
    )

    assert path == tmp_path / "out" / "menus" / "test_app_menu_closes"


def test_the_leading_tests_segment_is_dropped(tmp_path):
    """Keeping it would repeat a word the output root already implies."""
    path = output_path_for(
        test_file=tmp_path / "tests" / "lifecycle" / "test_x.py",
        test_name="test_x",
        rootdir=tmp_path,
        output_root=tmp_path / "out",
    )

    assert "tests" not in path.relative_to(tmp_path / "out").parts


def test_a_module_holding_several_tests_keeps_them_apart(tmp_path):
    """Merging two tests into one directory would overwrite artifacts."""
    first = output_path_for(
        test_file=tmp_path / "tests" / "test_module.py",
        test_name="test_one",
        rootdir=tmp_path,
        output_root=tmp_path / "out",
    )
    second = output_path_for(
        test_file=tmp_path / "tests" / "test_module.py",
        test_name="test_two",
        rootdir=tmp_path,
        output_root=tmp_path / "out",
    )

    assert first != second
    assert first == tmp_path / "out" / "test_module" / "test_one"


def test_parametrised_cases_get_separate_directories(tmp_path):
    """Each case writes its own artifacts, so they cannot share a directory."""
    paths = {
        output_path_for(
            test_file=tmp_path / "tests" / "test_x.py",
            test_name=name,
            rootdir=tmp_path,
            output_root=tmp_path / "out",
        )
        for name in ("test_x[1]", "test_x[2]")
    }

    assert len(paths) == 2


def test_characters_illegal_in_a_path_are_replaced(tmp_path):
    """A test id like test_x[a/b] would otherwise nest a directory."""
    path = output_path_for(
        test_file=tmp_path / "tests" / "test_x.py",
        test_name="test_x[a/b:c]",
        rootdir=tmp_path,
        output_root=tmp_path / "out",
    )

    leaf = path.relative_to(tmp_path / "out" / "test_x")
    assert len(leaf.parts) == 1, f"should be one segment, got {leaf.parts}"
    assert "/" not in str(leaf) and ":" not in str(leaf)


def test_trailing_dots_and_spaces_are_stripped(tmp_path):
    """Windows accepts these but then cannot open the path."""
    path = output_path_for(
        test_file=tmp_path / "tests" / "test_x.py",
        test_name="test_x ",
        rootdir=tmp_path,
        output_root=tmp_path / "out",
    )

    assert not path.name.endswith((" ", "."))


def test_a_test_outside_the_rootdir_does_not_raise(tmp_path):
    """An unexpected layout must not stop a run that is otherwise fine."""
    path = output_path_for(
        test_file=tmp_path.parent / "stray" / "test_wandering.py",
        test_name="test_wandering",
        rootdir=tmp_path,
        output_root=tmp_path / "out",
    )

    assert path == tmp_path / "out" / "test_wandering"


NO_ALLURE_INI = "[pytest]\naddopts = --no-allure\n"


@pytest.fixture
def suite(pytester):
    """A throwaway suite with one test that writes into its output directory."""
    pytester.makefile(".ini", pytest=NO_ALLURE_INI)
    pytester.makepyfile(
        **{
            "tests/menus/test_thing": (
                "def test_thing(output_dir):\n"
                "    (output_dir / 'report.txt').write_text('written', encoding='utf-8')\n"
            )
        }
    )
    return pytester


def test_the_fixture_creates_the_directory_and_a_test_can_write_to_it(suite):
    """End to end: discovery, option parsing, path building, creation."""
    result = suite.runpytest("--output-dir=artifacts")

    result.assert_outcomes(passed=1)
    written = suite.path / "artifacts" / "menus" / "test_thing" / "report.txt"
    assert written.read_text(encoding="utf-8") == "written"


def test_the_command_line_beats_the_environment(suite, monkeypatch):
    """In CI the environment is global and one job must override it."""
    monkeypatch.setenv(OUTPUT_DIR_ENV_VAR, str(suite.path / "from-env"))

    result = suite.runpytest("--output-dir=from-cli")

    result.assert_outcomes(passed=1)
    assert (suite.path / "from-cli").is_dir()
    assert not (suite.path / "from-env").exists()


def test_the_environment_is_used_when_no_option_is_given(suite, monkeypatch):
    """A CI job redirects a whole run without changing any command."""
    monkeypatch.setenv(OUTPUT_DIR_ENV_VAR, str(suite.path / "from-env"))

    result = suite.runpytest()

    result.assert_outcomes(passed=1)
    assert (suite.path / "from-env" / "menus" / "test_thing").is_dir()


def test_the_default_is_under_the_rootdir(suite, monkeypatch):
    """Unconfigured artifacts land in the project, not the current directory."""
    monkeypatch.delenv(OUTPUT_DIR_ENV_VAR, raising=False)

    result = suite.runpytest()

    result.assert_outcomes(passed=1)
    assert (suite.path / DEFAULT_OUTPUT_DIR_NAME / "menus" / "test_thing").is_dir()


def test_no_directory_is_created_for_a_test_that_does_not_ask(pytester, monkeypatch):
    """Creation is lazy, or most tests would leave an empty directory."""
    monkeypatch.delenv(OUTPUT_DIR_ENV_VAR, raising=False)
    pytester.makefile(".ini", pytest=NO_ALLURE_INI)
    pytester.makepyfile(**{"tests/test_quiet": "def test_quiet():\n    assert True\n"})

    result = pytester.runpytest()

    result.assert_outcomes(passed=1)
    assert not (pytester.path / DEFAULT_OUTPUT_DIR_NAME / "test_quiet").exists()


def test_the_run_header_says_where_artifacts_go(suite):
    """Nobody should read the plugin to find where artifacts went."""
    result = suite.runpytest("--output-dir=artifacts")

    result.stdout.fnmatch_lines(["*output-dir:*artifacts*"])


@pytest.fixture
def noisy_suite(pytester, monkeypatch):
    """One passing and one failing test, both of which print."""
    monkeypatch.delenv(OUTPUT_DIR_ENV_VAR, raising=False)
    pytester.makefile(".ini", pytest=NO_ALLURE_INI)
    pytester.makepyfile(
        **{
            "tests/test_good": "def test_good():\n    print('good ran')\n    assert True\n",
            "tests/test_bad": (
                "def test_bad():\n    print('bad ran')\n    raise AssertionError('deliberate')\n"
            ),
        }
    )
    return pytester


def _log_for(pytester, name):
    return pytester.path / DEFAULT_OUTPUT_DIR_NAME / name / LOG_FILE_NAME


def test_a_failing_test_keeps_its_stdout_as_text(noisy_suite):
    """After a failure the printed output is the first thing wanted."""
    noisy_suite.runpytest("--output-dir=" + DEFAULT_OUTPUT_DIR_NAME)

    written = _log_for(noisy_suite, "test_bad").read_text(encoding="utf-8")
    assert "bad ran" in written
    assert "outcome:  failed" in written


def test_the_log_includes_the_traceback(noisy_suite):
    """Output and traceback belong in one file, not two."""
    noisy_suite.runpytest("--output-dir=" + DEFAULT_OUTPUT_DIR_NAME)

    written = _log_for(noisy_suite, "test_bad").read_text(encoding="utf-8")
    assert "deliberate" in written
    assert "traceback" in written


def test_each_phase_appears_exactly_once(noisy_suite):
    """pytest accumulates sections, so rendering every report repeats them."""
    noisy_suite.runpytest("--output-dir=" + DEFAULT_OUTPUT_DIR_NAME)

    written = _log_for(noisy_suite, "test_bad").read_text(encoding="utf-8")

    assert written.count("Captured stdout call") == 1, "sections must not be repeated"


def test_the_output_is_labelled_by_phase(noisy_suite):
    """Output during teardown is a cleanup problem, not a test failure."""
    noisy_suite.runpytest("--output-dir=" + DEFAULT_OUTPUT_DIR_NAME)

    written = _log_for(noisy_suite, "test_bad").read_text(encoding="utf-8")
    assert "call" in written


def test_passing_tests_leave_no_log_by_default(noisy_suite):
    """A log for every passing test would bury the one that matters."""
    noisy_suite.runpytest("--output-dir=" + DEFAULT_OUTPUT_DIR_NAME)

    assert not _log_for(noisy_suite, "test_good").exists()
    assert _log_for(noisy_suite, "test_bad").exists()


def test_save_log_always_keeps_passing_tests_too(noisy_suite):
    """For a test that passes but did the wrong thing."""
    noisy_suite.runpytest("--output-dir=" + DEFAULT_OUTPUT_DIR_NAME, "--save-log=always")

    written = _log_for(noisy_suite, "test_good").read_text(encoding="utf-8")
    assert "good ran" in written
    assert "outcome:  passed" in written


def test_save_log_never_writes_nothing_at_all(noisy_suite):
    """An escape hatch for a run where artifacts are unwanted."""
    noisy_suite.runpytest("--output-dir=" + DEFAULT_OUTPUT_DIR_NAME, "--save-log=never")

    assert not _log_for(noisy_suite, "test_bad").exists()


def test_the_log_lands_beside_the_fixture_artifacts(pytester, monkeypatch):
    """The log and the test's own files must share one directory."""
    monkeypatch.delenv(OUTPUT_DIR_ENV_VAR, raising=False)
    pytester.makefile(".ini", pytest=NO_ALLURE_INI)
    pytester.makepyfile(
        **{
            "tests/menus/test_both": (
                "def test_both(output_dir):\n"
                "    (output_dir / 'extra.txt').write_text('x', encoding='utf-8')\n"
                "    raise AssertionError('deliberate')\n"
            )
        }
    )

    pytester.runpytest("--output-dir=" + DEFAULT_OUTPUT_DIR_NAME)

    directory = pytester.path / DEFAULT_OUTPUT_DIR_NAME / "menus" / "test_both"
    assert (directory / "extra.txt").exists()
    assert (directory / LOG_FILE_NAME).exists()


def _results(pytester, *parts: str):
    return pytester.path.joinpath(*parts)


@pytest.fixture
def allure_suite(pytester, monkeypatch):
    """The same throwaway suite with Allure on; always run in a subprocess."""
    monkeypatch.delenv(OUTPUT_DIR_ENV_VAR, raising=False)
    pytester.makefile(".ini", pytest="[pytest]\naddopts = --open-report=never\n")
    pytester.makepyfile(**{"tests/menus/test_thing": "def test_thing():\n    assert True\n"})
    return pytester


def test_allure_results_appear_without_anyone_asking_for_them(allure_suite):
    """Installing allure-pytest is the whole opt-in; no option to remember."""
    allure_suite.runpytest_subprocess("--output-dir=artifacts")

    results = _results(allure_suite, "artifacts", ALLURE_RESULTS_DIR_NAME)
    assert list(results.glob("*-result.json")), f"no Allure results in {results}"


def test_an_explicit_alluredir_wins(allure_suite):
    """The default must not override a deliberate choice."""
    allure_suite.runpytest_subprocess("--output-dir=artifacts", "--alluredir=elsewhere")

    assert list(_results(allure_suite, "elsewhere").glob("*-result.json"))
    assert not _results(allure_suite, "artifacts", ALLURE_RESULTS_DIR_NAME).exists()


def test_no_allure_switches_it_off(allure_suite):
    """An escape hatch that does not require uninstalling a dependency."""
    allure_suite.runpytest_subprocess("--output-dir=artifacts", "--no-allure")

    assert not _results(allure_suite, "artifacts", ALLURE_RESULTS_DIR_NAME).exists()


def test_the_header_says_where_the_results_went(allure_suite):
    result = allure_suite.runpytest_subprocess("--output-dir=artifacts")

    result.stdout.fnmatch_lines(["*allure-results:*artifacts*"])


def test_the_failure_categories_are_written_for_the_report(allure_suite):
    """The file must survive --clean-alluredir, which empties the directory."""
    allure_suite.runpytest_subprocess("--output-dir=artifacts", "--clean-alluredir")

    categories = _results(allure_suite, "artifacts", ALLURE_RESULTS_DIR_NAME, CATEGORIES_FILE_NAME)
    names = [entry["name"] for entry in json.loads(categories.read_text(encoding="utf-8"))]
    assert "The UI never became ready" in names


def test_the_previous_reports_history_is_carried_into_the_results(allure_suite):
    """Trends exist only if the last report's history is fed back in."""
    history = _results(allure_suite, "artifacts", ALLURE_REPORT_DIR_NAME, ALLURE_HISTORY_DIR_NAME)
    history.mkdir(parents=True)
    (history / "history.json").write_text('{"from": "the previous run"}', encoding="utf-8")

    allure_suite.runpytest_subprocess("--output-dir=artifacts")

    carried = _results(
        allure_suite,
        "artifacts",
        ALLURE_RESULTS_DIR_NAME,
        ALLURE_HISTORY_DIR_NAME,
        "history.json",
    )
    assert "previous run" in carried.read_text(encoding="utf-8")


def test_a_first_run_without_a_previous_report_is_fine(allure_suite):
    """The common case, and it must not error: there is no history to carry."""
    result = allure_suite.runpytest_subprocess("--output-dir=artifacts")

    result.assert_outcomes(passed=1)
    assert not _results(
        allure_suite, "artifacts", ALLURE_RESULTS_DIR_NAME, ALLURE_HISTORY_DIR_NAME
    ).exists()


def test_the_summary_prints_the_commands_that_build_the_report(allure_suite):
    """A results directory is JSON for a generator, and says so nowhere."""
    result = allure_suite.runpytest_subprocess("--output-dir=artifacts")

    result.stdout.fnmatch_lines(["*allure generate*artifacts*", "*allure open*"])


def _result_names(pytester):
    directory = _results(pytester, "artifacts", ALLURE_RESULTS_DIR_NAME)
    return {path.name for path in directory.glob("*-result.json")}


def test_each_run_replaces_the_results_of_the_previous_one(allure_suite):
    """Mixing runs makes the report show tests that no longer exist."""
    allure_suite.runpytest_subprocess("--output-dir=artifacts")
    first = _result_names(allure_suite)

    allure_suite.runpytest_subprocess("--output-dir=artifacts")
    second = _result_names(allure_suite)

    assert len(first) == len(second) == 1
    assert not first & second


def test_keep_results_accumulates_runs_on_purpose(allure_suite):
    """The escape hatch for assembling one report out of several runs."""
    allure_suite.runpytest_subprocess("--output-dir=artifacts")
    allure_suite.runpytest_subprocess("--output-dir=artifacts", "--keep-results")

    assert len(_result_names(allure_suite)) == 2


def test_cleaning_the_results_leaves_the_report_history_alone(allure_suite):
    """History is the one thing that must survive run after run."""
    history = _results(allure_suite, "artifacts", ALLURE_REPORT_DIR_NAME, ALLURE_HISTORY_DIR_NAME)
    history.mkdir(parents=True)
    (history / "history.json").write_text('{"from": "the previous run"}', encoding="utf-8")

    allure_suite.runpytest_subprocess("--output-dir=artifacts")
    allure_suite.runpytest_subprocess("--output-dir=artifacts")

    assert "previous run" in (history / "history.json").read_text(encoding="utf-8")


def test_a_plain_run_is_the_whole_suite(pytester):
    """Only such a run earns a point on the trend chart."""
    assert run_covers_whole_suite(pytester.parseconfig())


@pytest.mark.parametrize("narrowing", [("-k", "menu"), ("-m", "slow"), ("test_thing.py",)])
def test_filters_and_paths_make_a_run_partial(pytester, narrowing):
    """A subset of the suite must not be compared against full runs."""
    assert not run_covers_whole_suite(pytester.parseconfig(*narrowing))


def test_a_whole_suite_run_generates_a_report_it_keeps(tmp_path):
    """Generating into a fixed directory is what carries history forward."""
    commands = report_commands("allure", tmp_path / "in", tmp_path / "out", whole_suite=True)

    assert [command[1] for command in commands] == ["generate", "open"]
    assert str(tmp_path / "out") in commands[0]


def test_a_partial_run_is_served_and_leaves_no_report(tmp_path):
    """allure serve uses a temporary directory, so no trend point appears."""
    commands = report_commands("allure", tmp_path / "in", tmp_path / "out", whole_suite=False)

    assert commands == [["allure", "serve", str(tmp_path / "in")]]


def test_never_and_always_override_everything(pytester, monkeypatch):
    """The two switches a person reaches for must not be second-guessed."""
    monkeypatch.setenv(CI_ENV_VAR, "true")

    assert not should_open_report(pytester.parseconfig("--open-report=never"))
    assert should_open_report(pytester.parseconfig("--open-report=always"))


def test_auto_opens_nothing_in_ci(pytester, monkeypatch):
    """A blocking web server would hang the job until it timed out."""
    monkeypatch.setenv(CI_ENV_VAR, "true")
    config = pytester.parseconfig()
    config.stash[INTERACTIVE_RUN] = True

    assert not should_open_report(config)


def test_auto_opens_the_report_for_an_interactive_run(pytester, monkeypatch):
    """The case the default exists for: a person running tests by hand."""
    monkeypatch.delenv(CI_ENV_VAR, raising=False)
    config = pytester.parseconfig()
    config.stash[INTERACTIVE_RUN] = True

    assert should_open_report(config)


def test_auto_stays_quiet_when_the_output_is_not_a_terminal(pytester, monkeypatch):
    """Editors, hooks and pipes read pytest output; nobody watches a browser."""
    monkeypatch.delenv(CI_ENV_VAR, raising=False)
    config = pytester.parseconfig()
    config.stash[INTERACTIVE_RUN] = False

    assert not should_open_report(config)
