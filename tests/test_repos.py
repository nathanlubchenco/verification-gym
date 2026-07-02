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
