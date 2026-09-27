import pytest

import openplc_sil as sil


@pytest.fixture
def plc():
    """Fresh program instance: initial values, t = 0, every permissive healthy."""
    p = sil.Plc()
    p.healthy()
    p.scan(2)
    return p


@pytest.fixture
def idle(plc):
    """STOPPED -> RESETTING -> IDLE via the reset pushbutton."""
    plc.pulse("PB_RESET")
    assert plc.state() == sil.IDLE
    return plc


@pytest.fixture
def in_cycle(idle):
    """IDLE -> STARTING -> EXECUTE, waiting for a part at the infeed (seq 10)."""
    idle.pulse("PB_START")
    idle.run(ms=600)
    assert idle.state() == sil.EXECUTE
    assert idle.seq() == 10
    return idle


@pytest.fixture
def washing(in_cycle):
    """Part indexed into the chamber, pump proven, spray timer running (seq 30)."""
    plc = in_cycle
    plc.set("PE_INFEED", True)
    plc.scan(2)
    plc.set("PE_CHAMBER", True)
    plc.scan(2)
    assert plc.seq() == 30
    plc.follow_pump_aux()
    plc.scan(2)
    assert plc.get("PUMP_RUN") and plc.get("DOOR_LOCK")
    return plc
