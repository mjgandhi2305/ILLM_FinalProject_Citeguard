// Builds slides/CiteGuard_ILLM_Final.pptx from the evaluation outputs.
//
//   cd slides && npm install && node build_deck.js
//
// Numbers on the result slides are read from eval/runs/*/summary.json and
// paper/generated/llm_only_breakdown.json, the same files the paper's tables come from.

const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");

const ROOT = path.resolve(__dirname, "..");
const RUNS = path.join(ROOT, "eval", "runs");
const ASSETS = path.join(__dirname, "assets");
const OUT = path.join(__dirname, "CiteGuard_ILLM_Final.pptx");
const REPO = "https://github.com/mjgandhi2305/ILLM_FinalProject_Citeguard";

const THEME = {
  name: "CiteGuard Academic",
  headFontFace: "Calibri",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1A1A1A", lt1: "FFFFFF", dk2: "1F4E79", lt2: "EEF3F8",
    accent1: "1F4E79", accent2: "2E75B6", accent3: "C0392B",
    accent4: "2E7D32", accent5: "B7791F", accent6: "7F8C8D",
    hlink: "2E75B6", folHlink: "1F4E79",
  },
};
const HEX = THEME.colors;
const NAVY = HEX.accent1, BLUE = HEX.accent2, RED = HEX.accent3, GREEN = HEX.accent4;
const AMBER = HEX.accent5, GREY = HEX.accent6, TINT = HEX.lt2, INK = HEX.dk1;
const MUTED = "5F6B76";

// ------------------------------------------------------------------------------------------
// Data
// ------------------------------------------------------------------------------------------
function summary(name) {
  const p = path.join(RUNS, name, "summary.json");
  return fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, "utf8")) : null;
}
function correctFpr(s) {
  const row = s.confusion.VERIFIED;
  const n = Object.values(row).reduce((a, b) => a + b, 0);
  return n ? (row.FABRICATED + row.MISATTRIBUTED) / n : 0;
}
const SYSTEMS = [
  ["Offline heuristics", "citebench_test3-heuristics"],
  ["DOI lookup only", "citebench_test3-doi_only"],
  ["LLM-only gpt-oss-20b", "citebench_test3-llm_only-gpt-oss-20b"],
  ["LLM-only qwen3.8-27b", "citebench_test3-llm_only-qwen3.8-27b"],
  ["LLM-only gpt-oss-120b", "citebench_test3-llm_only-gpt-oss-120b"],
  ["CiteGuard exact match", "citebench_test3-exact"],
  ["CiteGuard (no LLM)", "citebench_test3-no_llm"],
  ["CiteGuard full (LLM)", "citebench_test3-full"],
].map(([label, run]) => ({ label, s: summary(run) })).filter((x) => x.s);

const breakdown = JSON.parse(
  fs.readFileSync(path.join(ROOT, "paper", "generated", "llm_only_breakdown.json"), "utf8"),
);
const noLlm = summary("citebench_test3-no_llm");
const full = summary("citebench_test3-full");
const big = summary("citebench_test3-llm_only-gpt-oss-120b");
const pct = (x) => `${Math.round(100 * x)}%`;

// ------------------------------------------------------------------------------------------
// Deck, theme and layouts
// ------------------------------------------------------------------------------------------
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in
pres.author = "Miten Gandhi";
pres.title = "CiteGuard: LLM-Based Fake Citation Detection and Verification";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;
const W = 13.333, MX = 0.6;

pres.defineSlideMaster({
  title: "TITLE_DARK",
  background: { color: NAVY },
  objects: [],
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: "FFFFFF" },
  margin: [0.5, 0.6, 0.5, 0.6],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: MX, y: 0.35, w: W - 2 * MX, h: 0.95,
        fontSize: 27, bold: true, color: NAVY, align: "left", valign: "middle", margin: 0 },
      text: "" } },
    { text: { text: "CiteGuard  ·  ILLM Final Project", options: { x: MX, y: 7.05, w: 6, h: 0.3,
        fontSize: 10, color: MUTED, margin: 0 } } },
  ],
  slideNumber: { x: W - MX - 0.6, y: 7.05, w: 0.6, h: 0.3, fontSize: 10, color: MUTED, align: "right" },
});

