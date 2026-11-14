# CiteBench results: citebench_dev-exact (exact)

Items: **150** · accuracy **0.980** · macro-F1 **0.987** · ECE 0.040

## Fake-citation detection (fabricated ∪ misattributed)

| Precision | Recall | F1 | FPR on real citations | Real → unverifiable |
| --- | --- | --- | --- | --- |
| 0.983 | 0.983 | 0.983 | 0.011 | 0.011 |

## Confusion matrix (rows = gold, columns = predicted)

| gold \ pred | VERIFIED | VERIFIED_WITH_ERRORS | MISATTRIBUTED | FABRICATED | UNVERIFIABLE |
| --- | --- | --- | --- | --- | --- |
| VERIFIED | 59 | 0 | 0 | 0 | 1 |
| VERIFIED_WITH_ERRORS | 0 | 29 | 0 | 1 | 0 |
| MISATTRIBUTED | 0 | 0 | 20 | 0 | 0 |
| FABRICATED | 0 | 0 | 0 | 39 | 1 |

## By perturbation

| Perturbation | n | Accuracy | Flagged as fake |
| --- | --- | --- | --- |
| author_swap | 10 | 1.000 | 1.000 |
| bogus_doi | 10 | 0.900 | 0.100 |
| borrowed_doi | 10 | 1.000 | 1.000 |
| fabricated | 30 | 0.967 | 0.967 |
| none | 60 | 0.983 | 0.000 |
| venue_swap | 10 | 1.000 | 0.000 |
| wrong_doi | 10 | 1.000 | 1.000 |
| year_shift | 10 | 1.000 | 0.000 |

Latency p50 4 ms · p95 27997 ms · LLM tokens per citation 0
