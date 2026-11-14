# CiteBench results: citebench_dev-no_llm (no_llm)

Items: **150** · accuracy **1.000** · macro-F1 **1.000** · ECE 0.028

## Fake-citation detection (fabricated ∪ misattributed)

| Precision | Recall | F1 | FPR on real citations | Real → unverifiable |
| --- | --- | --- | --- | --- |
| 1.000 | 1.000 | 1.000 | 0.000 | 0.000 |

## Confusion matrix (rows = gold, columns = predicted)

| gold \ pred | VERIFIED | VERIFIED_WITH_ERRORS | MISATTRIBUTED | FABRICATED | UNVERIFIABLE |
| --- | --- | --- | --- | --- | --- |
| VERIFIED | 60 | 0 | 0 | 0 | 0 |
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
| none | 60 | 1.000 | 0.000 |
| venue_swap | 10 | 1.000 | 0.000 |
| wrong_doi | 10 | 1.000 | 1.000 |
| year_shift | 10 | 1.000 | 0.000 |

Latency p50 8 ms · p95 19 ms · LLM tokens per citation 0