let section = null;
function slide(title, sectionTitle) {
  if (sectionTitle !== section) {
    pres.addSection({ title: sectionTitle });
    section = sectionTitle;
  }
  const s = pres.addSlide({ masterName: "CONTENT", sectionTitle });
  s.addText(title, { placeholder: "title" });
  return s;
}
function source(s, text) {
  s.addText(text, { x: MX, y: 6.62, w: W - 2 * MX, h: 0.35, fontSize: 11, color: MUTED,
    italic: true, margin: 0, isTextBox: true, objectName: "Source" });
}
function bullets(s, items, opts) {
  s.addText(
    items.map((t, i) => {
      const runs = typeof t === "string" ? [{ text: t }] : t;
      return runs.map((r, j) => ({
        text: r.text,
        options: {
          bold: r.bold, color: r.color || INK,
          bullet: j === 0 ? { indent: 18 } : undefined,
          breakLine: j === runs.length - 1 && i < items.length - 1,
          paraSpaceAfter: 10,
        },
      }));
    }).flat(),
    { fontSize: 19, valign: "top", margin: 0, isTextBox: true, ...opts },
  );
}
function card(s, x, y, w, h, fill = TINT) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08,
    fill: { color: fill }, line: { color: fill, width: 0 } });
}
function stat(s, x, y, w, big, label, color = NAVY) {
  s.addText(big, { x, y, w, h: 0.95, fontSize: 46, bold: true, color, margin: 0, isTextBox: true });
  s.addText(label, { x, y: y + 0.95, w, h: 1.0, fontSize: 16, color: INK, margin: 0, valign: "top",
    isTextBox: true });
}

// ------------------------------------------------------------------------------------------
// 1. Title
// ------------------------------------------------------------------------------------------
{
  pres.addSection({ title: "Introduction" });
  section = "Introduction";
  const s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Introduction" });
  s.addText("CiteGuard", { x: MX, y: 1.3, w: 12, h: 0.7, fontSize: 24, bold: true, color: "9DC3E6",
    margin: 0, isTextBox: true });
  s.addText("Catching fabricated citations with evidence, not with LLM judgement", {
    x: MX, y: 2.0, w: 11.6, h: 1.7, fontSize: 40, bold: true, color: "FFFFFF", margin: 0,
    valign: "top", isTextBox: true });
  s.addText("LLM-Based Fake Citation Detection and Verification System", {
    x: MX, y: 3.75, w: 11.6, h: 0.5, fontSize: 22, color: "DCE6F0", margin: 0, isTextBox: true });
  s.addText([
    { text: "Miten Gandhi", options: { bold: true, breakLine: true } },
    { text: "Introduction to Large Language Models (ILLM) · Final Project · November 2026" },
  ], { x: MX, y: 5.4, w: 11.6, h: 0.9, fontSize: 18, color: "FFFFFF", margin: 0, isTextBox: true });
}

// ------------------------------------------------------------------------------------------
// 2. Problem statement
// ------------------------------------------------------------------------------------------
{
  const s = slide("Problem: for every citation, decide if it is real and correct, and explain why",
    "Introduction");
  // Left: an annotated fabricated citation
  card(s, MX, 1.55, 6.4, 4.75);
  s.addText("A citation an LLM might write", { x: MX + 0.3, y: 1.7, w: 5.8, h: 0.4, fontSize: 16,
    bold: true, color: MUTED, margin: 0, isTextBox: true });
  s.addText([
    { text: "Zhang, L., & Kumar, R. (2021). ", options: { color: INK } },
    { text: "Contrastive graph transformers for protein folding dynamics.", options: { color: RED, bold: true } },
    { text: " Nature Machine Intelligence", options: { color: INK, italic: true } },
    { text: ", 3(4), 211–223. ", options: { color: INK } },
    { text: "doi:10.1038/s42256-021-00…", options: { color: AMBER, bold: true } },
  ], { x: MX + 0.3, y: 2.2, w: 5.8, h: 1.6, fontSize: 18, margin: 0, valign: "top", isTextBox: true });
  const notes = [
    [RED, "Title: plausible, but no such paper exists"],
    [INK, "Venue and formatting: real and correct"],
    [AMBER, "DOI: real, but belongs to another paper"],
  ];
  notes.forEach(([c, t], i) => {
    s.addShape(pres.shapes.OVAL, { x: MX + 0.35, y: 4.12 + i * 0.6, w: 0.22, h: 0.22,
      fill: { color: c }, line: { color: c, width: 0 } });
    s.addText(t, { x: MX + 0.75, y: 4.0 + i * 0.6, w: 5.4, h: 0.45, fontSize: 17, color: INK,
      margin: 0, valign: "middle", isTextBox: true });
  });
  // Right: the output
  s.addText("Output per citation", { x: 7.45, y: 1.55, w: 5.3, h: 0.4, fontSize: 18, bold: true,
    color: NAVY, margin: 0, isTextBox: true });
  const verdicts = [
    [GREEN, "Verified", "real record, fields agree"],
    [AMBER, "Verified with errors", "real paper, wrong year / venue / DOI"],
    ["E67E22", "Misattributed", "real title, wrong authors or DOI"],
    [RED, "Fabricated", "no such work in any index"],
    [GREY, "Unverifiable", "too little evidence: not “fake”"],
  ];
  verdicts.forEach(([c, v, d], i) => {
    const y = 2.05 + i * 0.62;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 7.45, y, w: 2.45, h: 0.48, rectRadius: 0.06,
      fill: { color: c }, line: { color: c, width: 0 } });
    s.addText(v, { x: 7.45, y, w: 2.45, h: 0.48, fontSize: 15, bold: true, color: "FFFFFF",
      align: "center", valign: "middle", margin: 0, isTextBox: true });
    s.addText(d, { x: 10.05, y, w: 2.75, h: 0.48, fontSize: 15, color: INK, valign: "middle",
      margin: 0, isTextBox: true });
  });
  s.addText("+ evidence, an explanation, and a fix (corrected citation or real alternatives)", {
    x: 7.45, y: 5.25, w: 5.3, h: 0.8, fontSize: 17, color: NAVY, bold: true, margin: 0,
    valign: "top", isTextBox: true });
  source(s, "Example citation is invented for illustration.");
}

