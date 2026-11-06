import pytest

from prometheus.econosim.inventory import InsufficientInventoryError, InventoryAccount


def test_rejects_negative_financing_limit() -> None:
    with pytest.raises(ValueError, match="financing_limit"):
        InventoryAccount(quantity=10.0, financing_limit=-1.0)


def test_rejects_initial_quantity_already_below_the_financing_floor() -> None:
    with pytest.raises(ValueError, match="financing floor"):
        InventoryAccount(quantity=-10.0, financing_limit=5.0)


def test_deposit_increases_quantity() -> None:
    account = InventoryAccount(quantity=5.0)
    account.deposit(3.0)
    assert account.quantity == 8.0


def test_deposit_rejects_non_positive_amount() -> None:
    account = InventoryAccount(quantity=5.0)
    with pytest.raises(ValueError, match="deposit"):
        account.deposit(0.0)
    with pytest.raises(ValueError, match="deposit"):
        account.deposit(-1.0)


def test_withdraw_decreases_quantity() -> None:
    account = InventoryAccount(quantity=10.0)
    account.withdraw(4.0)
    assert account.quantity == 6.0


def test_withdraw_rejects_non_positive_amount() -> None:
    account = InventoryAccount(quantity=10.0)
    with pytest.raises(ValueError, match="withdrawal"):
        account.withdraw(0.0)
    with pytest.raises(ValueError, match="withdrawal"):
        account.withdraw(-1.0)


def test_withdraw_to_exactly_zero_is_allowed_without_financing() -> None:
    account = InventoryAccount(quantity=10.0)
    account.withdraw(10.0)
    assert account.quantity == 0.0


def test_withdraw_beyond_balance_raises_a_structured_error_without_financing() -> None:
    """LED-03's literal "invalid ... withdrawal rejects with structured
    error": a named exception carrying the available/requested amounts,
    not a bare ValueError string."""
    account = InventoryAccount(quantity=10.0)
    with pytest.raises(InsufficientInventoryError) as exc_info:
        account.withdraw(15.0)
    assert exc_info.value.available == 10.0
    assert exc_info.value.requested == 15.0
    assert exc_info.value.floor == 0.0


def test_rejected_withdrawal_does_not_mutate_the_balance() -> None:
    account = InventoryAccount(quantity=10.0)
    with pytest.raises(InsufficientInventoryError):
        account.withdraw(15.0)
    assert account.quantity == 10.0


def test_financing_limit_alone_does_not_authorize_a_negative_withdrawal() -> None:
    """"Unless specified financing exists" requires financing to be
    EXPLICITLY invoked per withdrawal (financed=True), not merely
    configured on the account -- a financing_limit set but unused must
    still reject an over-withdrawal exactly as if there were none."""
    account = InventoryAccount(quantity=10.0, financing_limit=20.0)
    with pytest.raises(InsufficientInventoryError) as exc_info:
        account.withdraw(15.0)  # financed defaults to False
    assert exc_info.value.floor == 0.0
    assert account.quantity == 10.0


def test_financed_withdrawal_succeeds_within_the_financing_limit() -> None:
    account = InventoryAccount(quantity=10.0, financing_limit=20.0)
    account.withdraw(25.0, financed=True)  # resulting balance: -15.0
    assert account.quantity == -15.0


def test_financed_withdrawal_still_rejects_beyond_the_financing_limit() -> None:
    account = InventoryAccount(quantity=10.0, financing_limit=20.0)
    with pytest.raises(InsufficientInventoryError) as exc_info:
        account.withdraw(35.0, financed=True)  # would reach -25.0, floor is -20.0
    assert exc_info.value.floor == -20.0
    assert account.quantity == 10.0
