# CiteBench results: citebench_dev-full-recheck (full)

Items: **4** · accuracy **1.000** · macro-F1 **1.000** · ECE 0.021

## Fake-citation detection (fabricated ∪ misattributed)

| Precision | Recall | F1 | FPR on real citations | Real → unverifiable |
| --- | --- | --- | --- | --- |
| 1.000 | 1.000 | 1.000 | 0.000 | 0.000 |

## Confusion matrix (rows = gold, columns = predicted)

| gold \ pred | VERIFIED | VERIFIED_WITH_ERRORS | MISATTRIBUTED | FABRICATED | UNVERIFIABLE |
| --- | --- | --- | --- | --- | --- |
| VERIFIED | 1 | 0 | 0 | 0 | 0 |
| VERIFIED_WITH_ERRORS | 0 | 1 | 0 | 0 | 0 |
| MISATTRIBUTED | 0 | 0 | 1 | 0 | 0 |
| FABRICATED | 0 | 0 | 0 | 1 | 0 |

## By perturbation

| Perturbation | n | Accuracy | Flagged as fake |
| --- | --- | --- | --- |
| author_swap | 1 | 1.000 | 1.000 |
| bogus_doi | 1 | 1.000 | 0.000 |
| fabricated | 1 | 1.000 | 1.000 |
| none | 1 | 1.000 | 0.000 |

Latency p50 30 ms · p95 19379 ms · LLM tokens per citation 1176 · LLM explanations passing grounding check 100%
