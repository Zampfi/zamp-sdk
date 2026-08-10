"""Parsing the platform's failure text into AgentDbError.

This is a **cross-repo contract**: pantheon's `_run_one_statement` formats a failure
as ``statement <i> failed [sqlstate=XXXXX]: <message>``, and these tests are the
client half. Both halves have a test, so a change to either surfaces as a failure
rather than as silently-missing metadata.

The parsing is deliberately tolerant — an unrecognised shape degrades to a plain
message rather than raising while raising, which would replace a useful database
error with a parser traceback.
"""

import pytest

from zamp_sdk.db.errors import AgentDbError


class TestParsing:
    def test_the_canonical_platform_failure(self):
        error = AgentDbError.from_exception(
            RuntimeError(
                "Action abc-123 FAILED: statement 3 failed [sqlstate=23505]: "
                "duplicate key value violates unique constraint"
            )
        )

        assert error.sqlstate == "23505"
        assert error.statement_index == 3
        assert error.action_id == "abc-123"
        assert error.action_status == "FAILED"
        assert "duplicate key" in error.message

    def test_statement_zero_is_not_confused_with_absent(self):
        """0 is falsy; `is None` has to remain the test for "no index"."""
        error = AgentDbError.from_exception(RuntimeError("statement 0 failed [sqlstate=42703]: no such column"))

        assert error.statement_index == 0
        assert error.statement_index is not None

    def test_a_failure_that_never_reached_postgres_has_no_sqlstate(self):
        """A gate rejection or an authorization refusal. `sqlstate is None` is
        meaningful — it says "Postgres never saw this" — not merely missing."""
        error = AgentDbError.from_exception(
            RuntimeError(
                "Action x FAILED: statement 0: CREATE TABLE is not allowed here. "
                "Use agent_db_create_dataset instead."
            )
        )

        assert error.sqlstate is None
        assert error.statement_index == 0
        assert "agent_db_create_dataset" in error.message

    def test_the_unknown_sentinel_is_not_read_as_a_sqlstate(self):
        """Pantheon writes "sqlstate=unknown" when the driver gave it no code. A
        naive five-character match reports "unkno", which is worse than None: it
        looks like a real code and would be branched on."""
        error = AgentDbError.from_exception(RuntimeError("statement 0 failed [sqlstate=unknown]: connection reset"))

        assert error.sqlstate is None
        assert error.statement_index == 0

    def test_an_unrecognised_shape_still_produces_a_usable_error(self):
        error = AgentDbError.from_exception(RuntimeError("the network fell over"))

        assert error.message == "the network fell over"
        assert error.sqlstate is None
        assert error.statement_index is None

    @pytest.mark.parametrize(
        "text",
        [
            "statement 2 failed [sqlstate=40001]: could not serialize access",
            "statement 2 failed [SQLSTATE=40001]: could not serialize access",
            "statement_index=2 sqlstate: 40001",
        ],
    )
    def test_token_spellings_are_matched_tolerantly(self, text):
        error = AgentDbError.from_exception(RuntimeError(text))

        assert error.sqlstate == "40001"
        assert error.statement_index == 2

    def test_expected_rows_mismatch_carries_its_index(self):
        """The race guard. Its message has no sqlstate — the statement ran fine,
        the world just was not in the state the caller assumed."""
        error = AgentDbError.from_exception(
            RuntimeError(
                "Action y FAILED: statement 1: expected_rows=1 but the statement "
                "affected 0 rows; the whole transaction was rolled back."
            )
        )

        assert error.statement_index == 1
        assert error.sqlstate is None
        assert "rolled back" in error.message


class TestStringForm:
    def test_reads_well_with_metadata(self):
        error = AgentDbError("duplicate key", sqlstate="23505", statement_index=3)
        assert str(error) == "duplicate key [sqlstate=23505] [statement 3]"

    def test_reads_well_without(self):
        assert str(AgentDbError("something broke")) == "something broke"


class TestItIsARuntimeError:
    def test_existing_except_runtimeerror_handlers_keep_working(self):
        """Scripts written against the raw executor caught RuntimeError. Subclassing
        it means the bridge does not break them on upgrade."""
        with pytest.raises(RuntimeError):
            raise AgentDbError("boom")
