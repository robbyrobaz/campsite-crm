import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import classify_leakage


def test_realistic_gap_not_flagged_as_leakage():
    flagged, note = classify_leakage(0.979, 0.935, 0.934)
    assert flagged is False
    assert note is None


def test_near_perfect_train_and_test_is_flagged():
    flagged, note = classify_leakage(0.995, 0.992, 0.991)
    assert flagged is True
    assert "likely leakage" in note.lower()


def test_no_oos_only_flags_when_train_is_extreme():
    flagged_mid, _ = classify_leakage(0.97, None, None)
    flagged_hi, note_hi = classify_leakage(0.996, None, None)
    assert flagged_mid is False
    assert flagged_hi is True
    assert "no test/oos" in note_hi.lower()
