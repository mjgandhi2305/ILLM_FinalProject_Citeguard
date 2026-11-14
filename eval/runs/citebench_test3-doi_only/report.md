# CiteBench results: citebench_test3-doi_only (doi_only)

Items: **150** · accuracy **0.400** · macro-F1 **0.150** · ECE 0.305

## Fake-citation detection (fabricated ∪ misattributed)

| Precision | Recall | F1 | FPR on real citations | Real → unverifiable |
| --- | --- | --- | --- | --- |
| 0.000 | 0.000 | 0.000 | 0.111 | 0.000 |

## Confusion matrix (rows = gold, columns = predicted)

| gold \ pred | VERIFIED | VERIFIED_WITH_ERRORS | MISATTRIBUTED | FABRICATED | UNVERIFIABLE |
| --- | --- | --- | --- | --- | --- |
| VERIFIED | 60 | 0 | 0 | 0 | 0 |
| VERIFIED_WITH_ERRORS | 20 | 0 | 0 | 10 | 0 |
| MISATTRIBUTED | 20 | 0 | 0 | 0 | 0 |
| FABRICATED | 40 | 0 | 0 | 0 | 0 |

## By perturbation

| Perturbation | n | Accuracy | Flagged as fake |
| --- | --- | --- | --- |
| author_swap | 10 | 0.000 | 0.000 |
| bogus_doi | 10 | 0.000 | 1.000 |
| borrowed_doi | 10 | 0.000 | 0.000 |
| fabricated | 30 | 0.000 | 0.000 |
| none | 60 | 1.000 | 0.000 |
| venue_swap | 10 | 0.000 | 0.000 |
| wrong_doi | 10 | 0.000 | 0.000 |
| year_shift | 10 | 0.000 | 0.000 |

Latency p50 0 ms · p95 370 ms · LLM tokens per citation 0