// ------------------------------------------------------------------------------------------
// 3. Motivation
// ------------------------------------------------------------------------------------------
{
  const s = slide("Motivation: LLMs invent references, and asking an LLM to check them is unreliable",
    "Introduction");
  const cols = [
    ["55% / 18%", "of references written by GPT-3.5 / GPT-4 were fabricated", RED],
    ["146,932", "estimated non-existent citations in 2025 papers alone", RED],
    ["4 – 70%", "false-positive rate of zero-shot LLM citation verifiers", AMBER],
  ];
  cols.forEach(([b, l, c], i) => {
    const x = MX + i * 4.1;
    card(s, x, 1.65, 3.85, 2.75);
    stat(s, x + 0.3, 1.9, 3.3, b, l, c);
  });
  bullets(s, [
    "Reviewers cannot check every reference by hand",
    "An LLM judging from memory confuses “I don’t know this paper” with “this paper does not exist”",
  ], { x: MX, y: 4.75, w: W - 2 * MX, h: 1.6 });
  source(s, "Walters & Wilder (2023), Sci. Rep.; Zhao et al. (2026), arXiv:2605.07723; Kim et al. (2026), HALLMARK, arXiv:2607.18360.");
}

// ------------------------------------------------------------------------------------------
// 4. Dataset
// ------------------------------------------------------------------------------------------
{
  const s = slide("Dataset: CiteBench has 4 splits of 150 labelled citations, each scored once", "Data and method");
  const rows = [
    ["Group", "n", "How it is built", "Gold label"],
    ["Real", "60", "random articles from OpenAlex + Crossref; APA / IEEE / Vancouver / BibTeX", "Verified"],
    ["Real, cited with errors", "30", "year shifted, venue swapped, or non-existent DOI", "Verified w/ errors"],
    ["Misattributed", "20", "authors swapped, or another paper’s DOI", "Misattributed"],
    ["Fabricated", "40", "invented plausible title (30), or invented title + real DOI (10)", "Fabricated"],
  ];
  s.addTable(rows.map((r, i) => r.map((t, j) => ({
    text: t,
    options: {
      bold: i === 0 || j === 0, color: i === 0 ? "FFFFFF" : INK,
      fill: { color: i === 0 ? NAVY : i % 2 ? "FFFFFF" : TINT },
      align: j === 1 ? "center" : "left", valign: "middle",
    },
  }))), { x: MX, y: 1.55, w: 8.1, colW: [1.95, 0.55, 3.85, 1.75], fontSize: 14,
    rowH: [0.45, 0.75, 0.7, 0.6, 0.75], border: { type: "solid", pt: 0.5, color: "D5DCE3" },
    margin: 0.07 });
  // Right: protocol
  s.addText("Held-out protocol", { x: 9.15, y: 1.55, w: 3.6, h: 0.4, fontSize: 18, bold: true,
    color: NAVY, margin: 0, isTextBox: true });
  const steps = [["dev", "develop + fix"], ["test", "score once, then fix"], ["test2", "score once, then fix"],
    ["test3", "new for this report"]];
  steps.forEach(([k, d], i) => {
    const y = 2.1 + i * 0.85;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 9.15, y, w: 1.15, h: 0.55, rectRadius: 0.06,
      fill: { color: i === 3 ? RED : BLUE }, line: { color: i === 3 ? RED : BLUE, width: 0 } });
    s.addText(k, { x: 9.15, y, w: 1.15, h: 0.55, fontSize: 15, bold: true, color: "FFFFFF",
      align: "center", valign: "middle", margin: 0, isTextBox: true });
    s.addText(d, { x: 10.45, y, w: 2.35, h: 0.55, fontSize: 15, color: INK, valign: "middle",
      margin: 0, isTextBox: true });
  });
  s.addText("No DOI shared between splits; + 25 papers × 2 claims for the claim check", {
    x: 9.15, y: 5.55, w: 3.6, h: 0.8, fontSize: 14, color: MUTED, margin: 0, valign: "top",
    isTextBox: true });
}

