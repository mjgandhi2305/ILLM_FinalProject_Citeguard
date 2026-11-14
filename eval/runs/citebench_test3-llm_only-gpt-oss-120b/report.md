# CiteBench results: citebench_test3-llm_only-gpt-oss-120b (llm_only)

Items: **150** · accuracy **0.327** · macro-F1 **0.244** · ECE 0.386

## Fake-citation detection (fabricated ∪ misattributed)

| Precision | Recall | F1 | FPR on real citations | Real → unverifiable |
| --- | --- | --- | --- | --- |
| 0.667 | 0.800 | 0.727 | 0.267 | 0.578 |

## Confusion matrix (rows = gold, columns = predicted)

| gold \ pred | VERIFIED | VERIFIED_WITH_ERRORS | MISATTRIBUTED | FABRICATED | UNVERIFIABLE |
| --- | --- | --- | --- | --- | --- |
| VERIFIED | 12 | 0 | 0 | 8 | 40 |
| VERIFIED_WITH_ERRORS | 2 | 0 | 0 | 16 | 12 |
| MISATTRIBUTED | 2 | 0 | 0 | 11 | 7 |
| FABRICATED | 0 | 0 | 0 | 37 | 3 |

## By perturbation

| Perturbation | n | Accuracy | Flagged as fake |
| --- | --- | --- | --- |
| author_swap | 10 | 0.000 | 0.300 |
| bogus_doi | 10 | 0.000 | 0.600 |
| borrowed_doi | 10 | 1.000 | 1.000 |
| fabricated | 30 | 0.900 | 0.900 |
| none | 60 | 0.200 | 0.133 |
| venue_swap | 10 | 0.000 | 0.900 |
| wrong_doi | 10 | 0.000 | 0.800 |
| year_shift | 10 | 0.000 | 0.100 |

Latency p50 6618 ms · p95 7763 ms · LLM tokens per citation 671
