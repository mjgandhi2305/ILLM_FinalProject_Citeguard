# CiteBench results: citebench_dev-full (full)

Items: **150** · accuracy **0.987** · macro-F1 **0.995** · ECE 0.037

## Fake-citation detection (fabricated ∪ misattributed)

| Precision | Recall | F1 | FPR on real citations | Real → unverifiable |
| --- | --- | --- | --- | --- |
| 1.000 | 0.983 | 0.992 | 0.000 | 0.011 |

## Confusion matrix (rows = gold, columns = predicted)

| gold \ pred | VERIFIED | VERIFIED_WITH_ERRORS | MISATTRIBUTED | FABRICATED | UNVERIFIABLE |
| --- | --- | --- | --- | --- | --- |
| VERIFIED | 59 | 0 | 0 | 0 | 1 |
| VERIFIED_WITH_ERRORS | 0 | 30 | 0 | 0 | 0 |
| MISATTRIBUTED | 0 | 0 | 20 | 0 | 0 |
| FABRICATED | 0 | 0 | 0 | 39 | 1 |

## By perturbation

| Perturbation | n | Accuracy | Flagged as fake |
| --- | --- | --- | --- |
| author_swap | 10 | 1.000 | 1.000 |
| bogus_doi | 10 | 1.000 | 0.000 |
| borrowed_doi | 10 | 1.000 | 1.000 |
| fabricated | 30 | 0.967 | 0.967 |
| none | 60 | 0.983 | 0.000 |
| venue_swap | 10 | 1.000 | 0.000 |
| wrong_doi | 10 | 1.000 | 1.000 |
| year_shift | 10 | 1.000 | 0.000 |

Latency p50 1505 ms · p95 27981 ms · LLM tokens per citation 250