// ------------------------------------------------------------------------------------------
// 5. Approaches (1): what each family can see
// ------------------------------------------------------------------------------------------
{
  const s = slide("Approaches: four ways to judge a citation; only retrieval separates “unknown” from “fake”",
    "Data and method");
  const cols = [
    ["Offline heuristics", "Bad DOI syntax, future year, odd pages", "Plausible fakes have no surface defect", GREY],
    ["DOI lookup", "Does the DOI resolve? (HALLMARK baseline)", "Blind to fakes without a DOI, or with a borrowed one", GREY],
    ["LLM-only judge", "Ask gpt-oss-20b / qwen3.8-27b / gpt-oss-120b: “does this exist?”", "Rejects real papers it does not recognise", AMBER],
    ["CiteGuard (ours)", "Retrieve from 6 indexes, link records, apply rules; LLM only for checkable tasks", "Needs network access and index coverage", NAVY],
  ];
  cols.forEach(([h, how, weak, c], i) => {
    const x = MX + i * 3.08, w = 2.9;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.6, w, h: 0.7, rectRadius: 0.06,
      fill: { color: c }, line: { color: c, width: 0 } });
    s.addText(h, { x, y: 1.6, w, h: 0.7, fontSize: 18, bold: true, color: "FFFFFF", align: "center",
      valign: "middle", margin: 0, isTextBox: true });
    card(s, x, 2.45, w, 3.0, i === 3 ? "E3EDF7" : TINT);
    s.addText([
      { text: "Uses", options: { bold: true, color: MUTED, fontSize: 14, breakLine: true } },
      { text: how, options: { color: INK, fontSize: 17, breakLine: true } },
      { text: " ", options: { fontSize: 10, breakLine: true } },
      { text: "Fails when", options: { bold: true, color: MUTED, fontSize: 14, breakLine: true } },
      { text: weak, options: { color: i === 3 ? NAVY : RED, fontSize: 17 } },
    ], { x: x + 0.2, y: 2.6, w: w - 0.4, h: 2.75, valign: "top", margin: 0, isTextBox: true });
  });
  s.addText("Only CiteGuard returns a verdict a user can act on: which field is wrong, the evidence, and a fix.", {
    x: MX, y: 5.75, w: W - 2 * MX, h: 0.6, fontSize: 18, bold: true, color: NAVY, margin: 0,
    isTextBox: true });
}

// ------------------------------------------------------------------------------------------
// 6. Approaches (2): the LLM's checked roles
// ------------------------------------------------------------------------------------------
{
  const s = slide("CiteGuard confines the LLM to five tasks whose output is checked against evidence",
    "Data and method");
  const rows = [
    ["LLM task (Groq)", "Model", "The check that keeps it honest"],
    ["Parse messy references", "gpt-oss-20b", "Parsed title must appear in the raw string"],
    ["Adjudicate close matches", "gpt-oss-120b", "May only pick a retrieved candidate ID, or none"],
    ["Rewrite failed searches", "gpt-oss-20b", "Code runs the queries; linkage model scores results"],
    ["Explain the verdict", "gpt-oss-120b", "Every reason cites an evidence ID; every quoted value must be in the evidence"],
    ["Check claim support (opt-in)", "gpt-oss-120b", "Quote must appear verbatim in the cited abstract"],
  ];
  s.addTable(rows.map((r, i) => r.map((t, j) => ({
    text: t,
    options: {
      bold: i === 0 || j === 0, color: i === 0 ? "FFFFFF" : j === 1 ? MUTED : INK,
      fill: { color: i === 0 ? "4C1D95" : i % 2 ? "FFFFFF" : "F3F0FA" },
      fontFace: j === 1 && i > 0 ? "Courier New" : undefined, valign: "middle",
    },
  }))), { x: MX, y: 1.6, w: W - 2 * MX, colW: [3.6, 2.2, 6.33], fontSize: 17,
    rowH: [0.5, 0.62, 0.62, 0.62, 0.8, 0.62], border: { type: "solid", pt: 0.5, color: "DDD6EE" },
    margin: 0.08 });
  s.addText("The LLM never decides that a paper exists: if any output fails its check, the deterministic result stands.", {
    x: MX, y: 5.8, w: W - 2 * MX, h: 0.6, fontSize: 18, bold: true, color: NAVY, margin: 0,
    isTextBox: true });
}

