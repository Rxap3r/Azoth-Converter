import gc

import pytest

pytest.importorskip("pytestqt")


def test_memory_clean_up_runs_only_on_the_main_thread(qtbot):
    from azoth.gui.main_thread_gc import MainThreadGC

    collector = MainThreadGC()
    try:
        assert not gc.isenabled()  # never automatically, e.g. in a conversion thread
        garbage = []
        for _ in range(collector.threshold[0] + 10):
            cycle = []
            cycle.append(cycle)
            garbage.append(cycle)
        del garbage, cycle
        assert gc.get_count()[0] > collector.threshold[0]
        collector.check()  # what the timer does, in the main thread
        assert gc.get_count()[0] < collector.threshold[0]
    finally:
        collector.stop()
    assert gc.isenabled()
