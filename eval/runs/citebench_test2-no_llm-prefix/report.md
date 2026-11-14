# CiteBench results: citebench_test2-no_llm (no_llm)

Items: **150** · accuracy **0.987** · macro-F1 **0.986** · ECE 0.061

## Fake-citation detection (fabricated ∪ misattributed)

| Precision | Recall | F1 | FPR on real citations | Real → unverifiable |
| --- | --- | --- | --- | --- |
| 0.984 | 1.000 | 0.992 | 0.011 | 0.000 |

## Confusion matrix (rows = gold, columns = predicted)

| gold \ pred | VERIFIED | VERIFIED_WITH_ERRORS | MISATTRIBUTED | FABRICATED | UNVERIFIABLE |
| --- | --- | --- | --- | --- | --- |
| VERIFIED | 59 | 1 | 0 | 0 | 0 |
| VERIFIED_WITH_ERRORS | 0 | 29 | 0 | 1 | 0 |
| MISATTRIBUTED | 0 | 0 | 20 | 0 | 0 |
| FABRICATED | 0 | 0 | 0 | 40 | 0 |

## By perturbation

| Perturbation | n | Accuracy | Flagged as fake |
| --- | --- | --- | --- |
| author_swap | 10 | 1.000 | 1.000 |
| bogus_doi | 10 | 0.900 | 0.100 |
| borrowed_doi | 10 | 1.000 | 1.000 |
| fabricated | 30 | 1.000 | 1.000 |
| none | 60 | 0.983 | 0.000 |
| venue_swap | 10 | 1.000 | 0.000 |
| wrong_doi | 10 | 1.000 | 1.000 |
| year_shift | 10 | 1.000 | 0.000 |

Latency p50 1195 ms · p95 19720 ms · LLM tokens per citation 0