// ------------------------------------------------------------------------------------------
// 7. Pipeline
// ------------------------------------------------------------------------------------------
{
  const s = slide("Pipeline: retrieval and record linkage decide; the LLM assists in checked steps",
    "Data and method");
  const bw = 1.55, bh = 0.95, gap = 0.2, y1 = 1.75, y2 = 3.35, y3 = 4.95;
  const xs = (i) => MX + i * (bw + gap);
  function box(i, y, title, sub, llm = false, dark = false) {
    const fill = dark ? NAVY : llm ? "EDE9FE" : "E0F2FE";
    const line = llm ? "7C3AED" : "0284C7";
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: xs(i), y, w: bw, h: bh, rectRadius: 0.06,
      fill: { color: fill }, line: { color: line, width: 1 } });
    s.addText([
      { text: title, options: { bold: true, fontSize: 13, color: dark ? "FFFFFF" : INK, breakLine: true } },
      { text: sub, options: { fontSize: 11, color: dark ? "DCE6F0" : "37474F" } },
    ], { x: xs(i) + 0.03, y, w: bw - 0.06, h: bh, align: "center", valign: "middle", margin: 0,
      isTextBox: true });
  }
  function arrow(x1, y1a, x2, y2a, dash) {
    s.addShape(pres.shapes.LINE, { x: Math.min(x1, x2), y: Math.min(y1a, y2a),
      w: Math.abs(x2 - x1) || 0.001, h: Math.abs(y2a - y1a) || 0.001,
      flipH: x2 < x1, flipV: y2a < y1a,
      line: { color: "546E7A", width: 1.25, endArrowType: "triangle", dashType: dash ? "dash" : "solid" } });
  }
  const top = [["Input", "PDF · DOCX · LaTeX · BibTeX · text"], ["1 Ingest", "references + citing sentences"],
    ["2 Parse", "regex IDs, GROBID / rules"], ["3 Screen", "offline risk signals"],
    ["4 Retrieve", "doi.org · Crossref · OpenAlex · S2 · arXiv · PubMed"], ["5 Link", "P(same work), accept ≥ 0.9"],
    ["6 Decide", "rules + parse recovery"]];
  top.forEach(([t, d], i) => box(i, y1, t, d));
  for (let i = 0; i < 6; i++) arrow(xs(i) + bw, y1 + bh / 2, xs(i + 1), y1 + bh / 2);
  box(2, y2, "LLM parse", "low-confidence refs", true);
  box(4, y2, "LLM query rewrite", "code runs queries", true);
  box(5, y2, "LLM adjudicator", "0.5 ≤ p < 0.9: pick ID or none", true);
  box(6, y2, "Verdict", "streamed with evidence", false, true);
  arrow(xs(2) + bw / 2, y1 + bh, xs(2) + bw / 2, y2, true);
  arrow(xs(5) + 0.3, y1 + bh, xs(4) + bw - 0.3, y2);      // no match -> rewrite
  arrow(xs(4) + 0.4, y2, xs(4) + 0.4, y1 + bh);           // new candidates -> retrieve
  arrow(xs(5) + bw / 2 + 0.2, y1 + bh, xs(5) + bw / 2 + 0.2, y2);
  arrow(xs(5) + bw, y2 + 0.2, xs(6), y1 + bh - 0.1);      // adjudicator -> decide
  arrow(xs(6) + bw / 2, y1 + bh, xs(6) + bw / 2, y2);
  box(6, y3, "Claim check", "opt-in, verbatim quote", true);
  box(5, y3, "7 Explain", "cites evidence → validator", true);
  box(4, y3, "8 Suggest", "correction or alternatives", true);
  box(3, y3, "9 Report", "JSON · HTML · CSV · .bib");
  arrow(xs(6) + bw / 2, y2 + bh, xs(6) + bw / 2, y3);
  arrow(xs(6) + 0.15, y2 + bh, xs(5) + bw - 0.2, y3);
  arrow(xs(5), y3 + bh / 2, xs(4) + bw, y3 + bh / 2);
  arrow(xs(4), y3 + bh / 2, xs(3) + bw, y3 + bh / 2);
  // legend + pass-2 label
  s.addShape(pres.shapes.RECTANGLE, { x: MX, y: 3.55, w: 0.3, h: 0.22, fill: { color: "E0F2FE" },
    line: { color: "0284C7", width: 1 } });
  s.addText("deterministic: decides existence", { x: MX + 0.4, y: 3.48, w: 2.9, h: 0.36, fontSize: 13,
    color: INK, margin: 0, isTextBox: true });
  s.addShape(pres.shapes.RECTANGLE, { x: MX, y: 3.95, w: 0.3, h: 0.22, fill: { color: "EDE9FE" },
    line: { color: "7C3AED", width: 1 } });
  s.addText("LLM: output checked before use", { x: MX + 0.4, y: 3.88, w: 2.9, h: 0.36, fontSize: 13,
    color: INK, margin: 0, isTextBox: true });
  s.addText("Pass 2, after verdicts stream →", { x: MX, y: y3 + 0.25, w: 4.4, h: 0.45, fontSize: 14,
    italic: true, color: MUTED, margin: 0, align: "right", isTextBox: true });
}

