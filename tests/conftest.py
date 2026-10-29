"""Pytest configuration for the NorthStar Lab 4 test suite.

Why this file exists (defect 50, 2026-08-03):

`pytest_addoption` is a *initialisation* hook. Pytest only collects it from
`conftest.py` files and installed plugins -- never from a test module. It had
been defined at the top of `tests/test_model.py`, which meant the command
printed in that file's own docstring:

    pytest tests/test_model.py -v --model-path ./test_model.xgb

failed before collecting a single test:

    error: unrecognized arguments: --model-path

Every student running the documented command hit this. Same class of defect as
the Lab 5 canary script that resolved its default sample CSV against the
current working directory: the starter kit was never executed the way the
instructions tell you to execute it.

Keep option registration here.
"""

import os
import json
from pathlib import Path

import pytest

from evaluation.model_gates import validate_evaluation_metrics


def pytest_addoption(parser):
    parser.addoption(
        "--model-path", action="store", default=None,
        help="Path to trained XGBoost model (.xgb file)"
    )
    parser.addoption(
        "--eval-metrics-path", action="store", default=None,
        help="Path to evaluation_metrics.json emitted by the training script"
    )


def pytest_configure(config):
    """Let --eval-metrics-path drive the env var the metrics gate reads.

    The stored-metrics gate reads EVAL_METRICS_PATH so it works unchanged in
    CodeBuild, where the path comes from the build environment rather than the
    command line. This just makes the two agree when running locally.
    """
    p = config.getoption("--eval-metrics-path")
    if p:
        os.environ["EVAL_METRICS_PATH"] = p


@pytest.fixture(scope="session")
def evaluation_metrics():
    path = Path(os.environ.get("EVAL_METRICS_PATH", "output/evaluation_metrics.json"))
    if not path.is_file():
        pytest.fail(f"Evaluation metrics missing: {path}. Train the candidate first.", pytrace=False)
    with path.open(encoding="utf-8") as stream:
        metrics = json.load(stream)
    validate_evaluation_metrics(metrics)
    return metrics
