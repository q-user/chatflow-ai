"""Unit tests for _format_finance_text."""

from infrastructure.task_queue.tasks import _format_finance_text


class TestFormatFinanceText:
    """CRITICAL #1: _format_finance_text must handle invalid amounts gracefully."""

    # ── Amount validation ──

    def test_invalid_amount_string_skipped(self):
        """Non-numeric amount string is skipped, totals unaffected."""
        rows = [{"description": "test", "amount": "abc", "currency": "RUB"}]
        text = _format_finance_text(rows)
        assert "test" in text
        assert "Итого" not in text

    def test_invalid_amount_none(self):
        """None amount is rendered as '—'."""
        rows = [{"description": "test", "amount": None, "currency": "RUB"}]
        text = _format_finance_text(rows)
        assert "test" in text
        assert "—" in text
        assert "Итого" not in text

    def test_valid_amount_parsed(self):
        """Valid numeric amount is parsed and totals computed."""
        rows = [{"description": "Coffee", "amount": 150.5, "currency": "RUB"}]
        text = _format_finance_text(rows)
        assert "Coffee" in text
        assert "150.50" in text
        assert "Итого" in text
        assert "150.50" in text

    def test_negative_amount_string_parsed(self):
        """Negative amount string is parsed (AI may return negative)."""
        rows = [{"description": "Refund", "amount": "-50", "currency": "RUB"}]
        text = _format_finance_text(rows)
        assert "Refund" in text
        assert "50.00" in text
        assert "Итого" in text

    # ── Income vs Expense ──

    def test_expense_shows_red_minus(self):
        """Expense type shows red minus marker."""
        rows = [
            {"description": "Coffee", "amount": 150, "currency": "RUB", "type": "expense"}
        ]
        text = _format_finance_text(rows)
        assert "🔴" in text
        assert "-150.00" in text

    def test_income_shows_green_plus(self):
        """Income type shows green plus marker."""
        rows = [
            {"description": "Salary", "amount": 5000, "currency": "RUB", "type": "income"}
        ]
        text = _format_finance_text(rows)
        assert "🟢" in text
        assert "+5000.00" in text

    def test_default_type_is_expense(self):
        """Missing type defaults to expense (backward compatibility)."""
        rows = [{"description": "Coffee", "amount": 150, "currency": "RUB"}]
        text = _format_finance_text(rows)
        assert "🔴" in text
        assert "-150.00" in text

    # ── Totals ──

    def test_totals_income_minus_expense(self):
        """Totals: income adds, expense subtracts."""
        rows = [
            {"description": "Salary", "amount": 5000, "currency": "RUB", "type": "income"},
            {"description": "Coffee", "amount": 150, "currency": "RUB", "type": "expense"},
        ]
        text = _format_finance_text(rows)
        assert "Итого" in text
        assert "+4850.00" in text

    def test_totals_negative_when_expenses_exceed_income(self):
        """Net negative when expenses exceed income."""
        rows = [
            {"description": "Coffee", "amount": 150, "currency": "RUB", "type": "expense"},
        ]
        text = _format_finance_text(rows)
        assert "Итого" in text
        assert "-150.00" in text

    # ── Accounts list validation ──

    def test_unknown_category_gets_warning(self):
        """Unknown category gets warning emoji prefix."""
        rows = [{"description": "test", "amount": 100, "category": "Unknown:Cat"}]
        text = _format_finance_text(rows, accounts_list="Expenses:Food\nExpenses:Transport")
        assert "⚠️" in text

    def test_known_category_no_warning(self):
        """Known category has no warning prefix."""
        rows = [{"description": "test", "amount": 100, "category": "Expenses:Food"}]
        text = _format_finance_text(rows, accounts_list="Expenses:Food\nExpenses:Transport")
        assert "⚠️" not in text

    # ── Edge cases ──

    def test_empty_rows(self):
        """Empty rows returns failure message."""
        assert _format_finance_text([]) == "Не удалось распознать позиции."