// ------------------------------------------------------------------------------------------
// 8. Results (1): main table as chart
// ------------------------------------------------------------------------------------------
{
  const s = slide(`Results: on a fresh held-out split, CiteGuard finds every fake and flags no correct citation`,
    "Results");
  const labels = SYSTEMS.map((x) => x.label);
  s.addChart(pres.charts.BAR, [
    { name: "Fake-detection F1 (%)", labels, values: SYSTEMS.map((x) => Math.round(1000 * x.s.fake_detection.f1) / 10) },
    { name: "Correct citations called fake (%)", labels, values: SYSTEMS.map((x) => Math.round(1000 * correctFpr(x.s)) / 10) },
  ], {
    x: MX, y: 1.45, w: 8.0, h: 5.1, barDir: "bar", barGrouping: "clustered", barGapWidthPct: 45,
    chartColors: [NAVY, RED], showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 11,
    dataLabelFontFace: "+mn-lt", dataLabelColor: INK,
    catAxisLabelFontSize: 13, catAxisLabelFontFace: "+mn-lt", catAxisLabelColor: INK, catAxisOrientation: "maxMin",
    valAxisHidden: true, valAxisMaxVal: 110, valAxisMinVal: 0, valGridLine: { style: "none" },
    catGridLine: { style: "none" }, showLegend: true, legendPos: "b", legendFontSize: 13, legendFontFace: "+mn-lt",
  });
  bullets(s, [
    [{ text: `CiteGuard: F1 ${noLlm.fake_detection.f1.toFixed(2)}, 0 correct citations called fake`, bold: true, color: NAVY }],
    `Best LLM-only (gpt-oss-120b): F1 ${big.fake_detection.f1.toFixed(2)}, ${pct(correctFpr(big))} of correct citations called fake`,
    `Qwen3.8-27B is worse still: ${pct(correctFpr(summary("citebench_test3-llm_only-qwen3.8-27b")))} of correct citations called fake`,
    "DOI lookup misses every fabrication: fakes lack a DOI or borrow a real one",
    "The LLM changes no verdict here; its value is explanations and claim checks",
  ], { x: 8.9, y: 1.6, w: 3.85, h: 4.9, fontSize: 17 });
  source(s, "CiteBench test3: 150 citations (60 correct, 30 real with errors, 20 misattributed, 40 fabricated), scored once.");
}

// ------------------------------------------------------------------------------------------
// 9. Results (2): LLM-only answers + grounding
// ------------------------------------------------------------------------------------------
{
  const s = slide("Results: LLM-only judges doubt real papers; CiteGuard’s LLM outputs stay grounded", "Results");
  const models = Object.keys(breakdown);
  const lab = models.map((m) => m).concat(["CiteGuard (no LLM)"]);
  const g = (m, k) => {
    const [n, ex, fk, un] = breakdown[m]["Correct"];
    return Math.round((1000 * [ex, fk, un][k]) / n) / 10;
  };
  const cgRow = noLlm.confusion.VERIFIED;
  const cgN = Object.values(cgRow).reduce((a, b) => a + b, 0);
  const cg = [
    Math.round((1000 * (cgRow.VERIFIED + cgRow.VERIFIED_WITH_ERRORS)) / cgN) / 10,
    Math.round((1000 * (cgRow.FABRICATED + cgRow.MISATTRIBUTED)) / cgN) / 10,
    Math.round((1000 * cgRow.UNVERIFIABLE) / cgN) / 10,
  ];
  s.addChart(pres.charts.BAR, ["Says it exists", "Says fake", "Unsure"].map((name, k) => ({
    name, labels: lab, values: models.map((m) => g(m, k)).concat([cg[k]]),
  })), {
    x: MX, y: 1.45, w: 7.4, h: 5.0, barDir: "bar", barGrouping: "percentStacked", barGapWidthPct: 50,
    chartColors: [GREEN, RED, "B0BEC5"], showValue: true, dataLabelPosition: "ctr", dataLabelFontSize: 12,
    dataLabelFontFace: "+mn-lt", dataLabelColor: "FFFFFF", dataLabelFormatCode: "0",
    catAxisLabelFontSize: 14, catAxisLabelFontFace: "+mn-lt", catAxisLabelColor: INK, catAxisOrientation: "maxMin",
    valAxisHidden: true, valGridLine: { style: "none" }, catGridLine: { style: "none" },
    showLegend: true, legendPos: "b", legendFontSize: 13, legendFontFace: "+mn-lt",
    showTitle: true, title: "Answers on the 60 correct citations of test3 (%)", titleFontSize: 15,
    titleFontFace: "+mn-lt", titleColor: INK,
  });
  const stats = [
    ["19 / 19", "LLM explanations passed the evidence validator"],
    ["0 / 25", "false alarms when claims were supported"],
    ["23 / 25", "mismatched claims flagged as not supported"],
  ];
  stats.forEach(([b, l], i) => {
    const y = 1.55 + i * 1.65;
    card(s, 8.4, y, 4.35, 1.45);
    s.addText(b, { x: 8.6, y: y + 0.1, w: 1.9, h: 1.25, fontSize: 32, bold: true, color: NAVY,
      valign: "middle", margin: 0, isTextBox: true });
    s.addText(l, { x: 10.5, y: y + 0.1, w: 2.1, h: 1.25, fontSize: 15, color: INK, valign: "middle",
      margin: 0, isTextBox: true });
  });
  source(s, "Explanations: 30 dev citations. Claim check: 25 test2 papers × (own conclusion, another paper’s conclusion).");
}

