# CiteBench results: citebench_dev-llm_only (llm_only)

Items: **150** · accuracy **0.340** · macro-F1 **0.249** · ECE 0.382

## Fake-citation detection (fabricated ∪ misattributed)

| Precision | Recall | F1 | FPR on real citations | Real → unverifiable |
| --- | --- | --- | --- | --- |
| 0.595 | 0.783 | 0.676 | 0.356 | 0.478 |

## Confusion matrix (rows = gold, columns = predicted)

| gold \ pred | VERIFIED | VERIFIED_WITH_ERRORS | MISATTRIBUTED | FABRICATED | UNVERIFIABLE |
| --- | --- | --- | --- | --- | --- |
| VERIFIED | 15 | 0 | 0 | 9 | 36 |
| VERIFIED_WITH_ERRORS | 0 | 0 | 0 | 23 | 7 |
| MISATTRIBUTED | 2 | 0 | 0 | 11 | 7 |
| FABRICATED | 0 | 0 | 0 | 36 | 4 |

## By perturbation

| Perturbation | n | Accuracy | Flagged as fake |
| --- | --- | --- | --- |
| author_swap | 10 | 0.000 | 0.200 |
| bogus_doi | 10 | 0.000 | 0.900 |
| borrowed_doi | 10 | 1.000 | 1.000 |
| fabricated | 30 | 0.867 | 0.867 |
| none | 60 | 0.250 | 0.150 |
| venue_swap | 10 | 0.000 | 1.000 |
| wrong_doi | 10 | 0.000 | 0.900 |
| year_shift | 10 | 0.000 | 0.400 |

Latency p50 6541 ms · p95 7476 ms · LLM tokens per citation 661
