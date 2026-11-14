# Self-review of the report

This is the adversarial review the paper-writing guidelines ask for: a claim-evidence map of the
abstract and introduction, then a five-dimension check. Each item is marked pass,
needs revision (and what was done), or open (a limitation stated in the paper).

## Claim-evidence map

| Claim (abstract / introduction) | Evidence | Status |
| --- | --- | --- |
| LLM-only judges wrongly reject correct citations they do not recognise | Table 1, Table 2: 10.0–31.7% of correct `test3` citations called fake by three models | supported |
| The deterministic pipeline reaches 0.960 accuracy and 1.000 fake F1 with 0% of correct citations called fake on a fresh held-out split | Table 1 (`citebench_test3-no_llm`), scored once | supported |
| A DOI-lookup baseline detects none of the fabrications | Table 1 (`citebench_test3-doi_only`): recall 0.000 | supported |
| LLM explanations pass the grounding validator in 19 of 19 cases | Section 6.5, `citebench_dev-full-explained` | supported (small n, stated) |
| The claim check flags 92% of mismatched claims with no false alarms on 25 papers | Section 6.5, `claims-citebench_test2` | supported (synthetic claims, stated) |
| CiteGuard detects every fake without a false alarm, while LLM-only judges call 10–32% of correct citations fake | Table 1 | supported |
| The LLM never decides existence | Section 4, Figure 1; code: the adjudicator can only return a retrieved ID; a reformulation only adds candidates | supported (design claim) |
| Fuzzy linkage and the LLM improve verdicts | **Not claimed**: Section 6.4 reports that they do not, on CiteBench | revised to a negative finding |

## Five-dimension review

**1. Contribution.**
- New knowledge: on one benchmark and protocol, retrieval-grounded verification against three
  LLM-only judges and a DOI baseline, with FPR on correct citations reported separately. *Pass.*
- Risk: retrieval-first citation checking is not new (CiteCheck, CiteTracer). The paper says this in
  Related Work and claims only the differences: rules decide rather than an LLM score, validated
  explanations, and a claim check. *Pass.*

**2. Writing clarity.**
- Reproducibility: Appendix B gives the exact commands, and every table cell comes from
  `make_results.py`. *Pass.*
- Terms: "fake" is defined once (fabricated ∪ misattributed) and used consistently; "FPR correct" and
  "FPR real" are defined in Section 3 and in the Table 1 caption. *Pass.*

**3. Experimental strength.**
- Baselines: three LLM-only judges from two model families, a DOI baseline and heuristics. The
  released systems of other papers were not run, which is stated under Comparability. *Open.*
- Ceiling effect: CiteGuard scores 1.000 fake F1, so the benchmark cannot separate the CiteGuard
  rungs. The paper says this plainly and draws the negative conclusion about fuzzy linkage and the LLM.
  *Needs revision → done.*

**4. Evaluation completeness.**
- Ablation: there is a ladder on `dev`, and the exact-matching rung was also run on `test3`. *Pass.*
- Missing: a chatbot-written split with human labels, and hard negatives. These are listed as the
  first limitation and future work. *Open.*
- Statistical uncertainty: with 150 items, one error moves accuracy by 0.7 points; this is stated.
  No confidence intervals are computed. *Open.*

**5. Method design soundness.**
- Realism: the inputs are synthetic but rendered in four real citation styles from two indexes, and
  the demo and self-check use real inputs. *Pass with caveat.*
- Hidden defects: the demo exposed a label-only headline (now fixed, with a regression test) and an
  unwarranted inference that passes string-level grounding (stated as a limitation). *Pass.*
- LLM-only prompt fairness: "exists exactly as cited" makes "fake" defensible for real citations with
  errors, so FPR on correct citations is reported separately. *Pass.*