// ------------------------------------------------------------------------------------------
// 10. Challenges
// ------------------------------------------------------------------------------------------
{
  const s = slide("Challenges: most failures came from messy formats and fragile external services", "Discussion");
  const cells = [
    ["Messy reference formats", "Vancouver names (“Van Tinteren H”, “Helland Å”), “St. Petersburg”, ALL-CAPS titles turned real papers into “fakes”",
      "Unicode-aware parser + parse recovery safety net"],
    ["External APIs", "Crossref / OpenAlex / S2 time-outs and rate limits; Groq free tier: 8K tokens/min",
      "20 s hard deadline per call, circuit breakers, caching, per-model token limiter"],
    ["Unreliable LLM output", "≈1 in 5 strict-JSON calls failed (json_validate_failed); one headline called a real paper “fabricated”",
      "Same-model retry, schema validation, evidence validator, template fallback"],
    ["Honest evaluation", "Synthetic data saturates; fixing on test data inflates scores",
      "Held-out protocol: each split scored once; fresh test3 for this report"],
  ];
  cells.forEach(([h, prob, fix], i) => {
    const x = MX + (i % 2) * 6.15, y = 1.55 + Math.floor(i / 2) * 2.55, w = 5.95, h2 = 2.35;
    card(s, x, y, w, h2);
    s.addText([
      { text: h, options: { bold: true, fontSize: 18, color: NAVY, breakLine: true } },
      { text: prob, options: { fontSize: 15, color: INK, breakLine: true } },
      { text: "→ " + fix, options: { fontSize: 15, color: GREEN, bold: true } },
    ], { x: x + 0.25, y: y + 0.15, w: w - 0.5, h: h2 - 0.3, valign: "top", margin: 0,
      paraSpaceAfter: 6, isTextBox: true });
  });
}

// ------------------------------------------------------------------------------------------
// 11. Learnings
// ------------------------------------------------------------------------------------------
{
  const s = slide("Learnings: let evidence decide, measure false alarms, and hold data out", "Discussion");
  const items = [
    ["Evidence before generation", "An LLM is a poor oracle for facts it may not know, but a good assistant when its output can be checked"],
    ["False positives are the metric", "Flagging a real paper as fake costs a user more than missing a rare fake"],
    ["“Not found” ≠ “fake”", "An explicit Unverifiable verdict keeps thin index coverage from becoming an accusation"],
    ["Structured output still fails", "Strict schemas, validators and fallbacks are needed around every LLM call"],
    ["Evaluate like a researcher", "A fresh held-out split exposed errors the dev set never showed"],
  ];
  items.forEach(([h, d], i) => {
    const y = 1.55 + i * 1.0;
    s.addShape(pres.shapes.OVAL, { x: MX, y: y + 0.12, w: 0.6, h: 0.6, fill: { color: NAVY },
      line: { color: NAVY, width: 0 } });
    s.addText(String(i + 1), { x: MX, y: y + 0.12, w: 0.6, h: 0.6, fontSize: 20, bold: true,
      color: "FFFFFF", align: "center", valign: "middle", margin: 0, isTextBox: true });
    s.addText([
      { text: h + ":  ", options: { bold: true, color: NAVY } },
      { text: d, options: { color: INK } },
    ], { x: MX + 0.85, y, w: W - 2 * MX - 0.85, h: 0.85, fontSize: 18, valign: "middle", margin: 0,
      isTextBox: true });
  });
}

// ------------------------------------------------------------------------------------------
// 12. Demo
// ------------------------------------------------------------------------------------------
{
  const s = slide("Demo: paste references, get verdicts with evidence, explanations and fixes", "Demo");
  const shots = ["demo_results.png", "demo_drawer.png"].map((f) => path.join(ASSETS, f));
  if (fs.existsSync(shots[0])) {
    s.addImage({ path: shots[0], x: MX, y: 1.5, w: 5.9, h: 3.69, objectName: "Results screenshot",
      altText: "CiteGuard results page listing verdicts for four citations" });
  }
  if (fs.existsSync(shots[1])) {
    s.addImage({ path: shots[1], x: 6.75, y: 1.5, w: 5.9, h: 3.69, objectName: "Evidence screenshot",
      altText: "CiteGuard evidence drawer for a fabricated citation" });
  }
  s.addText([
    { text: "Run it: ", options: { bold: true, color: NAVY } },
    { text: "make up", options: { fontFace: "Courier New" } },
    { text: "  →  http://localhost:8088   ·   CLI: ", options: {} },
    { text: "citeguard check refs.bib", options: { fontFace: "Courier New" } },
    { text: "   ·   Video: ", options: { bold: true, color: NAVY } },
    { text: "demo/citeguard_demo.webm", options: { fontFace: "Courier New" } },
  ], { x: MX, y: 5.45, w: W - 2 * MX, h: 0.5, fontSize: 16, color: INK, margin: 0, isTextBox: true });
  source(s, "Left: verdicts for a mixed reference list. Right: evidence and validated LLM explanation for a fabricated citation.");
}

