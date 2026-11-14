# Evaluation

## CiteBench

There are three splits of 150 items each, built with the same recipe
(`python -m citeguard.eval.build --real 60 --perturbed 60 --fabricated 30 --seed N`). No two
splits share a DOI.

| Split | Seed | Role |
| --- | --- | --- |
| `citebench_dev.jsonl` | 7 | Development and error analysis |
| `citebench_test.jsonl` | 23 | First held-out split, scored once after the dev fixes |
| `citebench_test2.jsonl` | 41 | Second held-out split, scored once after the fixes from `test` |
| `citebench_test3.jsonl` | 59 | Third held-out split, built for the report and scored once with the final code (errors analysed, not fixed) |

Each held-out split counts as held out only until its first score. After that, its errors were
analysed and fixed, so later scores on it are optimistic.

| Group | n | How it is made | Gold label |
| --- | --- | --- | --- |
| Real | 60 | Random journal articles (1990–2024) sampled from **both** OpenAlex and Crossref, so ground truth does not come from a single index the system also queries. Rendered in APA, IEEE, Vancouver or BibTeX; DOI kept in only about half of them | `VERIFIED` |
| `year_shift` | 10 | Year moved by ±2–3 | `VERIFIED_WITH_ERRORS` |
| `venue_swap` | 10 | Venue replaced by another real venue | `VERIFIED_WITH_ERRORS` |
| `bogus_doi` | 10 | Real paper with a DOI that does not exist | `VERIFIED_WITH_ERRORS` |
| `author_swap` | 10 | Real title with another paper's authors | `MISATTRIBUTED` |
| `wrong_doi` | 10 | Real paper carrying another real paper's DOI | `MISATTRIBUTED` |
| `borrowed_doi` | 10 | Invented title carrying a real DOI (a typical LLM hallucination) | `FABRICATED` |
| `fabricated` | 30 | Invented, plausible title ("Contrastive Diffusion Models for Sepsis Detection in EHRs") with real-looking authors and a real venue | `FABRICATED` |

Limitations of these splits: the fabricated titles are template-generated, not produced by a
chatbot, and the real split contains only journal articles. The planned `llm_hallucinated` and
`hard_negative` splits (chatbot-written references with manual labels; books, theses, non-English
and very recent work) need a Groq key and annotation time. The tooling for them is listed under
"Next steps" below.

## How to run

```bash
cd backend
.venv/bin/python -m citeguard.eval.run --dataset ../eval/datasets/citebench_dev.jsonl --mode no_llm
.venv/bin/python -m citeguard.eval.run --dataset ../eval/datasets/citebench_dev.jsonl --mode full      # needs GROQ_API_KEY
.venv/bin/python -m citeguard.eval.run --dataset ../eval/datasets/citebench_dev.jsonl --mode llm_only  # baseline, needs GROQ_API_KEY
.venv/bin/python -m citeguard.eval.run --dataset ../eval/datasets/citebench_dev.jsonl --mode llm_only \
    --llm-model qwen/qwen3.8-27b --name citebench_dev-llm_only-qwen   # any Groq model, no fallback
.venv/bin/python -m citeguard.eval.run --dataset ../eval/datasets/citebench_dev.jsonl --mode doi_only  # HALLMARK's DOI-lookup baseline
.venv/bin/python -m citeguard.eval.fit_linkage ../eval/runs/citebench_dev-no_llm/predictions.jsonl --out linkage.json
```

Each run writes `eval/runs/<name>/{predictions.jsonl, summary.json, report.md}`. Runs resume
if interrupted, and source and LLM responses are cached, so re-runs are cheap.

## Metrics

- **Fake detection**, where the positive class is `FABRICATED` ∪ `MISATTRIBUTED`: precision, recall and F1.
- **False-positive rate on real citations**: real citations (`VERIFIED` or `VERIFIED_WITH_ERRORS`) wrongly called fake. This is the number that matters most to users.
- Five-class accuracy, macro-F1, confusion matrix, and expected calibration error (ECE) of the confidence.
- Per-perturbation accuracy, latency (p50/p95), and LLM tokens per citation.

## Results (2026-11-02/03)

