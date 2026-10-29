"""Manual slice evaluation at the global top-10% contact cutoff.

Data-quality errors block the build. A measured recall gap only warns so the
human approver sees the disparity without disguising it as a failed model gate.
"""

from evaluation.model_gates import tier_recalls, warn_fairness_gap


def test_all_loyalty_tiers_have_usable_metrics(evaluation_metrics):
    assert len(tier_recalls(evaluation_metrics)) == 4


def test_loyalty_recall_gap_is_visible_to_approver(evaluation_metrics):
    gap = warn_fairness_gap(evaluation_metrics)
    assert 0 <= gap <= 1
