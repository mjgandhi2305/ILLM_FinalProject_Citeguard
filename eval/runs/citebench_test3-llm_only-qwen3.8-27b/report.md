# CiteBench results: citebench_test3-llm_only-qwen3.8-27b (llm_only)

Items: **150** · accuracy **0.367** · macro-F1 **0.264** · ECE 0.294

## Fake-citation detection (fabricated ∪ misattributed)

| Precision | Recall | F1 | FPR on real citations | Real → unverifiable |
| --- | --- | --- | --- | --- |
| 0.506 | 0.700 | 0.587 | 0.456 | 0.244 |

## Confusion matrix (rows = gold, columns = predicted)

| gold \ pred | VERIFIED | VERIFIED_WITH_ERRORS | MISATTRIBUTED | FABRICATED | UNVERIFIABLE |
| --- | --- | --- | --- | --- | --- |
| VERIFIED | 25 | 0 | 0 | 19 | 16 |
| VERIFIED_WITH_ERRORS | 2 | 0 | 0 | 22 | 6 |
| MISATTRIBUTED | 1 | 0 | 0 | 12 | 7 |
| FABRICATED | 0 | 0 | 0 | 30 | 10 |

## By perturbation

| Perturbation | n | Accuracy | Flagged as fake |
| --- | --- | --- | --- |
| author_swap | 10 | 0.000 | 0.400 |
| bogus_doi | 10 | 0.000 | 0.800 |
| borrowed_doi | 10 | 0.700 | 0.700 |
| fabricated | 30 | 0.767 | 0.767 |
| none | 60 | 0.417 | 0.317 |
| venue_swap | 10 | 0.000 | 0.900 |
| wrong_doi | 10 | 0.000 | 0.800 |
| year_shift | 10 | 0.000 | 0.500 |

Latency p50 8362 ms · p95 19355 ms · LLM tokens per citation 220
