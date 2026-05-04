"""
GenAI Evidence Hub — Paper Screening Tool
Screens academic papers for inclusion/exclusion in the systematic literature
review based on the GenAI Evidence Hub criteria.

Backend: Anthropic API (Claude Opus) only.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import json
import csv
import os
import time
import datetime
import base64
import requests
import anthropic
from pathlib import Path
import io
import re

# ── Constants ─────────────────────────────────────────────────────────────────

APP_TITLE  = "GenAI Evidence Hub — Paper Screener"
REPO_DIR   = Path.home() / "genai_evidence_hub"
REPO_JSON  = REPO_DIR / "paper_repository.json"
REPO_CSV   = REPO_DIR / "paper_repository.csv"
BATCH_TEMPLATE_CSV = REPO_DIR / "batch_template.csv"

CLAUDE_MODEL = "claude-opus-4-5"

PALETTE = {
    # Surfaces
    "bg":           "#F6F5F3",
    "surface":      "#FFFFFF",
    "surface_dim":  "#EFEDE9",
    "border":       "#E0DED9",
    "border_dark":  "#C4C0B8",
    # Type
    "ink":          "#18181A",
    "ink_mid":      "#52524E",
    "ink_faint":    "#96948E",
    # Brand / header
    "brand":        "#18181A",
    "brand_accent": "#C4984A",
    # Actions
    "action":       "#18181A",
    "action_text":  "#FFFFFF",
    "action_sec":   "#ECEAE5",
    "action_sec_t": "#18181A",
    # Signals
    "include":      "#1A6B45",
    "include_bg":   "#EAF5EE",
    "exclude":      "#B03030",
    "exclude_bg":   "#FAECEC",
    "manual":       "#8C6200",
    "manual_bg":    "#FDF4E3",
    # Console
    "console_bg":   "#111111",
    "console_fg":   "#D0CEC8",
    "console_ok":   "#4DC98A",
    "console_err":  "#E06060",
    "console_info": "#C4984A",
    "console_key":  "#78BFDA",
}

CSV_COLUMNS = [
    "paper_id", "title", "authors", "publication_year", "journal_or_venue",
    "doi", "abstract", "url", "file_path",
    "recommendation", "confidence", "genai_used", "relevant_domain",
    "quality_assurance", "domains_identified", "metrics_identified",
    "key_decision_factors", "additional_notes", "analyzed_at", "model_used",
]

BATCH_CSV_COLUMNS = ["paper_id", "url", "file_path"]

SYSTEM_PROMPT = """You are a systematic literature review screener for the GenAI Evidence Hub,
a research initiative examining generative AI in educational assessment contexts. Your job is
to evaluate whether a research paper meets the inclusion criteria for this meta-analysis.

## CRITICAL LANGUAGE RULE
All reasoning, text_examples, key_decision_factors, and additional_notes fields must contain
ONLY verifiable facts stated in the paper: model names, task descriptions, reported metrics,
dataset names, sample sizes, and direct quotes. Do NOT include evaluative language such as
"well-documented," "high-quality," "strong example," "impressive," "thorough," or any other
qualitative judgment about the paper's merit. Describe what the paper does, not how good it is.

## Criterion 1: GenAI Used — verdict: YES / NO / UNCLEAR
The primary AI system in the research must be a generative AI model.
- INCLUDE: Research uses an LLM or generative model (GPT-3/4/4o, Claude, Gemini, LLaMA,
  Mistral, DeepSeek, T5, BERT variants used generatively, etc.)
- INCLUDE: Ensemble models that combine a GenAI component with traditional ML
- EXCLUDE: Research uses only traditional/discriminative ML (SVM, Random Forest, KNN,
  logistic regression, XGBoost, CNN/RNN without a generative LLM component)
- EXCLUDE: Research where GenAI is only mentioned in the literature review but not used
- Must have been conducted after 2020

## Criterion 2: Relevant Assessment Domain — verdict: YES / NO / UNCLEAR
The research must directly perform one of the four assessment tasks below using GenAI.
"Discusses" or "mentions" a domain is NOT sufficient — the GenAI system must execute the task.

ITEM GENERATION (YES if):
  - GenAI directly generates assessment questions, test items, prompts, or rubrics
  - Covers any item type: MCQ, short answer, essay prompts, simulation tasks
  (NO if): GenAI generates other content (stories, summaries) not used as assessment items

FORMATIVE FEEDBACK (YES if):
  - GenAI generates feedback text delivered to students to improve their learning
  - Feedback is tied to student work or responses, not just general content
  (NO if): Paper evaluates whether humans can detect AI text; paper annotates data for
  future feedback systems; paper generates scoring labels without student-facing feedback

AUTOMATED ITEM SCORING (YES if):
  - GenAI assigns scores, grades, or ratings to student-produced work (essays, short
  answers, code, drawings, simulations) that is typically scored by humans
  - Includes holistic scoring, trait scoring, rubric-based scoring
  (NO if): GenAI classifies, annotates, or labels text for NLP/ML pipeline purposes
  without the output being a score on student work; GenAI detects whether text is
  AI-generated; GenAI scores non-student content

MULTIMODAL INFERENCES (YES if):
  - GenAI processes audio or video from classroom contexts to make assessment inferences
  - Includes speech recognition, behavioral coding, engagement detection from A/V data
  (NO if): Paper uses only text; multimodal data is not from a classroom/learning context

CROSS-CUTTING EXCLUSIONS for Criterion 2:
  - EXCLUDE if research task is AI detection / plagiarism detection
  - EXCLUDE if research task is data annotation / labeling for training future models
  - EXCLUDE if educational context is only background framing, not the actual study context
  - EXCLUDE if the paper addresses fairness analysis only, with no assessment task

## Criterion 3: Quality Assurance — verdict: YES / NO / UNCLEAR
The paper must report quantitative evaluation metrics for the GenAI system's outputs.
Acceptable metrics include but are not limited to:
  - Precision, Recall, F1-score (with baseline or comparison group)
  - Accuracy vs. established benchmark or human raters
  - Cohen's Kappa, Weighted Kappa, Quadratic Weighted Kappa (QWK)
  - AUROC, BLEU, ROUGE, GLEU, BERTScore
  - Pearson/Spearman correlation with human scores
  - Agreement rates (exact, adjacent) compared to human rater agreement
EXCLUDE if: paper only reports descriptive outputs with no quantitative evaluation;
paper describes a system without empirical results; evaluation metrics are only for
a non-GenAI baseline with no GenAI-specific scores reported

## Confidence Calibration
Assign confidence based on how much interpretation was required:
- High: All three criteria are unambiguously met or unambiguously not met based on
  explicit statements in the paper. No domain boundary judgment was required.
- Medium: At least one criterion required meaningful interpretation — e.g., the domain
  is adjacent to but not clearly within scope; the GenAI role is secondary or unclear;
  metrics are reported but for a proxy task rather than the main assessment outcome.
- Low: The paper sits on a genuine domain boundary; key information is missing or
  contradictory; the assessment task could be interpreted either way by a reasonable reviewer.

## Decision Rules
- INCLUDE: All three criteria YES
- EXCLUDE: Any criterion NO; paper not in English; paper published before 2023
- MANUAL_REVIEW: Any criterion UNCLEAR, or genuinely borderline domain classification

