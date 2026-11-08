import pytest

from yaml_config import (
    ConfigNode,
    MissingConfigAttribute,
    MissingConfigValue,
    TestConfig,
    config_path_for,
    load_test_config,
)


@pytest.fixture
def suite(tmp_path):
    """A miniature suite repository: tests/ and configs/ side by side."""
    tests_root = tmp_path / "tests"
    configs_root = tmp_path / "configs"
    (tests_root / "menus").mkdir(parents=True)
    (configs_root / "menus").mkdir(parents=True)
    return tests_root, configs_root


def write_config(configs_root, relative, text):
    path = configs_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_config_path_mirrors_the_test_path(suite):
    """The config path is derived, never configured."""
    tests_root, configs_root = suite
    test_file = tests_root / "menus" / "test_app_menu_closes.py"

    path = config_path_for(test_file, tests_root, configs_root)

    assert path == configs_root / "menus" / "test_app_menu_closes.yaml"


def test_existing_yml_extension_is_accepted(suite):
    """Both spellings are common, and an ignored config is the worst outcome."""
    tests_root, configs_root = suite
    test_file = tests_root / "menus" / "test_thing.py"
    written = write_config(configs_root, "menus/test_thing.yml", "expected: {}\n")

    assert config_path_for(test_file, tests_root, configs_root) == written


def test_test_file_outside_the_tests_root_is_rejected(suite):
    """A clear error beats a path built from a bogus relative segment."""
    tests_root, configs_root = suite

    with pytest.raises(ValueError) as failure:
        config_path_for(tests_root.parent / "stray.py", tests_root, configs_root)

    assert "not inside the tests root" in str(failure.value)


def test_values_are_read_from_the_file(suite):
    """Expected values come from data, not from code."""
    tests_root, configs_root = suite
    write_config(
        configs_root,
        "menus/test_thing.yaml",
        "expected:\n  menu_item: Settings\n  menu_is_open: true\n",
    )

    config = load_test_config(tests_root / "menus" / "test_thing.py", tests_root, configs_root)

    assert config.exists
    assert config.expected["menu_item"] == "Settings"
    assert config.expected["menu_is_open"] is True


def test_lists_survive_loading(suite):
    """YAML sequences must arrive as Python lists, not one joined string."""
    tests_root, configs_root = suite
    write_config(
        configs_root,
        "menus/test_thing.yaml",
        "expected:\n  menu_items:\n    - New tab\n    - Settings\n",
    )

    config = load_test_config(tests_root / "menus" / "test_thing.py", tests_root, configs_root)

    assert config.expected["menu_items"] == ["New tab", "Settings"]


def test_a_missing_config_is_not_an_error(suite):
    """A test that needs no data must still run, on framework defaults."""
    tests_root, configs_root = suite

    config = load_test_config(tests_root / "menus" / "test_thing.py", tests_root, configs_root)

    assert not config.exists
    assert config.get("chrome", {}) == {}


def test_an_empty_file_is_treated_as_empty_config(suite):
    """A commented-out config parses to None and must not crash the loader."""
    tests_root, configs_root = suite
    write_config(configs_root, "menus/test_thing.yaml", "# nothing yet\n")

    config = load_test_config(tests_root / "menus" / "test_thing.py", tests_root, configs_root)

    assert config.get("chrome", {}) == {}


def test_missing_value_fails_and_names_its_source(suite):
    """Returning None would let a test assert against nothing and pass."""
    tests_root, configs_root = suite
    write_config(configs_root, "menus/test_thing.yaml", "expected:\n  menu_item: Settings\n")

    config = load_test_config(tests_root / "menus" / "test_thing.py", tests_root, configs_root)

    with pytest.raises(MissingConfigValue) as failure:
        config.expected["typo_key"]

    message = str(failure.value)
    assert "typo_key" in message
    assert "test_thing.yaml" in message
    assert "menu_item" in message, "the error should list what IS available"


def test_missing_value_in_a_missing_file_still_fails_clearly(suite):
    """With no config at all, the error must name the file it looked for."""
    tests_root, configs_root = suite

    config = load_test_config(tests_root / "menus" / "test_thing.py", tests_root, configs_root)

    with pytest.raises(MissingConfigValue) as failure:
        config.expected["menu_item"]

    assert "test_thing.yaml" in str(failure.value)


def test_a_non_mapping_top_level_is_rejected(suite):
    """A top-level YAML list would otherwise surface as a confusing error."""
    tests_root, configs_root = suite
    write_config(configs_root, "menus/test_thing.yaml", "- just\n- a list\n")

    with pytest.raises(MissingConfigValue) as failure:
        load_test_config(tests_root / "menus" / "test_thing.py", tests_root, configs_root)

    assert "must be a mapping" in str(failure.value)


def test_a_non_mapping_section_is_rejected(suite):
    """A section is splatted into Chrome.launch, so a string must fail here."""
    tests_root, configs_root = suite
    write_config(configs_root, "menus/test_thing.yaml", "chrome: just a string\n")

    config = load_test_config(tests_root / "menus" / "test_thing.py", tests_root, configs_root)

    with pytest.raises(MissingConfigValue) as failure:
        config.section("chrome")

    assert "must be a mapping" in str(failure.value)


