"""The eval gate: a metric may drop by the tolerance, but a must-pass case may never fail."""
from evals.gate import compare


def _baseline(**extra):
    return {"tolerance": 2, "metrics": {"Intent": {"passed": 60, "total": 63, "failing": ["A", "B", "C"]}}, **extra}


def _current(failing):
    return {"Intent": {"passed": 63 - len(failing), "total": 63, "failing": failing}}


def test_a_drop_within_the_tolerance_passes():
    ok, lines = compare(_baseline(), _current(["A", "B", "C", "D", "E"]))
    assert ok and lines[0].startswith("**Eval gate passed**")


def test_a_drop_beyond_the_tolerance_fails():
    ok, lines = compare(_baseline(), _current(["A", "B", "C", "D", "E", "F"]))
    assert not ok and "dropped more than the tolerance" in lines[0]


def test_a_must_pass_case_fails_the_gate_even_within_the_tolerance():
    ok, lines = compare(_baseline(must_pass={"G110": ["Intent"]}), _current(["A", "B", "C", "G110"]))
    assert not ok and "must-pass case failed" in lines[0]
    assert any("G110 (Intent)" in line for line in lines)


def test_a_must_pass_case_on_a_metric_that_was_not_measured_fails():
    ok, _ = compare(_baseline(must_pass={"G110": ["Review routing"]}), _current(["A", "B", "C"]))
    assert not ok


def test_passing_must_pass_cases_are_reported():
    ok, lines = compare(_baseline(must_pass={"G110": ["Intent"]}), _current(["A", "B", "C"]))
    assert ok and "Must-pass cases (1): all passed" in lines
