import { useMutation } from "@tanstack/react-query";
import { ArrowRight, Braces, FileText, FileUp, Quote, Search, ShieldCheck, Sparkles } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { useNavigate } from "react-router-dom";

import { api, type NewCheck } from "../api/client";
import type { CheckOptions, Style } from "../api/types";
import { ErrorNote, Segmented, Spinner, Toggle, cx } from "../components/ui";
import { settings } from "../lib/settings";

type Mode = "text" | "bibtex" | "citation" | "file";

const EXAMPLE_TEXT = `Transformer models replaced recurrent networks for sequence modelling [1]. Deep learning has transformed representation learning [2], and graph transformers now predict protein folding dynamics [3].

References
[1] Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., Kaiser, Ł., & Polosukhin, I. (2017). Attention is all you need. Advances in Neural Information Processing Systems, 30.
[2] LeCun, Y., Bengio, Y., & Hinton, G. (2016). Deep learning. Nature, 520(7553), 436–444.
[3] Smith, J., & Lee, K. (2021). Contrastive graph transformers for protein folding dynamics. Nature Machine Intelligence, 3(4), 211–223. https://doi.org/10.1038/nature14539`;

const EXAMPLE_BIB = `@inproceedings{vaswani2017,
  title = {Attention Is All You Need},
  author = {Vaswani, Ashish and Shazeer, Noam and Parmar, Niki},
  booktitle = {Advances in Neural Information Processing Systems},
  year = {2017}
}
@article{fake2022,
  title = {Neuro-Symbolic Reasoning Networks for Predicting Phase III Clinical Trial Outcomes},
  author = {Chen, Li and Wang, Hao},
  journal = {Journal of Biomedical Informatics},
  year = {2022}
}`;

const EXAMPLE_CITATION =
  "Hinton, G., & LeCun, Y. (2017). Attention is all you need. Advances in Neural Information Processing Systems.";

const ACCEPT = ".pdf,.docx,.bib,.tex,.txt,.md";