### Fresh held-out split `test3` with baselines (2026-11-14)

`test3` (seed 59) was built for the report and scored once with the final code, by every system,
before any of its errors were examined. Those errors were then analysed but **not** fixed, so these
numbers remain a held-out estimate. They are the main result of the report (`paper/main.pdf`).

| System | Accuracy | Macro-F1 | Fake precision | Fake recall | Fake F1 | Correct citations called fake | Real citations called fake | LLM tokens / citation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Offline heuristics only | 0.400 | 0.145 | 1.000 | 0.050 | 0.095 | 0.0% | 0.0% | 0 |
| DOI lookup only (HALLMARK baseline) | 0.400 | 0.150 | — | 0.000 | 0.000 | 0.0% | 11.1% | 0 |
| LLM-only, `gpt-oss-20b` | 0.473 | 0.323 | 0.632 | 0.800 | 0.706 | 10.0% | 31.1% | 784 |
| LLM-only, `qwen/qwen3.8-27b` | 0.367 | 0.264 | 0.506 | 0.700 | 0.587 | 31.7% | 45.6% | 220 |
| LLM-only, `gpt-oss-120b` | 0.327 | 0.244 | 0.667 | 0.800 | 0.727 | 13.3% | 26.7% | 671 |
| CiteGuard, exact matching only | **0.967** | **0.970** | 1.000 | 1.000 | 1.000 | 0.0% | 0.0% | 0 |
| CiteGuard, `no_llm` | 0.960 | 0.964 | 1.000 | 1.000 | 1.000 | 0.0% | 0.0% | 0 |
| CiteGuard, `full` | 0.960 | 0.964 | 1.000 | 1.000 | 1.000 | 0.0% | 0.0% | 241 |

- **Every CiteGuard variant finds all 60 fakes and calls no real citation fake.** The best LLM-only
  judge calls 13% of perfectly correct citations fake, and Qwen 32%. `gpt-oss-120b` answers "unsure"
  for 40 of the 60 correct citations; Qwen returned invalid structured output for 27 of 150 even
  after a retry (counted as unsure).
- **The DOI lookup detects no fake**: fabricated titles either have no DOI or borrow a real one that
  resolves. Its only flags are the 10 real papers cited with a non-existent DOI.
- **Exact matching scores one citation higher than `no_llm`**, and `full` makes exactly the same
  predictions as `no_llm`. On synthetic citations, fuzzy linkage and the LLM do not improve verdicts;
  the gains came from parsing and the decision rules, which every CiteGuard rung shares.
- **The six CiteGuard errors** are all correct citations labelled `VERIFIED_WITH_ERRORS` (none called
  fake): "Gastrointestinal Stem Cells. II. …" cut at "II."; an IEEE title containing "(1998)" whose
  year was taken as the publication year; a Japanese record with ALL-CAPS names and volume "2017.23";
  and three citations rendered from garbled index metadata ("PG Student, D. o. S. E. C. c. J. H. I.").
- Latency is not reported for `test3`: the `no_llm` and `full` runs used a source cache already filled
  by the exact-matching run.

**Self-check.** CiteGuard on the report's own 30 references (`paper/verify_references.py`): 28
verified, 2 `VERIFIED_WITH_ERRORS`, 0 fake. Both flags are false alarms from how indexes record the
work (Crossref lists an LNCS paper under its series; Semantic Scholar gives an arXiv record the volume
`abs/1706.04599`).

**Found by recording the demo** (`demo/record_demo.js`), outside the benchmark:

18. The explainer once returned the headline "Real paper with errors:" with nothing after the label.
    The validator now rejects a label-only headline and asks again (regression test in
    `tests/unit/test_llm.py`).
19. Not fixed: one LLM reason inferred that a citation "may have been assembled from mixed sources".
    It cited real evidence IDs and quoted nothing false, so it passed the validator. The validator
    checks values and evidence IDs, not the soundness of an inference.

### Held-out estimates (the honest numbers)

Each split was scored once before anyone looked at its errors, with the deterministic pipeline
(`no_llm`, no LLM calls):