def test_section_behaves_as_a_mapping(suite):
    """Fixtures iterate a section to splat it into Chrome.launch."""
    tests_root, configs_root = suite
    write_config(configs_root, "menus/test_thing.yaml", "chrome:\n  ui_timeout: 5\n")

    config = load_test_config(tests_root / "menus" / "test_thing.py", tests_root, configs_root)
    section = config.section("chrome")

    assert dict(section) == {"ui_timeout": 5}
    assert len(section) == 1
    assert list(section) == ["ui_timeout"]


def test_config_without_a_file_reports_the_path_it_wanted():
    """When a value is missing, you need to know where to put it."""
    config = TestConfig(path=__import__("pathlib").Path("configs/menus/test_x.yaml"), data=None)

    assert not config.exists
    assert "test_x.yaml" in str(config.path)


def test_values_are_reachable_with_dots(suite):
    """Subscript chains are plumbing; a test should read as a statement."""
    tests_root, configs_root = suite
    write_config(configs_root, "menus/test_thing.yaml", "asserts:\n  menu_item: Settings\n")

    config = load_test_config(tests_root / "menus" / "test_thing.py", tests_root, configs_root)

    assert config.asserts.menu_item == "Settings"


def test_dots_work_at_any_depth(suite):
    """Dots must keep working however deep the config grows."""
    tests_root, configs_root = suite
    write_config(
        configs_root,
        "menus/test_thing.yaml",
        "asserts:\n  menu:\n    first:\n      label: New tab\n",
    )

    config = load_test_config(tests_root / "menus" / "test_thing.py", tests_root, configs_root)

    assert config.asserts.menu.first.label == "New tab"


def test_mappings_inside_lists_are_wrapped(suite):
    """One test body over a list of scenario mappings."""
    tests_root, configs_root = suite
    write_config(
        configs_root,
        "menus/test_thing.yaml",
        "scenarios:\n  - name: single\n    quantity: 1\n  - name: bulk\n    quantity: 3\n",
    )

    config = load_test_config(tests_root / "menus" / "test_thing.py", tests_root, configs_root)
    scenarios = config.scenarios

    assert scenarios[0].name == "single"
    assert scenarios[1].quantity == 3


def test_missing_attribute_names_the_file_the_path_and_the_alternatives(suite):
    """A bare AttributeError would not say which config file is wrong."""
    tests_root, configs_root = suite
    write_config(
        configs_root,
        "menus/test_thing.yaml",
        "asserts:\n  menu_item: Settings\n  menu_is_open: true\n",
    )

    config = load_test_config(tests_root / "menus" / "test_thing.py", tests_root, configs_root)

    with pytest.raises(MissingConfigValue) as failure:
        config.asserts.typo_key  # noqa: B018 - the access IS the action

    message = str(failure.value)
    assert "typo_key" in message
    assert "test_thing.yaml" in message, "must name the file"
    assert "asserts" in message, "must name the dotted path, not just the key"
    assert "menu_item" in message, "must list what IS available"


def test_missing_attribute_is_both_a_lookup_and_an_attribute_error(suite):
    """Both, so that `except MissingConfigValue` and hasattr each still work."""
    node = ConfigNode({"present": 1}, __import__("pathlib").Path("x.yaml"))

    with pytest.raises(MissingConfigAttribute):
        node.absent  # noqa: B018 - the access IS the action

    assert issubclass(MissingConfigAttribute, MissingConfigValue)
    assert issubclass(MissingConfigAttribute, AttributeError)
    assert not hasattr(node, "absent"), "hasattr must return False, not raise"
    assert getattr(node, "absent", "fallback") == "fallback"


def test_underscored_names_are_never_config_lookups(suite):
    """A dunder probe must not become a config lookup, or __init__ recurses."""
    node = ConfigNode({"present": 1}, __import__("pathlib").Path("x.yaml"))

    with pytest.raises(AttributeError):
        node._not_a_config_key  # noqa: B018 - the access IS the action


def test_an_absent_section_is_empty_rather_than_an_error(suite):
    """This is what lets a test omit a section and still launch on defaults."""
    tests_root, configs_root = suite
    write_config(configs_root, "menus/test_thing.yaml", "asserts:\n  menu_item: Settings\n")

    config = load_test_config(tests_root / "menus" / "test_thing.py", tests_root, configs_root)

    assert dict(config.chrome) == {}


def test_a_value_from_an_absent_section_still_fails_and_names_the_file(suite):
    """Empty is fine, but reading a value out of nothing is still an error."""
    tests_root, configs_root = suite
    write_config(configs_root, "menus/test_thing.yaml", "asserts:\n  menu_item: Settings\n")

    config = load_test_config(tests_root / "menus" / "test_thing.py", tests_root, configs_root)

    with pytest.raises(MissingConfigValue) as failure:
        config.chrome.ui_timeout  # noqa: B018 - the access IS the action

    assert "test_thing.yaml" in str(failure.value)


def test_a_key_shadowed_by_a_mapping_method_is_still_reachable(suite):
    """A key named like a Mapping method is shadowed; subscript it instead."""
    node = ConfigNode({"items": [1, 2]}, __import__("pathlib").Path("x.yaml"))

    assert callable(node.items), "the Mapping method wins, as Python requires"
    assert node["items"] == [1, 2], "the subscript is the way to that key"
