"""Unified-diff hunk parsing used by mining filters and ground-truth locations."""

import textwrap

from gym.difftools import Hunk, changed_new_ranges, parse_diff

DIFF = textwrap.dedent("""\
    diff --git a/mod.py b/mod.py
    index 1111111..2222222 100644
    --- a/mod.py
    +++ b/mod.py
    @@ -1,4 +1,6 @@
     def add(a, b):
         return a + b
    +
    +NEW = 1

     def sub(a, b):
    @@ -10,3 +12,3 @@ def mul(a, b):
     x = 1
    -y = 2
    +y = 3
     z = 4
    diff --git a/new_file.py b/new_file.py
    new file mode 100644
    index 0000000..3333333
    --- /dev/null
    +++ b/new_file.py
    @@ -0,0 +1,2 @@
    +A = 1
    +B = 2
""")


def test_parse_diff_files_and_hunks():
    parsed = parse_diff(DIFF)
    assert set(parsed) == {"mod.py", "new_file.py"}
    assert parsed["mod.py"][0] == Hunk(old_start=1, old_len=4, new_start=1, new_len=6)
    assert parsed["mod.py"][1] == Hunk(old_start=10, old_len=3, new_start=12, new_len=3)
    assert parsed["new_file.py"][0] == Hunk(old_start=0, old_len=0, new_start=1, new_len=2)


def test_changed_new_ranges_only_added_or_modified_lines():
    ranges = changed_new_ranges(DIFF)
    # mod.py hunk 1: added lines at new positions 3,4; hunk 2: changed line at 13
    assert ranges["mod.py"] == [(3, 4), (13, 13)]
    assert ranges["new_file.py"] == [(1, 2)]