## Publication Metadata Extraction
Extract the following fields directly from the paper. Report null for any field not found.
- title: Full paper title as printed
- authors: All author names as listed, in order, separated by "; "
- publication_year: 4-digit year from header, footer, copyright notice, or journal metadata
- journal_or_venue: Journal name, conference name, or preprint server (e.g. "arXiv", "OSF Preprints")
- doi: DOI string if present (e.g. "10.1016/j.compedu.2024.01.001"), without "https://doi.org/" prefix
- abstract: The full abstract text, copied verbatim from the paper

## Required Output Format
Respond ONLY with valid JSON in this exact structure (no markdown fences, no preamble):
{
  "overall_recommendation": "INCLUDE",
  "title": "Full paper title",
  "authors": "Last, First; Last, First",
  "publication_year": "2024",
  "journal_or_venue": "Computers and Education: Artificial Intelligence",
  "doi": "10.1016/j.compedu.2024.01.001",
  "abstract": "Full abstract text copied verbatim from the paper.",
  "criteria": {
    "genai_used": {
      "verdict": "YES",
      "reasoning": "Factual description of which GenAI model was used and for what task",
      "text_examples": "Direct quote or close paraphrase from the paper",
      "location": "Page/section reference"
    },
    "relevant_domain": {
      "verdict": "YES",
      "domains_identified": ["Automated Item Scoring"],
      "reasoning": "Factual description of what assessment task the GenAI system performs",
      "text_examples": "Direct quote or close paraphrase from the paper",
      "location": "Page/section reference"
    },
    "quality_assurance": {
      "verdict": "YES",
      "metrics_identified": ["Quadratic Weighted Kappa", "F1"],
      "reasoning": "List of specific metrics reported and what they measure in this paper",
      "text_examples": "Direct quote or close paraphrase from the paper",
      "location": "Page/section reference"
    }
  },
  "confidence_level": "High",
  "confidence_rationale": "Specific statement of which criterion required interpretation, or confirmation that all criteria were unambiguous",
  "key_decision_factors": "Factual list of the specific evidence that determined the recommendation",
  "additional_notes": "Factual observations relevant for human reviewers: domain boundary issues, missing information, or conflicting signals in the paper"
}"""


# ── Repository ────────────────────────────────────────────────────────────────

def ensure_repo():
    REPO_DIR.mkdir(parents=True, exist_ok=True)
    if not REPO_JSON.exists():
        REPO_JSON.write_text(json.dumps([], indent=2), encoding="utf-8")
    if not REPO_CSV.exists():
        with open(REPO_CSV, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_COLUMNS).writeheader()
    if not BATCH_TEMPLATE_CSV.exists():
        with open(BATCH_TEMPLATE_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=BATCH_CSV_COLUMNS)
            w.writeheader()
            w.writerow({
                "paper_id": "PAPER_001",
                "url": "https://example.com/paper.pdf",
                "file_path": "",
            })


def load_repository():
    ensure_repo()
    try:
        return json.loads(REPO_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_to_repository(entry: dict):
    ensure_repo()
    repo = load_repository()
    for i, r in enumerate(repo):
        if r.get("paper_id") == entry.get("paper_id"):
            repo[i] = entry
            break
    else:
        repo.append(entry)
    # Always keep sorted by paper_id ascending (numeric if possible, else lexicographic)
    def _sort_key(r):
        pid = r.get("paper_id", "")
        try:
            return (0, int(pid))
        except (ValueError, TypeError):
            return (1, str(pid))
    repo.sort(key=_sort_key)
    REPO_JSON.write_text(json.dumps(repo, indent=2, ensure_ascii=False), encoding="utf-8")
    _sync_csv(repo)


def _sync_csv(repo: list):
    with open(REPO_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in repo:
            w.writerow(r)


# ── PDF / URL helpers ─────────────────────────────────────────────────────────

def fetch_pdf_from_url(url: str):
    """Returns (bytes_or_None, error_str)."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; GenAI Evidence Hub Screener)"}
        resp = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        ct = resp.headers.get("content-type", "")
        if "pdf" in ct or url.lower().endswith(".pdf") or resp.content[:4] == b"%PDF":
            return resp.content, ""
        return None, f"URL did not return a PDF (content-type: {ct})"
    except requests.exceptions.RequestException as e:
        return None, str(e)


# ── Analysis ──────────────────────────────────────────────────────────────────

