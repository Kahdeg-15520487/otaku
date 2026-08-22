"""The shared write helpers in the package root: `row` aligns a
comment to one column so the written files read as a table."""

from otaku2.settings import row


class TestRow:
    def test_aligns_the_comment_to_one_column(self) -> None:
        first = row("a = 1", "first")
        second = row("bbbb = 2", "second")
        assert first.index("#") == second.index("#")

    def test_a_long_setting_still_gets_a_separated_comment(self) -> None:
        long = row("a_very_long_setting_name_indeed = 12345", "note")
        assert long.endswith("  # note")

    def test_no_comment_means_the_setting_alone(self) -> None:
        assert row("a = 1", "") == "a = 1"
