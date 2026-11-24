"""Dashboard parsers turn pytest JUnit XML and Vitest JSON into one shape."""

from devtools.dashboard import parse_junit, parse_vitest

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="3">
  <testcase classname="tests.test_app" name="test_health_reports_ok" time="0.01"/>
  <testcase classname="tests.test_hybrid" name="test_fallback" time="0.02">
    <failure message="assert 1 == 2">trace</failure>
  </testcase>
  <testcase classname="tests.test_x" name="test_skip" time="0.00"><skipped/></testcase>
</testsuite></testsuites>"""

VITEST = {
    "numTotalTests": 2,
    "testResults": [
        {
            "name": "C:/x/g2-app/src/gestures.test.ts",
            "assertionResults": [
                {"ancestorTitles": ["classifyGesture"], "title": "reads tap", "status": "passed", "duration": 1.5},
                {"ancestorTitles": ["helloScreen"], "title": "shows name", "status": "failed", "duration": 0.4},
            ],
        }
    ],
}


def test_parse_junit_reads_pass_fail_and_skip():
    tests = parse_junit(JUNIT)
    assert [t["status"] for t in tests] == ["passed", "failed", "skipped"]
    assert tests[0]["file"] == "test_app"
    assert tests[0]["name"] == "test_health_reports_ok"
    assert tests[1]["message"] == "assert 1 == 2"


def test_parse_vitest_reads_file_group_and_status():
    tests = parse_vitest(VITEST)
    assert tests[0] == {
        "file": "gestures.test.ts", "name": "classifyGesture > reads tap",
        "status": "passed", "ms": 1.5, "message": "",
    }
    assert tests[1]["status"] == "failed"


def test_parsers_survive_missing_or_broken_input():
    assert parse_junit("") == []
    assert parse_junit("<not xml") == []
    assert parse_vitest({}) == []
