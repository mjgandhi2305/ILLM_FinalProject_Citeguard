# CiteBench results: citebench_test3-full (full)

Items: **150** · accuracy **0.960** · macro-F1 **0.964** · ECE 0.017

## Fake-citation detection (fabricated ∪ misattributed)

| Precision | Recall | F1 | FPR on real citations | Real → unverifiable |
| --- | --- | --- | --- | --- |
| 1.000 | 1.000 | 1.000 | 0.000 | 0.000 |

## Confusion matrix (rows = gold, columns = predicted)

| gold \ pred | VERIFIED | VERIFIED_WITH_ERRORS | MISATTRIBUTED | FABRICATED | UNVERIFIABLE |
| --- | --- | --- | --- | --- | --- |
| VERIFIED | 54 | 6 | 0 | 0 | 0 |
| VERIFIED_WITH_ERRORS | 0 | 30 | 0 | 0 | 0 |
| MISATTRIBUTED | 0 | 0 | 20 | 0 | 0 |
| FABRICATED | 0 | 0 | 0 | 40 | 0 |

## By perturbation

| Perturbation | n | Accuracy | Flagged as fake |
| --- | --- | --- | --- |
| author_swap | 10 | 1.000 | 1.000 |
| bogus_doi | 10 | 1.000 | 0.000 |
| borrowed_doi | 10 | 1.000 | 1.000 |
| fabricated | 30 | 1.000 | 1.000 |
| none | 60 | 0.900 | 0.000 |
| venue_swap | 10 | 1.000 | 0.000 |
| wrong_doi | 10 | 1.000 | 1.000 |
| year_shift | 10 | 1.000 | 0.000 |

Latency p50 5 ms · p95 51578 ms · LLM tokens per citation 241
