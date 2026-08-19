from autobooker.domain.state_machine import BookingStateMachine


def test_initial_state() -> None:
    """Prüft, ob die State Machine im richtigen Startzustand initialisiert wird."""
    machine = BookingStateMachine()
    assert machine.state == "IDLE"


def test_golden_path_exploration() -> None:
    """Testet den korrekten Durchlauf des Explorations-Modus."""
    machine = BookingStateMachine()

    machine.start()
    assert machine.state == "PREPARING_SESSION"

    machine.session_ready()
    assert machine.state == "MONITORING"

    machine.slot_found()
    assert machine.state == "SELECTING_APPOINTMENT"

    machine.slot_reserved()
    assert machine.state == "FILLING_USER_DATA"

    # Hier simulieren wir den Stop im Explorations-Modus
    machine.stop_dry_run()
    assert machine.state == "DRY_RUN_STOP"
