import random

from citeguard.domain.models import Verdict
from citeguard.eval.build import fabricated_title, perturb, render
from citeguard.eval.fit_linkage import fit, log_loss, vectorize
from citeguard.eval.metrics import (
    Prediction,
    binary_fake_metrics,
    expected_calibration_error,
    summarize,
)
from tests.conftest import ATTENTION, BERT, DEEP_LEARNING, OTHER_HINTON


def p(gold: Verdict, pred: Verdict, conf: float = 0.9) -> Prediction:
    return Prediction(id="x", gold=gold, pred=pred, confidence=conf, split="real")


def test_fake_detection_metrics() -> None:
    preds = [
        p(Verdict.FABRICATED, Verdict.FABRICATED),
        p(Verdict.MISATTRIBUTED, Verdict.VERIFIED_WITH_ERRORS),  # missed
        p(Verdict.VERIFIED, Verdict.FABRICATED),  # false positive on a real citation
        p(Verdict.VERIFIED, Verdict.VERIFIED),
    ]
    m = binary_fake_metrics(preds)
    assert m["precision"] == 0.5 and m["recall"] == 0.5
    assert m["false_positive_rate_on_real"] == 0.5
    s = summarize(preds)
    assert s["confusion"]["VERIFIED"]["FABRICATED"] == 1 and s["n"] == 4


def test_ece_perfectly_calibrated() -> None:
    preds = [p(Verdict.VERIFIED, Verdict.VERIFIED, 1.0)] * 4
    assert expected_calibration_error(preds) == 0.0


def test_perturbations_have_expected_labels() -> None:
    rng = random.Random(1)
    pool = [ATTENTION, DEEP_LEARNING, BERT, OTHER_HINTON]
    year = perturb("year_shift", DEEP_LEARNING, pool, rng)
    assert year and year[1] == Verdict.VERIFIED_WITH_ERRORS and year[0].year != 2015
    fab = perturb("fabricated", DEEP_LEARNING, pool, rng)
    assert fab and fab[1] == Verdict.FABRICATED and fab[0].doi is None
    swap = perturb("author_swap", ATTENTION, pool, rng)
    assert swap and swap[1] == Verdict.MISATTRIBUTED
    assert len(fabricated_title(rng).split()) >= 5
    text, kind, _ = render(DEEP_LEARNING, rng, keep_doi=False)
    assert "10.1038" not in text and kind in ("citation", "bibtex")


def test_linkage_fit_learns_separable_data() -> None:
    same = {"title_sim": 1.0, "author_f1": 1.0, "first_author": 1.0, "year_delta": 0,
            "venue_sim": 1.0, "id_match": None}  # fmt: skip
    diff = {"title_sim": 0.3, "author_f1": 0.0, "first_author": 0.0, "year_delta": 5,
            "venue_sim": 0.1, "id_match": None}  # fmt: skip
    rows = [(vectorize(same), 1)] * 30 + [(vectorize(diff), 0)] * 30
    b, w = fit(rows, epochs=300)
    assert log_loss(rows, b, w) < 0.1
