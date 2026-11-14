# CiteBench results: citebench_dev-full-explained (full)

Items: **30** · accuracy **1.000** · macro-F1 **1.000** · ECE 0.020

## Fake-citation detection (fabricated ∪ misattributed)

| Precision | Recall | F1 | FPR on real citations | Real → unverifiable |
| --- | --- | --- | --- | --- |
| 1.000 | 1.000 | 1.000 | 0.000 | 0.000 |

## Confusion matrix (rows = gold, columns = predicted)

| gold \ pred | VERIFIED | VERIFIED_WITH_ERRORS | MISATTRIBUTED | FABRICATED | UNVERIFIABLE |
| --- | --- | --- | --- | --- | --- |
| VERIFIED | 11 | 0 | 0 | 0 | 0 |
| VERIFIED_WITH_ERRORS | 0 | 7 | 0 | 0 | 0 |
| MISATTRIBUTED | 0 | 0 | 3 | 0 | 0 |
| FABRICATED | 0 | 0 | 0 | 9 | 0 |

## By perturbation

| Perturbation | n | Accuracy | Flagged as fake |
| --- | --- | --- | --- |
| author_swap | 1 | 1.000 | 1.000 |
| bogus_doi | 3 | 1.000 | 0.000 |
| borrowed_doi | 2 | 1.000 | 1.000 |
| fabricated | 7 | 1.000 | 1.000 |
| none | 11 | 1.000 | 0.000 |
| venue_swap | 2 | 1.000 | 0.000 |
| wrong_doi | 2 | 1.000 | 1.000 |
| year_shift | 2 | 1.000 | 0.000 |

Latency p50 18931 ms · p95 74508 ms · LLM tokens per citation 1972 · LLM explanations passing grounding check 100%