// ------------------------------------------------------------------------------------------
// 13. References
// ------------------------------------------------------------------------------------------
{
  const s = slide("References", "Conclusion");
  const refs = [
    "Agrawal, Suzgun, Mackey & Kalai (2024). Do Language Models Know When They’re Hallucinating References? Findings of EACL.",
    "Khajavi, Sadeghi, Adhikari & Tessier (2026). CiteCheck: Retrieval-Grounded Detection of LLM Citation Hallucinations. arXiv:2605.27700.",
    "Kim, Brendel & Reizinger (2026). HALLMARK: How to Diagnose LLM Citation Verifiers and When to Deploy Them. arXiv:2607.18360.",
    "Li, Lin & Ma (2026). Source or It Didn’t Happen: A Multi-Agent Framework for Citation Hallucination Detection. arXiv:2605.08583.",
    "Lopez (2009). GROBID: Combining Automatic Bibliographic Data Recognition and Term Extraction. ECDL, LNCS 5714.",
    "OpenAI (2025). gpt-oss-120b & gpt-oss-20b Model Card. arXiv:2508.10925.",
    "Walters & Wilder (2023). Fabrication and errors in the bibliographic citations generated by ChatGPT. Scientific Reports 13, 14045.",
    "Zhao, Wang, Stuart, De Vaan, Ginsparg & Yin (2026). LLM hallucinations in the wild: Large-scale evidence from non-existent citations. arXiv:2605.07723.",
  ];
  s.addText(refs.map((r, i) => ({ text: r, options: { breakLine: i < refs.length - 1, paraSpaceAfter: 8 } })),
    { x: MX, y: 1.5, w: W - 2 * MX, h: 5.0, fontSize: 14, color: INK, valign: "top", margin: 0,
      isTextBox: true });
  source(s, "All references verified with CiteGuard itself (28 verified, 2 minor metadata differences, 0 fake). Full list in the report.");
}

// ------------------------------------------------------------------------------------------
// 14. Final slide: conclusions + links
// ------------------------------------------------------------------------------------------
{
  const s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Conclusion" });
  s.addText("Evidence decides whether a paper exists; the LLM explains, repairs and checks claims", {
    x: MX, y: 0.55, w: 12.1, h: 1.3, fontSize: 30, bold: true, color: "FFFFFF", margin: 0,
    valign: "top", isTextBox: true });
  s.addText([
    { text: `Fresh held-out split: fake-detection F1 ${noLlm.fake_detection.f1.toFixed(2)}, 0 correct citations called fake`, options: { bullet: { indent: 18 }, breakLine: true } },
    { text: `LLM-only judges call ${pct(correctFpr(summary("citebench_test3-llm_only-gpt-oss-20b")))}–${pct(correctFpr(big))} of correct citations fake`, options: { bullet: { indent: 18 }, breakLine: true } },
    { text: "Grounded explanations (19/19) and claim checks (0 false alarms on 25)", options: { bullet: { indent: 18 }, breakLine: true } },
    { text: "Next: chatbot-written references with human labels", options: { bullet: { indent: 18 } } },
  ], { x: MX, y: 2.05, w: 7.6, h: 3.0, fontSize: 19, color: "FFFFFF", margin: 0, valign: "top",
    paraSpaceAfter: 10, isTextBox: true });
  s.addImage({ path: path.join(ASSETS, "github_qr.png"), x: 9.45, y: 1.95, w: 2.9, h: 2.9,
    objectName: "GitHub QR", altText: "QR code linking to the GitHub repository" });
  s.addText([
    { text: "GitHub: ", options: { bold: true, color: "9DC3E6" } },
    { text: REPO, options: { color: "FFFFFF", hyperlink: { url: REPO } , breakLine: true } },
    { text: "Hugging Face: ", options: { bold: true, color: "9DC3E6" } },
    { text: "none (no trained weights; uses Groq-hosted gpt-oss models)", options: { color: "DCE6F0", breakLine: true } },
    { text: "Demo: ", options: { bold: true, color: "9DC3E6" } },
    { text: "web app (make up → localhost:8088), CLI, REST API, recorded video in demo/", options: { color: "DCE6F0" } },
  ], { x: MX, y: 5.35, w: 12.1, h: 1.4, fontSize: 16, margin: 0, valign: "top", paraSpaceAfter: 4,
    isTextBox: true });
  s.addText("Miten Gandhi · ILLM Final Project · Questions welcome", { x: MX, y: 6.95, w: 12.1, h: 0.35,
    fontSize: 12, color: "9DC3E6", margin: 0, isTextBox: true });
}

// ------------------------------------------------------------------------------------------
(async () => {
  await pres.writeFile({ fileName: OUT });
  const skill = process.env.PPTX_SKILL_DIR;
  if (skill) {
    const { applyTheme } = require(path.join(skill, "scripts", "apply_theme.js"));
    await applyTheme(OUT, THEME);
  }
  console.log("wrote", OUT);
})();