def _clean_json(raw: str) -> dict:
    raw = raw.strip()
    # Strip markdown fences if present
    raw = re.sub(r"^```json\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"^```\s*",     "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$",     "", raw, flags=re.MULTILINE)
    raw = raw.strip()
    # Find the start of the JSON object
    start = raw.find("{")
    if start == -1:
        raise json.JSONDecodeError("No JSON object found in response", raw, 0)
    # Use raw_decode so it stops at the end of the first complete object,
    # ignoring any trailing text Claude may have appended after the closing }
    obj, _ = json.JSONDecoder().raw_decode(raw, start)
    return obj


def analyze_paper(pdf_bytes: bytes, api_key: str, progress_callback=None) -> dict:
    """Send PDF natively to Claude and return parsed result dict."""
    if progress_callback:
        progress_callback("Sending PDF to Claude…")

    client  = anthropic.Anthropic(api_key=api_key)
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_b64,
                    },
                },
                {
                    "type": "text",
                    "text": (
                        "Evaluate this paper against the GenAI Evidence Hub inclusion criteria. "
                        "Read the full paper carefully before deciding. "
                        "Return ONLY valid JSON — no markdown, no preamble."
                    ),
                },
            ],
        }],
    )

    return _clean_json(response.content[0].text)


# ── GUI ───────────────────────────────────────────────────────────────────────

class PaperScreenerApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1140x860")
        self.minsize(960, 700)
        self.configure(bg=PALETTE["bg"])

        ensure_repo()
        self._api_key           = tk.StringVar()
        self._current_pdf_bytes = None
        self._batch_csv_path    = None
        self._busy              = False
        self._stop_requested    = False

        # Timer state
        self._single_start_time = None
        self._batch_start_time  = None
        self._paper_start_time  = None
        self._timer_after_id    = None

        self._apply_styles()
        self._build_ui()
        self._refresh_repository_tab()

    # ── Styles ────────────────────────────────────────────────────────────────

    def _apply_styles(self):
        s = ttk.Style(self)
        s.theme_use("default")

        # Notebook
        s.configure("TNotebook",
                    background=PALETTE["bg"], borderwidth=0, tabmargins=[0, 0, 0, 0])
        s.configure("TNotebook.Tab",
                    background=PALETTE["bg"], foreground=PALETTE["ink_faint"],
                    padding=[20, 10], font=("Helvetica", 9, "bold"),
                    borderwidth=0, relief="flat")
        s.map("TNotebook.Tab",
              background=[("selected", PALETTE["surface"])],
              foreground=[("selected", PALETTE["ink"])],
              expand=[("selected", [0, 0, 0, 0])])

        # Progress bars
        s.configure("Thin.Horizontal.TProgressbar",
                    troughcolor=PALETTE["border"], background=PALETTE["ink"],
                    borderwidth=0, thickness=3)
        s.configure("Indeterminate.Horizontal.TProgressbar",
                    troughcolor=PALETTE["border"], background=PALETTE["brand_accent"],
                    borderwidth=0, thickness=3)

        # Treeview
        s.configure("Repo.Treeview",
                    rowheight=28, font=("Helvetica", 9),
                    background=PALETTE["surface"],
                    fieldbackground=PALETTE["surface"],
                    foreground=PALETTE["ink"],
                    borderwidth=0, relief="flat")
        s.configure("Repo.Treeview.Heading",
                    font=("Helvetica", 8, "bold"),
                    background=PALETTE["surface_dim"],
                    foreground=PALETTE["ink_mid"],
                    borderwidth=0, relief="flat",
                    padding=[8, 6])
        s.map("Repo.Treeview",
              background=[("selected", PALETTE["brand_accent"])],
              foreground=[("selected", PALETTE["surface"])])

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()

        # Tab strip sits directly below header
        self.notebook = ttk.Notebook(self, style="TNotebook")
        self.notebook.pack(fill="both", expand=True)

        self.tab_single = tk.Frame(self.notebook, bg=PALETTE["bg"])
        self.tab_batch  = tk.Frame(self.notebook, bg=PALETTE["bg"])
        self.tab_repo   = tk.Frame(self.notebook, bg=PALETTE["bg"])
        self.tab_config = tk.Frame(self.notebook, bg=PALETTE["bg"])

        self.notebook.add(self.tab_single, text="Single Paper")
        self.notebook.add(self.tab_batch,  text="Batch Upload")
        self.notebook.add(self.tab_repo,   text="Repository")
        self.notebook.add(self.tab_config, text="Settings")

        self._build_single_tab()
        self._build_batch_tab()
        self._build_repo_tab()
        self._build_config_tab()

    def _build_header(self):
        hdr = tk.Frame(self, bg=PALETTE["brand"], height=56)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        left = tk.Frame(hdr, bg=PALETTE["brand"])
        left.pack(side="left", padx=28, fill="y")

        tk.Label(left, text="GenAI Evidence Hub",
                 font=("Georgia", 15, "bold"),
                 fg=PALETTE["brand_accent"],
                 bg=PALETTE["brand"]).pack(side="left", anchor="center")

        tk.Label(left, text="  ·  Paper Screener",
                 font=("Helvetica", 11),
                 fg="#6A6A60",
                 bg=PALETTE["brand"]).pack(side="left", anchor="center")

        tk.Label(hdr, text="Learning Data Insights, LLC",
                 font=("Helvetica", 8),
                 fg="#4A4A44",
                 bg=PALETTE["brand"]).pack(side="right", padx=28, anchor="center")

    # ── Helpers: card and button factories ────────────────────────────────────

    def _card(self, parent, label=None, pad=(20, 12)):
        """A flat white card with optional section label above it."""
        outer = tk.Frame(parent, bg=PALETTE["bg"])
        outer.pack(fill="x", padx=24, pady=(8, 0))
        if label:
            tk.Label(outer, text=label.upper(),
                     bg=PALETTE["bg"], fg=PALETTE["ink_faint"],
                     font=("Helvetica", 7, "bold"),
                     anchor="w").pack(fill="x", pady=(0, 4))
        card = tk.Frame(outer, bg=PALETTE["surface"],
                        highlightbackground=PALETTE["border"],
                        highlightthickness=1)
        card.pack(fill="x")
        inner = tk.Frame(card, bg=PALETTE["surface"])
        inner.pack(fill="x", padx=pad[0], pady=pad[1])
        return inner

    def _btn(self, parent, text, command, style="primary",
             padx=18, pady=7, width=None):
        """Flat button with primary / secondary / danger styles."""
        cfg = {
            "primary":   (PALETTE["action"],     PALETTE["action_text"]),
            "secondary": (PALETTE["action_sec"],  PALETTE["action_sec_t"]),
            "danger":    (PALETTE["exclude"],      "#FFFFFF"),
            "ghost":     (PALETTE["bg"],           PALETTE["ink_mid"]),
        }
        bg, fg = cfg.get(style, cfg["primary"])
        kw = dict(text=text, command=command, bg=bg, fg=fg,
                  font=("Helvetica", 9, "bold"), relief="flat",
                  padx=padx, pady=pady, cursor="hand2",
                  activebackground=bg, activeforeground=fg,
                  bd=0)
        if width:
            kw["width"] = width
        return tk.Button(parent, **kw)

    def _divider(self, parent, vertical_pad=8):
        tk.Frame(parent, bg=PALETTE["border"], height=1).pack(
            fill="x", padx=24, pady=vertical_pad)

    # ── Single Paper Tab ──────────────────────────────────────────────────────

    def _build_single_tab(self):
        f = self.tab_single

        # ── Paper ID card ──
        id_inner = self._card(f, label="Paper ID")
        id_row = tk.Frame(id_inner, bg=PALETTE["surface"])
        id_row.pack(fill="x")

        self._paper_id_var = tk.StringVar()
        id_entry = tk.Entry(id_row, textvariable=self._paper_id_var,
                            font=("Helvetica", 11), bd=0, relief="flat",
                            bg=PALETTE["surface"], fg=PALETTE["ink"],
                            insertbackground=PALETTE["ink"],
                            highlightthickness=1,
                            highlightbackground=PALETTE["border"],
                            highlightcolor=PALETTE["ink"], width=22)
        id_entry.pack(side="left", ipady=6, padx=(0, 16))

        tk.Label(id_row, text="All other metadata is extracted automatically from the PDF.",
                 bg=PALETTE["surface"], fg=PALETTE["ink_faint"],
                 font=("Helvetica", 8, "italic")).pack(side="left")

        # ── Source card ──
        src_inner = self._card(f, label="Paper Source")

        url_row = tk.Frame(src_inner, bg=PALETTE["surface"])
        url_row.pack(fill="x", pady=(0, 8))
        tk.Label(url_row, text="URL", bg=PALETTE["surface"], fg=PALETTE["ink_mid"],
                 font=("Helvetica", 8, "bold"), width=6, anchor="w").pack(side="left")
        self._url_var = tk.StringVar()
        url_entry = tk.Entry(url_row, textvariable=self._url_var,
                             font=("Helvetica", 9), bd=0, relief="flat",
                             bg=PALETTE["surface_dim"], fg=PALETTE["ink"],
                             insertbackground=PALETTE["ink"],
                             highlightthickness=1,
                             highlightbackground=PALETTE["border"],
                             highlightcolor=PALETTE["ink"])
        url_entry.pack(side="left", fill="x", expand=True, ipady=5, padx=(6, 10))
        self._btn(src_inner if False else url_row,
                  "Fetch", self._fetch_url, "secondary", padx=14, pady=5
                  ).pack(side="left")

        sep_row = tk.Frame(src_inner, bg=PALETTE["surface"])
        sep_row.pack(fill="x", pady=4)
        tk.Frame(sep_row, bg=PALETTE["border"], height=1).pack(
            side="left", fill="x", expand=True)
        tk.Label(sep_row, text="  or  ", bg=PALETTE["surface"],
                 fg=PALETTE["ink_faint"], font=("Helvetica", 8)).pack(side="left")
        tk.Frame(sep_row, bg=PALETTE["border"], height=1).pack(
            side="left", fill="x", expand=True)

        file_row = tk.Frame(src_inner, bg=PALETTE["surface"])
        file_row.pack(fill="x")
        self._btn(file_row, "Upload PDF", self._upload_pdf,
                  "secondary", padx=14, pady=5).pack(side="left")
        self._file_label = tk.Label(file_row, text="No file selected",
                                    bg=PALETTE["surface"], fg=PALETTE["ink_faint"],
                                    font=("Helvetica", 8, "italic"))
        self._file_label.pack(side="left", padx=12)

        # ── Analyze button + progress ──
        act_outer = tk.Frame(f, bg=PALETTE["bg"])
        act_outer.pack(fill="x", padx=24, pady=12)

        self._analyze_btn = self._btn(act_outer, "Analyze Paper",
                                      self._run_single_analysis, "primary",
                                      padx=24, pady=9)
        self._analyze_btn.pack(side="left")

        prog_right = tk.Frame(act_outer, bg=PALETTE["bg"])
        prog_right.pack(side="left", fill="x", expand=True, padx=20)

        prog_top = tk.Frame(prog_right, bg=PALETTE["bg"])
        prog_top.pack(fill="x")
        self._progress_label = tk.Label(
            prog_top, text="Ready.", bg=PALETTE["bg"],
            fg=PALETTE["ink_faint"], font=("Helvetica", 8, "italic"), anchor="w")
        self._progress_label.pack(side="left", fill="x", expand=True)
        self._single_timer_label = tk.Label(
            prog_top, text="", bg=PALETTE["bg"],
            fg=PALETTE["brand_accent"], font=("Courier", 9, "bold"), anchor="e", width=8)
        self._single_timer_label.pack(side="right")

        self._single_pbar = ttk.Progressbar(
            prog_right, mode="indeterminate",
            style="Indeterminate.Horizontal.TProgressbar")
        self._single_pbar.pack(fill="x", pady=(4, 0))

        self._divider(f, vertical_pad=0)

        # ── Results ──
        res_outer = tk.Frame(f, bg=PALETTE["bg"])
        res_outer.pack(fill="both", expand=True, padx=24, pady=(10, 16))

        tk.Label(res_outer, text="ANALYSIS RESULTS",
                 bg=PALETTE["bg"], fg=PALETTE["ink_faint"],
                 font=("Helvetica", 7, "bold"), anchor="w").pack(fill="x", pady=(0, 4))

        res_card = tk.Frame(res_outer, bg=PALETTE["console_bg"],
                            highlightbackground=PALETTE["border"],
                            highlightthickness=1)
        res_card.pack(fill="both", expand=True)

        self._result_text = scrolledtext.ScrolledText(
            res_card, font=("Courier New", 9),
            bg=PALETTE["console_bg"], fg=PALETTE["console_fg"],
            insertbackground=PALETTE["console_fg"],
            bd=0, padx=16, pady=12, wrap="word",
            selectbackground=PALETTE["ink_mid"])
        self._result_text.pack(fill="both", expand=True)
        self._result_text.insert("1.0", "Results will appear here after analysis.")
        self._result_text.configure(state="disabled")

        for tag, color in [
            ("include",  PALETTE["console_ok"]),
            ("exclude",  PALETTE["console_err"]),
            ("manual",   PALETTE["console_info"]),
            ("yes",      PALETTE["console_ok"]),
            ("no",       PALETTE["console_err"]),
            ("unclear",  PALETTE["console_info"]),
            ("key",      PALETTE["console_key"]),
        ]:
            self._result_text.tag_config(tag, foreground=color)
        self._result_text.tag_config(
            "heading", foreground=PALETTE["brand_accent"],
            font=("Courier New", 9, "bold"))

    # ── Batch Tab ─────────────────────────────────────────────────────────────

    def _build_batch_tab(self):
        f = self.tab_batch

        # ── Instructions card ──
        info_inner = self._card(f, label="Instructions")
        tk.Label(info_inner, bg=PALETTE["surface"], fg=PALETTE["ink_mid"],
                 font=("Helvetica", 9), justify="left", anchor="w",
                 text=(
                     "Upload a CSV with one paper per row.\n"
                     "Required column: paper_id\n"
                     "Source (at least one): url  or  file_path\n"
                     "All metadata is extracted automatically from each PDF."
                 )).pack(anchor="w", pady=(0, 8))
        self._btn(info_inner, "Download CSV Template",
                  self._download_batch_template, "secondary",
                  padx=14, pady=5).pack(anchor="w")

        # ── File selection + controls ──
        ctrl_inner = self._card(f, label="Batch File")
        ctrl_row = tk.Frame(ctrl_inner, bg=PALETTE["surface"])
        ctrl_row.pack(fill="x")

        self._btn(ctrl_row, "Select CSV", self._select_batch_csv,
                  "secondary", padx=14, pady=6).pack(side="left")
        self._batch_file_label = tk.Label(
            ctrl_row, text="No file selected",
            bg=PALETTE["surface"], fg=PALETTE["ink_faint"],
            font=("Helvetica", 8, "italic"))
        self._batch_file_label.pack(side="left", padx=12)

        self._batch_stop_btn = self._btn(
            ctrl_row, "⏹  Stop", self._stop_batch, "danger", padx=14, pady=6)
        self._batch_stop_btn.pack(side="right")
        self._batch_stop_btn.config(state="disabled")

        self._batch_run_btn = self._btn(
            ctrl_row, "Run Batch Analysis", self._run_batch_analysis,
            "primary", padx=18, pady=6)
        self._batch_run_btn.pack(side="right", padx=(0, 10))
        self._batch_run_btn.config(state="disabled")

        # ── Progress panel ──
        prog_inner = self._card(f, label="Progress", pad=(20, 14))

        # Bar row
        bar_row = tk.Frame(prog_inner, bg=PALETTE["surface"])
        bar_row.pack(fill="x", pady=(0, 6))
        self._batch_progress = ttk.Progressbar(
            bar_row, mode="determinate",
            style="Thin.Horizontal.TProgressbar")
        self._batch_progress.pack(side="left", fill="x", expand=True)
        self._batch_pct_label = tk.Label(
            bar_row, text="", bg=PALETTE["surface"],
            fg=PALETTE["ink_mid"], font=("Helvetica", 8, "bold"), width=5, anchor="e")
        self._batch_pct_label.pack(side="right")

        # Status row
        stat_row = tk.Frame(prog_inner, bg=PALETTE["surface"])
        stat_row.pack(fill="x")
        self._batch_status = tk.Label(
            stat_row, text="", bg=PALETTE["surface"],
            fg=PALETTE["ink_mid"], font=("Helvetica", 8), anchor="w")
        self._batch_status.pack(side="left", fill="x", expand=True)
        self._paper_timer_label = tk.Label(
            stat_row, text="", bg=PALETTE["surface"],
            fg=PALETTE["brand_accent"], font=("Courier", 8), anchor="e", width=14)
        self._paper_timer_label.pack(side="right")

        # Counts row
        counts_row = tk.Frame(prog_inner, bg=PALETTE["surface"])
        counts_row.pack(fill="x", pady=(4, 0))
        self._batch_counts_label = tk.Label(
            counts_row, text="", bg=PALETTE["surface"],
            fg=PALETTE["ink_faint"], font=("Helvetica", 8), anchor="w")
        self._batch_counts_label.pack(side="left", fill="x", expand=True)
        self._batch_total_timer_label = tk.Label(
            counts_row, text="", bg=PALETTE["surface"],
            fg=PALETTE["brand_accent"], font=("Courier", 8, "bold"), anchor="e", width=14)
        self._batch_total_timer_label.pack(side="right")

        # ── Log ──
        log_outer = tk.Frame(f, bg=PALETTE["bg"])
        log_outer.pack(fill="both", expand=True, padx=24, pady=(10, 16))

        tk.Label(log_outer, text="LOG",
                 bg=PALETTE["bg"], fg=PALETTE["ink_faint"],
                 font=("Helvetica", 7, "bold"), anchor="w").pack(fill="x", pady=(0, 4))

        log_card = tk.Frame(log_outer, bg=PALETTE["console_bg"],
                            highlightbackground=PALETTE["border"],
                            highlightthickness=1)
        log_card.pack(fill="both", expand=True)

        self._batch_log = scrolledtext.ScrolledText(
            log_card, font=("Courier New", 9),
            bg=PALETTE["console_bg"], fg=PALETTE["console_fg"],
            bd=0, padx=16, pady=12, wrap="word")
        self._batch_log.pack(fill="both", expand=True)

        for tag, color in [
            ("ok",   PALETTE["console_ok"]),
            ("err",  PALETTE["console_err"]),
            ("info", PALETTE["console_info"]),
        ]:
            self._batch_log.tag_config(tag, foreground=color)

    # ── Repository Tab ────────────────────────────────────────────────────────

    def _build_repo_tab(self):
        f = self.tab_repo

        # ── Toolbar ──
        bar = tk.Frame(f, bg=PALETTE["bg"])
        bar.pack(fill="x", padx=24, pady=12)

        self._btn(bar, "Refresh", self._refresh_repository_tab,
                  "secondary", padx=14, pady=5).pack(side="left")
        self._btn(bar, "Open Folder",
                  lambda: os.startfile(REPO_DIR),
                  "ghost", padx=14, pady=5).pack(side="left", padx=8)

        # Filter pills
        ff = tk.Frame(bar, bg=PALETTE["bg"])
        ff.pack(side="right")

        tk.Label(ff, text="Search", bg=PALETTE["bg"], fg=PALETTE["ink_faint"],
                 font=("Helvetica", 8)).pack(side="left", padx=(0, 4))
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._refresh_repository_tab())
        srch = tk.Entry(ff, textvariable=self._filter_var,
                        font=("Helvetica", 9), bd=0, relief="flat",
                        bg=PALETTE["surface"], fg=PALETTE["ink"],
                        insertbackground=PALETTE["ink"],
                        highlightthickness=1,
                        highlightbackground=PALETTE["border"],
                        highlightcolor=PALETTE["ink"], width=18)
        srch.pack(side="left", ipady=4, padx=(0, 16))

        self._rec_filter = tk.StringVar(value="All")
        pill_cfg = [
            ("All",          PALETTE["ink_mid"],  PALETTE["action_sec"]),
            ("INCLUDE",      PALETTE["include"],   PALETTE["include_bg"]),
            ("EXCLUDE",      PALETTE["exclude"],   PALETTE["exclude_bg"]),
            ("MANUAL_REVIEW",PALETTE["manual"],    PALETTE["manual_bg"]),
        ]
        for val, fg, pill_bg in pill_cfg:
            rb = tk.Radiobutton(
                ff, text=val.replace("_", " "), variable=self._rec_filter,
                value=val, command=self._refresh_repository_tab,
                bg=PALETTE["bg"], fg=fg, activebackground=PALETTE["bg"],
                activeforeground=fg, selectcolor=PALETTE["bg"],
                font=("Helvetica", 8, "bold"),
                indicatoron=0, relief="flat",
                padx=10, pady=4,
                cursor="hand2")
            rb.pack(side="left", padx=2)

        # ── Tree ──
        tf = tk.Frame(f, bg=PALETTE["bg"])
        tf.pack(fill="both", expand=True, padx=24, pady=(0, 4))

        cols   = ("paper_id", "title", "authors", "publication_year",
                  "journal_or_venue", "recommendation", "confidence", "analyzed_at")
        widths = (72, 230, 150, 52, 138, 108, 66, 126)

        self._tree = ttk.Treeview(tf, columns=cols, show="headings",
                                  style="Repo.Treeview", selectmode="browse")
        for col, w in zip(cols, widths):
            label = col.replace("_", " ").title()
            self._tree.heading(col, text=label,
                               command=lambda c=col: self._sort_tree(c))
            self._tree.column(col, width=w, anchor="w", minwidth=40)

        vsb = ttk.Scrollbar(tf, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self._tree.tag_configure("include", background=PALETTE["include_bg"])
        self._tree.tag_configure("exclude", background=PALETTE["exclude_bg"])
        self._tree.tag_configure("manual",  background=PALETTE["manual_bg"])
        self._tree.bind("<Double-1>", self._view_repo_entry)

        tk.Label(f, text="Double-click a row to view full analysis  ·  Click column headers to sort",
                 bg=PALETTE["bg"], fg=PALETTE["ink_faint"],
                 font=("Helvetica", 7, "italic")).pack(pady=4)

    # ── Settings Tab ──────────────────────────────────────────────────────────

    def _build_config_tab(self):
        f = self.tab_config

        # ── API Key card ──
        key_inner = self._card(f, label="Anthropic API Key", pad=(20, 16))

        key_row = tk.Frame(key_inner, bg=PALETTE["surface"])
        key_row.pack(fill="x")

        self._key_entry = tk.Entry(
            key_row, textvariable=self._api_key,
            font=("Courier New", 10), show="*", width=50,
            bd=0, relief="flat",
            bg=PALETTE["surface_dim"], fg=PALETTE["ink"],
            insertbackground=PALETTE["ink"],
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
            highlightcolor=PALETTE["ink"])
        self._key_entry.pack(side="left", ipady=6, padx=(0, 10))
        self._btn(key_row, "Show / Hide", self._toggle_key_vis,
                  "ghost", padx=12, pady=5).pack(side="left")

        tk.Frame(key_inner, bg=PALETTE["border"], height=1).pack(fill="x", pady=12)

        info_lines = [
            ("Key is stored in memory only — never written to disk.", PALETTE["ink_faint"]),
            ("Get a key:    console.anthropic.com  →  API Keys  →  Create Key", PALETTE["ink_mid"]),
            ("Add credits:  console.anthropic.com  →  Billing  (minimum $5)", PALETTE["ink_mid"]),
            ("", PALETTE["ink_faint"]),
            (f"Model:   {CLAUDE_MODEL}", PALETTE["ink_mid"]),
            ("Cost:    ~$0.01–0.03 per paper  ·  200 papers ≈ $4–6 total", PALETTE["ink_mid"]),
        ]
        for text, color in info_lines:
            tk.Label(key_inner, text=text, bg=PALETTE["surface"],
                     fg=color, font=("Helvetica", 8), anchor="w",
                     justify="left").pack(fill="x")

        # ── Repository card ──
        repo_inner = self._card(f, label="Repository", pad=(20, 16))

        tk.Label(repo_inner, text=str(REPO_DIR),
                 bg=PALETTE["surface"], fg=PALETTE["ink"],
                 font=("Courier New", 9), anchor="w").pack(fill="x")

        tk.Frame(repo_inner, bg=PALETTE["border"], height=1).pack(fill="x", pady=10)

        for label, fname in [
            ("Full data (JSON):", "paper_repository.json"),
            ("Spreadsheet (CSV):", "paper_repository.csv"),
            ("Batch template:", "batch_template.csv"),
        ]:
            row = tk.Frame(repo_inner, bg=PALETTE["surface"])
            row.pack(fill="x", pady=1)
            tk.Label(row, text=label, bg=PALETTE["surface"],
                     fg=PALETTE["ink_faint"], font=("Helvetica", 8),
                     width=18, anchor="w").pack(side="left")
            tk.Label(row, text=fname, bg=PALETTE["surface"],
                     fg=PALETTE["ink_mid"], font=("Courier New", 8),
                     anchor="w").pack(side="left")

    # ── Settings helpers ──────────────────────────────────────────────────────

    def _toggle_key_vis(self):
        self._key_entry.config(show="" if self._key_entry.cget("show") == "*" else "*")

    # ── Single paper actions ──────────────────────────────────────────────────

    def _fetch_url(self):
        url = self._url_var.get().strip()
        if not url:
            messagebox.showwarning("No URL", "Please enter a URL first.")
            return
        self._set_progress("Fetching PDF from URL…")
        self._set_busy(True)
        def _do():
            pdf_bytes, err = fetch_pdf_from_url(url)
            if pdf_bytes:
                self._current_pdf_bytes = pdf_bytes
                self.after(0, lambda: self._file_label.config(
                    text=f"Fetched ({len(pdf_bytes)//1024} KB)", fg=PALETTE["include"]))
                self.after(0, self._set_progress, "PDF fetched — ready to analyze.")
            else:
                self._current_pdf_bytes = None
                self.after(0, lambda: self._file_label.config(
                    text=f"Failed: {err[:55]}", fg=PALETTE["exclude"]))
                self.after(0, self._set_progress, "Fetch failed — upload PDF manually.")
                self.after(0, messagebox.showwarning, "Fetch Failed",
                           f"Could not retrieve PDF:\n{err}\n\nPlease upload the PDF manually.")
            self.after(0, self._set_busy, False)
        threading.Thread(target=_do, daemon=True).start()

    def _upload_pdf(self):
        path = filedialog.askopenfilename(
            title="Select PDF", filetypes=[("PDF files", "*.pdf")])
        if path:
            with open(path, "rb") as fh:
                self._current_pdf_bytes = fh.read()
            name = Path(path).name
            self._file_label.config(
                text=f"{name} ({len(self._current_pdf_bytes)//1024} KB)",
                fg=PALETTE["include"])
            self._set_progress(f"Loaded: {name}")

    def _run_single_analysis(self):
        if not self._validate_ready(need_pdf=True):
            return
        paper_id = self._paper_id_var.get().strip()
        if not paper_id:
            messagebox.showwarning("Missing ID", "Please enter a Paper ID.")
            return
        self._set_busy(True)
        self._set_progress("Starting analysis…")
        self._single_timer_label.config(text="")
        self._start_single_timer()
        threading.Thread(target=self._analysis_worker, args=(paper_id,), daemon=True).start()

    def _analysis_worker(self, paper_id: str):
        t0 = time.monotonic()
        try:
            result = analyze_paper(
                self._current_pdf_bytes,
                api_key=self._api_key.get().strip(),
                progress_callback=lambda m: self.after(0, self._set_progress, m),
            )
            elapsed = time.monotonic() - t0
            entry = self._build_repo_entry(paper_id, result)
            save_to_repository(entry)
            self.after(0, self._display_result, result, paper_id)
            self.after(0, self._refresh_repository_tab)
            self.after(0, self._set_progress,
                       f"Analysis complete — saved to repository.  ({self._fmt_elapsed(elapsed)})")
            self.after(0, self._stop_single_timer, elapsed)
        except Exception as e:
            self.after(0, self._stop_single_timer, None)
            self.after(0, self._set_progress, "Analysis failed.")
            self.after(0, messagebox.showerror, "Error", str(e))
        finally:
            self.after(0, self._set_busy, False)

    def _build_repo_entry(self, paper_id: str, result: dict) -> dict:
        c  = result.get("criteria", {})
        gn = c.get("genai_used", {})
        dm = c.get("relevant_domain", {})
        qa = c.get("quality_assurance", {})
        return {
            "paper_id":           paper_id,
            "title":              str(result.get("title") or "").strip(),
            "authors":            str(result.get("authors") or "").strip(),
            "publication_year":   str(result.get("publication_year") or "").strip(),
            "journal_or_venue":   str(result.get("journal_or_venue") or "").strip(),
            "doi":                str(result.get("doi") or "").strip(),
            "abstract":           str(result.get("abstract") or "").strip(),
            "url":                self._url_var.get().strip(),
            "file_path":          "",
            "recommendation":     result.get("overall_recommendation", ""),
            "confidence":         result.get("confidence_level", ""),
            "genai_used":         gn.get("verdict", ""),
            "relevant_domain":    dm.get("verdict", ""),
            "quality_assurance":  qa.get("verdict", ""),
            "domains_identified": "; ".join(dm.get("domains_identified", [])),
            "metrics_identified": "; ".join(qa.get("metrics_identified", [])),
            "key_decision_factors": result.get("key_decision_factors", ""),
            "additional_notes":   result.get("additional_notes", ""),
            "analyzed_at":        datetime.datetime.now().isoformat(timespec="seconds"),
            "model_used":         CLAUDE_MODEL,
            "_full_result":       result,
        }

    def _display_result(self, result: dict, paper_id: str):
        rec  = result.get("overall_recommendation", "?")
        conf = result.get("confidence_level", "?")
        crit = result.get("criteria", {})
        rtag = {"INCLUDE":"include","EXCLUDE":"exclude","MANUAL_REVIEW":"manual"}.get(rec, "")
        vtag = {"YES":"yes","NO":"no","UNCLEAR":"unclear"}

        lines = []
        def w(text, tag=None): lines.append((text, tag))

        w("=" * 68)
        w(f"  PAPER: {paper_id}", "heading")
        w(f"  RECOMMENDATION:  {rec}", rtag)
        w(f"  CONFIDENCE:      {conf}")
        if result.get("title"):
            w(f"  TITLE:           {result['title']}")
        if result.get("authors"):
            w(f"  AUTHORS:         {result['authors']}")
        if result.get("publication_year"):
            w(f"  YEAR:            {result['publication_year']}")
        if result.get("journal_or_venue"):
            w(f"  VENUE:           {result['journal_or_venue']}")
        if result.get("doi"):
            w(f"  DOI:             {result['doi']}")
        w("=" * 68)

        for key, label in [
            ("genai_used",        "Criterion 1: GenAI Used"),
            ("relevant_domain",   "Criterion 2: Relevant Assessment Domain"),
            ("quality_assurance", "Criterion 3: Quality Assurance"),
        ]:
            c = crit.get(key, {})
            v = c.get("verdict", "?")
            w(f"\n  {label}", "heading")
            w(f"  Verdict: {v}", vtag.get(v))
            if key == "relevant_domain" and c.get("domains_identified"):
                w(f"  Domains: {', '.join(c['domains_identified'])}")
            if key == "quality_assurance" and c.get("metrics_identified"):
                w(f"  Metrics: {', '.join(c['metrics_identified'])}")
            w(f"  Reasoning: {c.get('reasoning','')}")
            if c.get("text_examples"):
                w(f"  Evidence:  {c['text_examples']}", "key")
            if c.get("location"):
                w(f"  Location:  {c['location']}")

        w("\n  Key Decision Factors", "heading")
        w(f"  {result.get('key_decision_factors','')}")
        if result.get("confidence_rationale"):
            w("\n  Confidence Rationale", "heading")
            w(f"  {result.get('confidence_rationale','')}")
        if result.get("additional_notes"):
            w("\n  Additional Notes", "heading")
            w(f"  {result.get('additional_notes','')}")
        w("\n" + "=" * 68)

        self._result_text.configure(state="normal")
        self._result_text.delete("1.0", "end")
        for text, tag in lines:
            if tag:
                self._result_text.insert("end", text + "\n", tag)
            else:
                self._result_text.insert("end", text + "\n")
        self._result_text.configure(state="disabled")

    # ── Batch actions ─────────────────────────────────────────────────────────

    def _download_batch_template(self):
        dest = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile="batch_papers_template.csv")
        if dest:
            import shutil
            shutil.copy(BATCH_TEMPLATE_CSV, dest)
            messagebox.showinfo("Saved", f"Template saved to:\n{dest}")

    def _select_batch_csv(self):
        path = filedialog.askopenfilename(
            title="Select Batch CSV", filetypes=[("CSV files", "*.csv")])
        if path:
            self._batch_csv_path = path
            self._batch_file_label.config(text=Path(path).name, fg=PALETTE["ink"])
            self._batch_run_btn.config(state="normal")

    def _run_batch_analysis(self):
        if not self._batch_csv_path: return
        if not self._validate_ready(need_pdf=False): return
        self._stop_requested = False
        self._set_busy(True)
        self._batch_log.delete("1.0", "end")
        self._batch_progress["value"] = 0
        self._batch_progress["maximum"] = 1
        self._batch_pct_label.config(text="0%")
        self._batch_counts_label.config(text="")
        self._batch_status.config(text="")
        self._paper_timer_label.config(text="")
        self._batch_total_timer_label.config(text="")
        self._start_batch_timers()
        threading.Thread(target=self._batch_worker, daemon=True).start()

    def _stop_batch(self):
        self._stop_requested = True
        self._batch_stop_btn.config(state="disabled", text="Stopping…")
        self._log_batch("\n⏹ Stop requested — finishing current paper then halting.\n", "info")

    def _batch_worker(self):
        key  = self._api_key.get().strip()
        rows = []
        try:
            for enc in ("utf-8-sig", "latin-1", "cp1252"):
                try:
                    with open(self._batch_csv_path, newline="", encoding=enc) as f:
                        rows = list(csv.DictReader(f))
                    self._log_batch(f"(Encoding: {enc})\n", "info")
                    break
                except UnicodeDecodeError:
                    continue
            else:
                with open(self._batch_csv_path, newline="",
                          encoding="utf-8", errors="replace") as f:
                    rows = list(csv.DictReader(f))
                self._log_batch("(Fallback encoding)\n", "info")
        except Exception as e:
            self._log_batch(f"Could not read CSV: {e}\n", "err")
            self.after(0, self._set_busy, False)
            return

        total = len(rows)
        self._log_batch(f"Loaded {total} papers.\n", "info")
        self.after(0, self._batch_progress.__setitem__, "maximum", total)

        n_included = n_excluded = n_manual = n_error = 0

        for i, row in enumerate(rows):
            if self._stop_requested:
                self._log_batch(f"\n⏹ Batch stopped after {i} of {total} papers.\n", "info")
                break

            pid = row.get("paper_id", f"PAPER_{i+1}").strip()
            url = row.get("url", "").strip()
            fp  = row.get("file_path", "").strip().replace("\\", os.sep).replace("/", os.sep)

            self.after(0, self._batch_status.config, {"text": f"Paper {i+1}/{total}: {pid}"})
            self.after(0, self._new_paper_timer)
            self._log_batch(f"\n[{i+1}/{total}] {pid} — ", "info")

            pdf_bytes = None
            if fp and os.path.isfile(fp):
                with open(fp, "rb") as fh:
                    pdf_bytes = fh.read()
                self._log_batch("loaded from file. ", "ok")
            elif url:
                self._log_batch("fetching URL… ", "info")
                pdf_bytes, err = fetch_pdf_from_url(url)
                if pdf_bytes:
                    self._log_batch("fetched. ", "ok")
                else:
                    self._log_batch(f"FAILED ({err[:40]}). Skipping.\n", "err")
                    n_error += 1
                    self.after(0, self._update_batch_counts,
                               i+1, total, n_included, n_excluded, n_manual, n_error)
                    continue
            else:
                self._log_batch("No source. Skipping.\n", "err")
                n_error += 1
                self.after(0, self._update_batch_counts,
                           i+1, total, n_included, n_excluded, n_manual, n_error)
                continue

            paper_t0 = time.monotonic()
            try:
                self._log_batch("Analyzing… ", "info")
                result = analyze_paper(
                    pdf_bytes, api_key=key,
                    progress_callback=lambda m: self._log_batch(f"[{m}] ", "info"),
                )
                paper_elapsed = time.monotonic() - paper_t0
                rec  = result.get("overall_recommendation", "?")
                rtag = {"INCLUDE":"ok","EXCLUDE":"err","MANUAL_REVIEW":"info"}.get(rec, "info")

                if rec == "INCLUDE":         n_included += 1
                elif rec == "EXCLUDE":       n_excluded += 1
                elif rec == "MANUAL_REVIEW": n_manual   += 1

                c = result.get("criteria", {})
                entry = {
                    "paper_id":           pid,
                    "title":              str(result.get("title") or "").strip(),
                    "authors":            str(result.get("authors") or "").strip(),
                    "publication_year":   str(result.get("publication_year") or "").strip(),
                    "journal_or_venue":   str(result.get("journal_or_venue") or "").strip(),
                    "doi":                str(result.get("doi") or "").strip(),
                    "abstract":           str(result.get("abstract") or "").strip(),
                    "url":                url,
                    "file_path":          fp,
                    "recommendation":     rec,
                    "confidence":         result.get("confidence_level", ""),
                    "genai_used":         c.get("genai_used", {}).get("verdict", ""),
                    "relevant_domain":    c.get("relevant_domain", {}).get("verdict", ""),
                    "quality_assurance":  c.get("quality_assurance", {}).get("verdict", ""),
                    "domains_identified": "; ".join(
                        c.get("relevant_domain", {}).get("domains_identified", [])),
                    "metrics_identified": "; ".join(
                        c.get("quality_assurance", {}).get("metrics_identified", [])),
                    "key_decision_factors": result.get("key_decision_factors", ""),
                    "additional_notes":   result.get("additional_notes", ""),
                    "analyzed_at":        datetime.datetime.now().isoformat(timespec="seconds"),
                    "model_used":         CLAUDE_MODEL,
                    "_full_result":       result,
                }
                save_to_repository(entry)
                self._log_batch(f"→ {rec}  ({self._fmt_elapsed(paper_elapsed)})\n", rtag)

            except InterruptedError:
                self._log_batch("stopped.\n", "info")
                break
            except Exception as e:
                self._log_batch(f"ERROR: {e}\n", "err")
                n_error += 1

            self.after(0, self._update_batch_counts,
                       i+1, total, n_included, n_excluded, n_manual, n_error)

        self._log_batch("\nBatch complete. Repository updated.\n", "ok")
        self.after(0, self._batch_status.config,
                   {"text": (f"Done — {n_included} included, {n_excluded} excluded, "
                              f"{n_manual} manual review, {n_error} errors")})
        self.after(0, self._refresh_repository_tab)
        self.after(0, self._stop_batch_timers)
        self.after(0, self._set_busy, False)

    def _log_batch(self, msg: str, tag: str = ""):
        def _do():
            self._batch_log.insert("end", msg, tag)
            self._batch_log.see("end")
        self.after(0, _do)

    # ── Repository ────────────────────────────────────────────────────────────

    def _refresh_repository_tab(self):
        if not hasattr(self, "_tree"): return
        repo  = load_repository()
        query = self._filter_var.get().lower() if hasattr(self, "_filter_var") else ""
        rec_f = self._rec_filter.get() if hasattr(self, "_rec_filter") else "All"

        # Sort by paper_id ascending (numeric if possible, else lexicographic)
        def _sort_key(r):
            pid = r.get("paper_id", "")
            try:
                return (0, int(pid))
            except (ValueError, TypeError):
                return (1, str(pid))
        repo.sort(key=_sort_key)

        for item in self._tree.get_children():
            self._tree.delete(item)
        for r in repo:
            rec = r.get("recommendation", "")
            if rec_f != "All" and rec != rec_f: continue
            if query and query not in json.dumps(r).lower(): continue
            tag = {"INCLUDE":"include","EXCLUDE":"exclude","MANUAL_REVIEW":"manual"}.get(rec, "")
            ts  = r.get("analyzed_at", "")[:16].replace("T", " ")
            self._tree.insert("", "end", iid=r.get("paper_id"),
                              values=(r.get("paper_id",""), r.get("title",""),
                                      r.get("authors",""), r.get("publication_year",""),
                                      r.get("journal_or_venue",""),
                                      rec, r.get("confidence",""), ts),
                              tags=(tag,))

    def _sort_tree(self, col):
        rows = [(self._tree.set(k, col), k) for k in self._tree.get_children("")]
        rows.sort()
        for i, (_, k) in enumerate(rows):
            self._tree.move(k, "", i)

    def _view_repo_entry(self, _=None):
        sel = self._tree.selection()
        if not sel: return
        repo  = load_repository()
        entry = next((r for r in repo if r.get("paper_id") == sel[0]), None)
        if not entry: return
        win = tk.Toplevel(self)
        win.title(f"Paper Detail — {sel[0]}")
        win.geometry("860x680")
        win.configure(bg=PALETTE["bg"])

        # Header bar
        hdr = tk.Frame(win, bg=PALETTE["brand"], height=48)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text=f"{sel[0]}  ·  {entry.get('title','(no title)')}",
                 bg=PALETTE["brand"], fg=PALETTE["brand_accent"],
                 font=("Helvetica", 10, "bold"), anchor="w",
                 padx=20).pack(fill="both", expand=True)

        # JSON panel
        txt_frame = tk.Frame(win, bg=PALETTE["console_bg"])
        txt_frame.pack(fill="both", expand=True, padx=16, pady=12)
        txt = scrolledtext.ScrolledText(
            txt_frame, font=("Courier New", 9),
            bg=PALETTE["console_bg"], fg=PALETTE["console_fg"],
            bd=0, padx=16, pady=12, wrap="word")
        txt.pack(fill="both", expand=True)
        full    = entry.get("_full_result", {})
        display = full if full else {k: v for k, v in entry.items() if k != "_full_result"}
        txt.insert("end", json.dumps(display, indent=2))
        txt.configure(state="disabled")

    # ── Timer helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _fmt_elapsed(seconds: float) -> str:
        s = int(seconds)
        if s < 3600:
            return f"{s // 60}:{s % 60:02d}"
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"

    def _start_single_timer(self):
        self._single_start_time = time.monotonic()
        self._single_pbar.start(12)
        self._tick_single()

    def _tick_single(self):
        if not self._busy or self._single_start_time is None:
            return
        elapsed = time.monotonic() - self._single_start_time
        self._single_timer_label.config(text=f"⏱ {self._fmt_elapsed(elapsed)}")
        self._timer_after_id = self.after(1000, self._tick_single)

    def _stop_single_timer(self, final_elapsed=None):
        # Always cancel the scheduled tick first
        if self._timer_after_id:
            self.after_cancel(self._timer_after_id)
            self._timer_after_id = None
        self._single_pbar.stop()
        self._single_start_time = None
        # Show final time on success, dash on error — never crashes
        if final_elapsed is not None:
            self._single_timer_label.config(text=f"✓ {self._fmt_elapsed(final_elapsed)}")
        else:
            self._single_timer_label.config(text="—")

    def _start_batch_timers(self):
        self._batch_start_time = time.monotonic()
        self._paper_start_time = time.monotonic()
        self._tick_batch()

    def _new_paper_timer(self):
        self._paper_start_time = time.monotonic()

    def _tick_batch(self):
        if not self._busy:
            return
        now = time.monotonic()
        if self._paper_start_time:
            self._paper_timer_label.config(
                text=f"Paper: {self._fmt_elapsed(now - self._paper_start_time)}")
        if self._batch_start_time:
            self._batch_total_timer_label.config(
                text=f"Total: {self._fmt_elapsed(now - self._batch_start_time)}")
        self._timer_after_id = self.after(1000, self._tick_batch)

    def _stop_batch_timers(self):
        if self._timer_after_id:
            self.after_cancel(self._timer_after_id)
            self._timer_after_id = None
        if self._batch_start_time:
            total_e = time.monotonic() - self._batch_start_time
            self._batch_total_timer_label.config(
                text=f"Done: {self._fmt_elapsed(total_e)}")
        self._batch_start_time  = None
        self._paper_start_time  = None
        self._paper_timer_label.config(text="")

    def _update_batch_counts(self, done, total, included, excluded, manual, errors):
        pct = int(done / total * 100) if total else 0
        self._batch_progress["value"] = done
        self._batch_pct_label.config(text=f"{pct}%")
        self._batch_counts_label.config(
            text=(f"{done}/{total} papers  ·  "
                  f"Include: {included}  Exclude: {excluded}  "
                  f"Manual Review: {manual}  Errors: {errors}"))

    # ── Validation & state ────────────────────────────────────────────────────

    def _validate_ready(self, need_pdf=True):
        if not self._api_key.get().strip():
            messagebox.showwarning("API Key Required",
                                   "Please enter your Anthropic API key in the Settings tab.")
            self.notebook.select(self.tab_config)
            return False
        if need_pdf and not self._current_pdf_bytes:
            messagebox.showwarning("No PDF", "Please fetch or upload a PDF first.")
            return False
        return True

    def _set_busy(self, busy: bool):
        self._busy = busy
        self._analyze_btn.config(state="disabled" if busy else "normal")
        self._batch_run_btn.config(
            state="disabled" if busy else ("normal" if self._batch_csv_path else "disabled"))
        self._batch_stop_btn.config(
            state="normal" if busy else "disabled",
            text="⏹  Stop")

    def _set_progress(self, msg: str):
        self._progress_label.config(text=msg)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = PaperScreenerApp()
    app.mainloop()
