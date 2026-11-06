"""Refit the record-linkage weights on candidate features collected by `eval.run`.

    python -m citeguard.eval.fit_linkage ../eval/runs/<run>/predictions.jsonl --out linkage.json

Plain L2-regularised logistic regression (no numpy needed: a dozen features, a few thousand
rows). The fitted weights map 1:1 onto `LinkageModel` fields."""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Any

FIELDS = [
    "w_title", "w_author_f1", "w_first_author", "author_offset", "year_exact", "year_off_by_one",
    "year_off_by_two", "year_far", "venue_good", "venue_bad", "id_agree", "id_disagree",
]  # fmt: skip


def vectorize(f: dict[str, Any]) -> list[float]:
    has_auth = f.get("author_f1") is not None
    yd = f.get("year_delta")
    vs = f.get("venue_sim")
    idm = f.get("id_match")
    return [
        f["title_sim"] - 0.5,
        f.get("author_f1") or 0.0,
        f.get("first_author") or 0.0,
        1.0 if has_auth else 0.0,
        1.0 if yd == 0 else 0.0,
        1.0 if yd == 1 else 0.0,
        1.0 if yd == 2 else 0.0,
        1.0 if yd is not None and yd > 2 else 0.0,
        1.0 if vs is not None and vs >= 0.8 else 0.0,
        1.0 if vs is not None and vs < 0.5 else 0.0,
        1.0 if idm is True else 0.0,
        1.0 if idm is False else 0.0,
    ]


def fit(
    rows: list[tuple[list[float], int]], l2: float = 0.01, lr: float = 0.5, epochs: int = 800
) -> tuple[float, list[float]]:
    n_feat = len(rows[0][0])
    w = [0.0] * n_feat
    b = 0.0
    n = len(rows)
    for _ in range(epochs):
        gw = [0.0] * n_feat
        gb = 0.0
        for x, y in rows:
            z = b + sum(wi * xi for wi, xi in zip(w, x, strict=True))
            p = 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))
            err = p - y
            gb += err
            for i, xi in enumerate(x):
                gw[i] += err * xi
        b -= lr * gb / n
        w = [wi - lr * (gwi / n + l2 * wi) for wi, gwi in zip(w, gw, strict=True)]
    return b, w


def log_loss(rows: list[tuple[list[float], int]], b: float, w: list[float]) -> float:
    total = 0.0
    for x, y in rows:
        z = b + sum(wi * xi for wi, xi in zip(w, x, strict=True))
        p = min(1 - 1e-9, max(1e-9, 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))))
        total += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return total / len(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("predictions", type=Path, nargs="+")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    rows: list[tuple[list[float], int]] = []
    for path in args.predictions:
        for line in path.read_text().splitlines():
            rec = json.loads(line)
            for c in (rec.get("extra") or {}).get("linkage", []):
                rows.append((vectorize(c["features"]), int(c["same"])))
    if len(rows) < 50:
        raise SystemExit(f"only {len(rows)} candidate rows; run a larger evaluation first")
    random.Random(0).shuffle(rows)
    cut = int(0.8 * len(rows))
    train, test = rows[:cut], rows[cut:]
    b, w = fit(train)
    from citeguard.match.linkage import DEFAULT_MODEL

    default_b = DEFAULT_MODEL.bias
    default_w = [getattr(DEFAULT_MODEL, f) for f in FIELDS]
    print(f"rows: {len(rows)} (positives {sum(y for _, y in rows)})")
    print(f"held-out log-loss  default {log_loss(test, default_b, default_w):.4f}  "
          f"fitted {log_loss(test, b, w):.4f}")  # fmt: skip
    weights = {"bias": round(b, 4), **{f: round(v, 4) for f, v in zip(FIELDS, w, strict=True)}}
    args.out.write_text(json.dumps(weights, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