| Split, first score | Code at that time | Accuracy | Macro-F1 | Fake precision | Fake recall | FPR on real | ECE | Latency p50 / p95 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `test` (seed 23) | after the dev fixes | 0.960 | 0.960 | 0.923 | 1.000 | **0.056** | 0.058 | 1.3 s / 24 s |
| `test2` (seed 41) | after the `test` fixes | **0.987** | 0.986 | 0.984 | 1.000 | **0.011** | 0.061 | 1.2 s / 20 s |

On `test2`, 1 of 90 real citations was called fake, and no fabricated citation was missed. After
the `test2` fixes (below), all three splits score 150/150 in `no_llm` mode. That result is not a
held-out estimate. The next honest number needs a fresh split, ideally the chatbot-written one.

The p95 latency comes from source timeouts on uncached lookups (Crossref, OpenAlex and Semantic
Scholar each time out now and then), bounded by the 20 s call budget.

### Dev split: ablation ladder (150 items)

| System | Accuracy | Macro-F1 | Fake precision | Fake recall | Fake F1 | FPR on real | ECE | LLM tokens / citation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Heuristics only (offline signals) | 0.400 | 0.143 | — | 0.000 | 0.000 | 0.000 | 0.593 | 0 |
| + retrieval, exact matching only | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.028 | 0 |
| + fuzzy linkage, full rules (`no_llm`) | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.028 | 0 |
| + Groq LLM (`full`)* | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.023 | 250 |
| LLM-only baseline (`llm_only`)* | 0.340 | 0.249 | 0.595 | 0.783 | 0.676 | 0.356 | 0.382 | 661 |

\* Measured before the parse-recovery fix, to save Groq quota. `full` already scored 150/150
then.

`full` uses `openai/gpt-oss-20b` for parsing and query reformulation and `openai/gpt-oss-120b` for
adjudication; explanations are measured separately below. On its first, uncached run the
latency per citation was 1.5 s (p50) and 28 s (p95).

**What the LLM adds on these splits: nothing measurable.** Before the parse-recovery fix, the LLM
parser was the only thing that rescued pert-0044. Its Crossref record has garbage in the author
field ("Assoc. Prof. & Head of the Department EaCEDSECJHAPI"), and the heuristic parser took that
text for the title. The deterministic recovery now handles that case too. Synthetic citations are
tidy, so the LLM's main jobs are barely exercised here: parsing messy real-world references,
choosing between close candidates, and rewriting failed searches. The chatbot-written split is
where they should show their value. Until it exists, the evidence for the LLM is the explanation
quality (below), not verdict accuracy.

### The LLM-only baseline

`llm_only` asks `gpt-oss-120b` whether each citation "exists exactly as cited", answering yes, no
or unsure from its own knowledge. No retrieval is involved. It can only output VERIFIED,
FABRICATED or UNVERIFIABLE, so its five-class accuracy is capped by construction. The binary
numbers are the fair comparison:

| Gold group | n | Said "exists" | Said "fake" | Said "unsure" |
| --- | --- | --- | --- | --- |
| Correct citations of real papers | 60 | 15 | **9** | 36 |
| Real papers cited with errors | 30 | 0 | 23 | 7 |
| Misattributed | 20 | 2 | 11 | 7 |
| Fabricated | 40 | 0 | 36 | 4 |

The model called **15% of perfectly correct citations fake** and was unsure about 60% of them.
It flags most fabrications only because it distrusts anything it does not recognise. The grounded
pipeline called none of the 60 correct citations fake. This is the core argument for
retrieval-grounded verification. One `llm_only` item failed with malformed JSON
(`"confidence": 0. nine`) and counts as unsure.

### LLM explanations (30 items, `--explain`)

| Metric | Value |
| --- | --- |
| Verdict accuracy on these 30 items | 30 / 30 |
| Non-verified citations that got an LLM explanation | 19 / 19 |
| LLM explanations passing the grounding validator | **100%** (19 / 19); the validator allows one retry with feedback before falling back to the template |
| LLM tokens per citation, with explanations | 1,972 |
| Latency p50 / p95 | 19 s / 75 s |

