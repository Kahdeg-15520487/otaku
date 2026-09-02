"""Log-view rendering — the pure day-name handling.

The contract: `resolve_day` turns a `logs` DAY argument into the stamp
the logs name their files with (YYYYMMDD) — today's when the argument
is absent, either spelling (bare or dashed) when given, and None for
anything else; `dashed` prints a stamp the human way; and `day_rows`
shapes the `--list` rows, one dashed day and its size each.
"""

from datetime import datetime

from otaku.logging import dashed, day_rows, resolve_day


class TestResolveDay:
    def test_an_absent_day_is_today(self) -> None:
        before = datetime.now().astimezone().strftime("%Y%m%d")
        stamp = resolve_day(None)
        after = datetime.now().astimezone().strftime("%Y%m%d")
        assert stamp in (before, after)  # both, lest the test straddle midnight

    def test_the_dashed_form_becomes_the_stamp(self) -> None:
        assert resolve_day("2026-07-25") == "20260725"

    def test_a_bare_stamp_passes_through(self) -> None:
        assert resolve_day("20260725") == "20260725"

    def test_anything_else_is_none(self) -> None:
        assert resolve_day("yesterday") is None
        assert resolve_day("2026-7-25") is None


class TestDashed:
    def test_a_stamp_prints_the_human_way(self) -> None:
        assert dashed("20260725") == "2026-07-25"


class TestDayRows:
    def test_one_row_per_day_with_its_size(self) -> None:
        rows = day_rows([("20260725", 1234), ("20260726", 56)])
        assert rows == ["2026-07-25       1,234 B", "2026-07-26          56 B"]
