# CiteBench results: citebench_test3-llm_only-gpt-oss-20b (llm_only)

Items: **150** · accuracy **0.473** · macro-F1 **0.323** · ECE 0.328

## Fake-citation detection (fabricated ∪ misattributed)

| Precision | Recall | F1 | FPR on real citations | Real → unverifiable |
| --- | --- | --- | --- | --- |
| 0.632 | 0.800 | 0.706 | 0.311 | 0.267 |

## Confusion matrix (rows = gold, columns = predicted)

| gold \ pred | VERIFIED | VERIFIED_WITH_ERRORS | MISATTRIBUTED | FABRICATED | UNVERIFIABLE |
| --- | --- | --- | --- | --- | --- |
| VERIFIED | 34 | 0 | 0 | 6 | 20 |
| VERIFIED_WITH_ERRORS | 4 | 0 | 0 | 22 | 4 |
| MISATTRIBUTED | 5 | 0 | 0 | 11 | 4 |
| FABRICATED | 1 | 0 | 0 | 37 | 2 |

## By perturbation

| Perturbation | n | Accuracy | Flagged as fake |
| --- | --- | --- | --- |
| author_swap | 10 | 0.000 | 0.200 |
| bogus_doi | 10 | 0.000 | 0.900 |
| borrowed_doi | 10 | 1.000 | 1.000 |
| fabricated | 30 | 0.900 | 0.900 |
| none | 60 | 0.567 | 0.100 |
| venue_swap | 10 | 0.000 | 0.900 |
| wrong_doi | 10 | 0.000 | 0.900 |
| year_shift | 10 | 0.000 | 0.400 |

Latency p50 6766 ms · p95 8700 ms · LLM tokens per citation 784