Verified citations keep the template explanation by design, so no LLM call is spent on them. The
grounding validator checks that every reason cites a real evidence ID, and that every quoted
title, DOI and year appears in the evidence. It now also rejects a headline that calls a
non-fabricated citation fake (see the fixes below). The latency comes from the Groq free-tier rate
limit (`LLM_TPM=8000` tokens per minute per model), not from the pipeline. Explanations stream in after
the verdicts (pass 2), so users see verdicts first.

### Claim-support check (opt-in, 25 papers from `test2`)

`python -m citeguard.eval.claims --dataset ../eval/datasets/citebench_test2.jsonl --n 25`. For each
real paper with an abstract, `gpt-oss-120b` judges two claims against that abstract:

| Claim | Built from | SUPPORTS | NOT_SUPPORTED | CANNOT_DETERMINE |
| --- | --- | --- | --- | --- |
| Supported (25) | The paper's own concluding sentence, lead-ins such as "We show that" removed | **25** | **0** (no false alarms) | 0 |
| Unsupported (25) | The concluding sentence of a different, random paper | 0 | **23** (92% detected) | 2 |

The two misses are vague sentences ("The ways of stabilization and improvement of the current
situation are proposed"), and both fell to the cautious label. One judgement whose quote was not in
the abstract was dropped by the grounding check. A check costs about 1,600 Groq tokens uncached.

How this result was reached, honestly reported:

- **First run:** 23/25 supported, 21/25 detected, and 1 failed check. Six of the misses came from
  the eval itself: the "concluding sentence" of some abstracts was metadata ("Trial registration
  ACTRN…", "Bibliography: 16 … Keywords: …") or future-work boilerplate. The claim builder now
  skips such sentences.
- **Groq output failures.** In about 1 in 5 calls, `gpt-oss` returned empty or non-JSON output
  under strict schema (`json_validate_failed`), and the client fell back to another model at once.
  It now retries the same model once on that error, and the claim stage's output budget went from
  2,500 to 4,000 tokens. In the second run, three such errors were all recovered.
- The first run took 6 hours of wall time. That was the laptop sleeping (lid closed two minutes
  after the start, per `pmset -g log`), not the pipeline; the re-run took 8.5 minutes.

Limits: synthetic claims measure false alarms and gross topic mismatches. They do not measure
subtle misuse, such as a claim that overgeneralises a real finding or reverses its direction.
That needs a hand-labelled set (next steps).

### Errors found by the evaluation and fixed

Every fix below has a regression test.

**On dev.** The first `no_llm` run scored 0.960 accuracy with a 2.2% false-positive rate on real
citations:

1. **ALL-CAPS titles** (common in Vancouver style): the sentence splitter would not split after a
   capital letter (meant to protect initials such as "J. Smith"), so titles swallowed the journal
   name.
2. **Non-Latin author names** (Chinese, Armenian): the name normalizer kept only a–z, so such
   authors "matched nobody" and real papers were called misattributed. Native-script names are now
   compared directly, and native vs. transliterated names count as *unknown*, not *different*.
3. **CJK name order**: Crossref writes "杨 怡" (family first) while OpenAlex writes "怡飞 杨" (given
   first). Matching now accepts the family name in either position.
4. **Quoted phrase inside a title** (real-0018): in "(2022). Introducing the “How to …” review
   article series", the parser took the quoted fragment as an IEEE-style title, so a real paper
   came out unverifiable. A quote now counts as the title only when it follows the author list or
   the year, not a word.
5. **Lowercase journal names** (fab-0027): in "Developing Countries. animal. 2008;2(6)" the journal
   *animal* did not start a new sentence, so it stuck to the title, the citation lost its venue,
   and a fabricated article came out unverifiable. The segment just before a Vancouver year is now
   always split off as the journal.
6. **Contradictory LLM headline**: for that same item, the LLM wrote "Could not verify: citation
   appears fabricated." The verdict-prefix rule only fixes the start of the headline, so the
   grounding validator now rejects any headline that calls a citation fake unless the verdict is
   FABRICATED or MISATTRIBUTED.

A first version of fix 4 broke IEEE citations whose author list starts with a full first name
("Lorraine E. Maxwell and …"): the Vancouver author pattern matched "Lorraine E." and the real
quoted title was discarded. The `no_llm` re-run on the dev split caught this, and pert-0033 is now
a regression test.

**On `test`** (5 of 90 real citations called fake). Every failure was a Vancouver author list
the parser could not read, with names such as "Van Tinteren H", "Du Plessis E", "Šubic-Kovač M",
"Helland Å" and "Ellis‐Barrett L" (a Unicode hyphen). The rest of the author list became the
"title", nothing matched, and real papers were called fabricated with 0.87–0.9 confidence. The
parse confidence was 0.7, so `full` mode would not have sent them to the LLM parser either.

7. The Vancouver author pattern now accepts any script, capitalised particles (Van, Du, De…) and
   Unicode hyphens.
8. A "title" shaped like an author list gets parse confidence 0.3, so `full` mode sends it to the
   LLM parser.
9. **Parse recovery** in the verifier, the safety net for every parser. Before calling an
   unconfirmed citation fabricated, the verifier checks whether a retrieved record's title and
   first author appear word for word in the raw citation, as a whole segment between
   punctuation. If so, the parse was wrong, so it re-parses around that title and verifies
   again. When the DOI and the searches found nothing, it first runs one Crossref search on the
   raw string. The segment rule keeps hallucinations that extend a real title ("Attention Is All
   You Need for protein structure prediction") from being rescued; there is a test for that.
10. APA volume ranges ("Physica B, 308-310, 431–433") were read as the pages.

**On `test2`** (1 of 90 real citations called fake):

11. "St. Petersburg" was split as a sentence end, which cut the title. "St.", "Mt.", "Dr." and
    "vs." no longer end a sentence.
12. Brazilian initials such as "BVdS" (dos Santos) broke the author pattern and the name splitter.
13. Parse recovery required the whole family name, but Crossref lists "Ibiapina Brito" for an
    author cited as "Brito GMI". Any word of the family name (3+ letters) now counts.

**Found by the Docker smoke test** (outside the benchmark): BibTeX for "Attention Is All You
Need" listing Vaswani and Shazeer, 2 of its 8 authors, came out MISATTRIBUTED at 0.988.

14. Author fabrication was decided on F1, so a correct but incomplete author list (precision
    1.0, recall 0.25) counted as "fabricated authors". It is now decided on precision, the share
    of listed authors who are on the paper. Missing authors are an `AUTHORS_MISSING` note.
15. The chimera check accepted another paper sharing one surname from Crossref's fuzzy author
    search ("A rewarding introduction to global bioethics"). The other work must now carry most
    of the listed authors.

The fix for 14 broke two dev items, which the regression runs caught:

16. Names in native script only ("怡飞 杨"), compared with a romanised citation, are "unknown".
    The old code treated unknown as a mismatch. That flagged correct romanised citations of
    Chinese papers, and caught one author-swapped item (pert-0045) only by accident. Spelling is
    now skipped for such records, but the count still counts: three listed authors for a
    one-author paper is misattribution in any script.
17. When sources disagree, author checks compare against the record most consistent with the
    citation. Crossref listed the publisher ("Korean Academy of Multicultural Welfare") as the
    first author of real-0014.

After fixes 14–17, all three splits score 150/150 in `no_llm` mode (not a held-out estimate).

## Next steps

1. ~~Build a fresh synthetic split and score it once~~: done (`test3`, above).
2. **Chatbot-written split**: prompt Groq-hosted models for literature reviews with references
   on niche topics, then label each reference by hand (two annotators on a subset, report Cohen's κ).
   This is where the LLM parser, adjudicator and query reformulation should matter most.
3. **Hard negatives**: books, theses, non-English and very recent work. The target is that none
   is called `FABRICATED`.
4. Scale the synthetic splits to the design's sizes (~1,000 real, ~500 perturbed), and refit the
   linkage weights with `citeguard.eval.fit_linkage` on a training split, not on dev or test.
5. Human ratings of explanation quality on 100 samples. The automatic grounding check is done
   (above).
6. A hand-labelled claim-support set with subtle misuse (overgeneralised or reversed findings,
   wrong population), to measure what the synthetic claims cannot.
