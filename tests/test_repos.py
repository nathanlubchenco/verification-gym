"""Unit tests for repo validation helpers (full validation runs against real repos)."""

from gym.repos import check_license, count_loc


def test_count_loc_excludes_tests_and_blanks(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n\ny = 2\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test():\n    pass\n")
    (tmp_path / "test_top.py").write_text("assert True\n")
    assert count_loc(tmp_path) == 2


def test_check_license_mit(tmp_path):
    (tmp_path / "LICENSE").write_text("MIT License\n\nPermission is hereby granted")
    assert check_license(tmp_path) == "MIT"


def test_check_license_missing(tmp_path):
    assert check_license(tmp_path) == ""


def test_check_license_gpl_rejected(tmp_path):
    (tmp_path / "LICENSE").write_text("GNU GENERAL PUBLIC LICENSE Version 3")
    assert check_license(tmp_path) == ""


def test_check_license_bsd_body_without_name(tmp_path):
    (tmp_path / "LICENSE.txt").write_text(
        "Copyright 2014 Pallets\n\nRedistribution and use in source and binary "
        "forms, with or without modification, are permitted..."
    )
    assert check_license(tmp_path) == "BSD"


def test_check_license_spdx_in_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0"\nlicense = "BSD-3-Clause"\n'
    )
    assert check_license(tmp_path) == "BSD"


def test_install_targets_prefers_extra_then_group(tmp_path):
    from gym.repos import _test_install_targets

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0"\n'
        "[dependency-groups]\ntests = [\"pytest\"]\n"
    )
    assert _test_install_targets(tmp_path) == [".", "--group", "tests"]

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0"\n'
        "[project.optional-dependencies]\ntests = [\"pytest\"]\n"
    )
    assert _test_install_targets(tmp_path) == [".[tests]"]