export function NewCheckPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("text");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [alternatives, setAlternatives] = useState(true);
  const [useLlm, setUseLlm] = useState(true);
  const [checkClaims, setCheckClaims] = useState(false);
  const [claim, setClaim] = useState("");
  const [style, setStyle] = useState<Style>(settings.getStyle());
  const fileInput = useRef<HTMLInputElement>(null);

  const submit = useMutation({
    mutationFn: async () => {
      const options: CheckOptions = {
        use_llm: useLlm,
        explain: useLlm,
        suggest_alternatives: alternatives,
        styles: ["apa", "ieee", "bibtex"],
        sources: null,
        check_claims: useLlm && checkClaims,
        claim: mode === "citation" && claim.trim() ? claim.trim() : null,
      };
      if (mode === "file") {
        if (!file) throw new Error("Choose a file first.");
        return api.uploadCheck(file, options);
      }
      const input: NewCheck =
        mode === "bibtex"
          ? { kind: "bibtex", bibtex: text }
          : mode === "citation"
            ? { kind: "citation", citation: text }
            : { kind: "text", text };
      return api.createCheck(input, options);
    },
    onSuccess: (created) => navigate(`/checks/${created.id}`),
  });

  const canSubmit = mode === "file" ? !!file : text.trim().length > 10;

  function loadExample() {
    setText(mode === "bibtex" ? EXAMPLE_BIB : mode === "citation" ? EXAMPLE_CITATION : EXAMPLE_TEXT);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) setFile(f);
  }

  return (
    <div className="mx-auto max-w-3xl">
      <section className="mb-8 text-center">
        <h1 className="font-serif text-3xl font-semibold tracking-tight text-balance sm:text-4xl">
          Catch fabricated citations before your reviewers do
        </h1>
        <p className="mx-auto mt-3 max-w-2xl text-ink-600 text-pretty dark:text-ink-300">
          Paste a reference list, a BibTeX file or a chatbot’s answer, or upload a paper. Each citation is
          checked against scholarly databases, and each verdict comes with the evidence behind it.
        </p>
      </section>

      <form
        className="card space-y-5 p-5 sm:p-6"
        onSubmit={(e) => {
          e.preventDefault();
          if (canSubmit) submit.mutate();
        }}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Segmented<Mode>
            ariaLabel="Input type"
            value={mode}
            onChange={setMode}
            options={[
              { value: "text", label: <><FileText className="size-4" />Text</> },
              { value: "bibtex", label: <><Braces className="size-4" />BibTeX</> },
              { value: "citation", label: <><Quote className="size-4" />One citation</> },
              { value: "file", label: <><FileUp className="size-4" />Upload</> },
            ]}
          />
          {mode !== "file" && (
            <button type="button" className="btn-ghost text-xs" onClick={loadExample}>
              Load example
            </button>
          )}
        </div>

        {mode === "file" ? (
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            onClick={() => fileInput.current?.click()}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && fileInput.current?.click()}
            role="button"
            tabIndex={0}
            className={cx(
              "flex min-h-48 cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 text-center transition",
              dragging
                ? "border-brand-500 bg-brand-500/5"
                : "border-ink-200 hover:border-ink-300 dark:border-ink-700 dark:hover:border-ink-600",
            )}
          >
            <FileUp className="size-7 text-ink-400" />
            {file ? (
              <p className="text-sm font-medium">
                {file.name} <span className="text-ink-500">({(file.size / 1024).toFixed(0)} KB)</span>
              </p>
            ) : (
              <>
                <p className="text-sm font-medium">Drop a file here or click to browse</p>
                <p className="text-xs text-ink-500">PDF, DOCX, BibTeX, LaTeX, Markdown or text · up to 25 MB</p>
              </>
            )}
            <input
              ref={fileInput}
              type="file"
              accept={ACCEPT}
              className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
        ) : (
          <textarea
            className="input min-h-56 resize-y font-mono text-[13px] leading-relaxed"
            value={text}
            onChange={(e) => setText(e.target.value)}
            spellCheck={false}
            placeholder={
              mode === "bibtex"
                ? "@article{key, title = {...}, author = {...}, ...}"
                : mode === "citation"
                  ? "Smith, J. (2021). Title of the paper. Journal, 3(4), 211–223."
                  : "Paste text with a reference list (numbered, APA, IEEE, Vancouver…), or a chatbot answer."
            }
            aria-label="Input"
          />
        )}

        {mode === "citation" && (
          <label className="block space-y-1.5">
            <span className="text-sm font-medium">What is it cited for? <span className="font-normal text-ink-500">(optional)</span></span>
            <textarea
              className="input min-h-16 resize-y text-sm"
              value={claim}
              onChange={(e) => setClaim(e.target.value)}
              maxLength={2000}
              placeholder="The sentence from your text, e.g. “Transformers replaced recurrent networks for machine translation [1].”"
            />
            <span className="block text-xs text-ink-500">
              {useLlm
                ? "We check whether the paper’s abstract supports this sentence."
                : "Turn on LLM explanations to check the claim."}
            </span>
          </label>
        )}

        <div className="grid gap-4 sm:grid-cols-3 sm:items-start">
          <Toggle
            checked={alternatives}
            onChange={setAlternatives}
            label="Suggest real alternatives"
            hint="For fabricated citations"
          />
          <Toggle
            checked={useLlm}
            onChange={(v) => {
              setUseLlm(v);
              if (!v) setCheckClaims(false);
            }}
            label="LLM explanations"
            hint="Grounded in retrieved evidence"
          />
          <Toggle
            checked={checkClaims}
            onChange={(v) => {
              setCheckClaims(v);
              if (v) setUseLlm(true);
            }}
            label="Check claims (beta)"
            hint="Does each paper’s abstract support the sentence citing it?"
          />
        </div>
        <div className="flex justify-end">
          <label className="flex items-center gap-2 text-sm">
            <span className="text-ink-600 dark:text-ink-300">Style</span>
            <select
              className="input w-auto py-1.5"
              value={style}
              onChange={(e) => {
                const s = e.target.value as Style;
                setStyle(s);
                settings.setStyle(s);
              }}
            >
              <option value="apa">APA</option>
              <option value="ieee">IEEE</option>
              <option value="bibtex">BibTeX</option>
            </select>
          </label>
        </div>

        {submit.error && <ErrorNote>{(submit.error as Error).message}</ErrorNote>}

        <button type="submit" className="btn-primary w-full py-2.5" disabled={!canSubmit || submit.isPending}>
          {submit.isPending ? <Spinner /> : <ShieldCheck className="size-4" />}
          Check citations
          {!submit.isPending && <ArrowRight className="size-4" />}
        </button>
      </form>

      <section className="mt-10 grid gap-4 sm:grid-cols-3">
        {[
          { icon: Search, title: "Verify", text: "DOIs, arXiv IDs and titles are looked up in Crossref, OpenAlex, Semantic Scholar, arXiv and PubMed." },
          { icon: ShieldCheck, title: "Explain", text: "Every verdict lists its evidence: which database said what, and which fields disagree." },
          { icon: Sparkles, title: "Fix", text: "Real papers get a corrected citation; fabricated ones get real alternatives on the same topic." },
        ].map(({ icon: Icon, title, text: body }) => (
          <div key={title} className="rounded-xl p-4">
            <Icon className="mb-2 size-5 text-brand-600 dark:text-brand-500" />
            <h3 className="text-sm font-semibold">{title}</h3>
            <p className="mt-1 text-sm text-ink-600 dark:text-ink-400">{body}</p>
          </div>
        ))}
      </section>
    </div>
  );
}
