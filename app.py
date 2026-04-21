"""
GenAI Evidence Hub — Paper Screening Tool
Screens papers for inclusion/exclusion in the systematic literature review
based on the GenAI Evidence Hub criteria.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import json
import csv
import os
import datetime
import base64
import requests
import pdfplumber
import anthropic
from pathlib import Path
import io
import re

# ── Constants ────────────────────────────────────────────────────────────────

APP_TITLE = "GenAI Evidence Hub — Paper Screener"
REPO_DIR = Path.home() / "genai_evidence_hub"
REPO_JSON = REPO_DIR / "paper_repository.json"
REPO_CSV = REPO_DIR / "paper_repository.csv"
BATCH_TEMPLATE_CSV = REPO_DIR / "batch_template.csv"

PALETTE = {
    "navy":       "#1B2A4A",
    "navy_mid":   "#243560",
    "teal":       "#2A7F8F",
    "teal_light": "#3BA3B5",
    "amber":      "#E8A020",
    "amber_light":"#F5C050",
    "white":      "#F4F6FA",
    "grey_light": "#E2E8F0",
    "grey_mid":   "#94A3B8",
    "grey_dark":  "#475569",
    "green":      "#22875A",
    "red":        "#C0392B",
    "orange":     "#D4750A",
    "bg":         "#F0F4FA",
}

SYSTEM_PROMPT = """You are a systematic literature review screener for the GenAI Evidence Hub, 
a research initiative at the University of Pennsylvania examining generative AI in educational 
assessment contexts. Your job is to evaluate whether a research paper meets the inclusion criteria 
for this meta-analysis.

You must evaluate each paper against ALL THREE criteria and provide a structured JSON response.

## Inclusion Criteria

### Criterion 1: GenAI Used
Paper describes research using Generative AI.
- Research must have been conducted after 2020 (release of OpenAI GPT)
- Paper references a Generative AI application (e.g., OpenAI GPT, Claude, DeepSeek, Gemini, LLaMA, etc.)
- May include ensemble models that combine multiple approaches
- EXCLUDE: papers that use only traditional ML approaches (KNN, Random Forest, etc.) without a GenAI/LLM component

### Criterion 2: Relevant Assessment Domain
Research must focus on one or more of these educational assessment domains:
- **Item Generation**: Creation of assessment items (forced choice, problem-based, simulations, etc.)
- **Formative Feedback**: Real-time feedback to students to improve knowledge/skills/abilities
- **Automated Item Scoring**: AI scoring of complex student work (essays, short answer, simulations) typically scored by humans
- **Multimodal (Audio/Video) Inferences**: Assessment using audio/video data in classroom contexts
- Educational/tutoring context required. Socioemotional skill teaching is OK.
- EXCLUDE: papers that only address fairness approaches without any evaluation

### Criterion 3: Quality Assurance
Paper describes model creation and evaluation methods in sufficient detail.
Acceptable metrics include (but not limited to):
- Precision, recall, F1 values with comparison groups
- Accuracy compared to established benchmarks
- Inter-rater reliability (human vs. AI)
- Kappa, AUROC
- GLEU, BLEU, ROUGE
- EXCLUDE: papers without thorough descriptions of evaluation methods

## Decision Rules
- INCLUDE: All three criteria met (YES/YES/YES)
- EXCLUDE: Any criterion not met, paper not in English, paper older than 2022
- MANUAL_REVIEW: Borderline cases, unclear evidence, partial satisfaction, conflicting information

## Required Output Format
Respond ONLY with valid JSON in this exact structure:
{
  "overall_recommendation": "INCLUDE" | "EXCLUDE" | "MANUAL_REVIEW",
  "criteria": {
    "genai_used": {
      "verdict": "YES" | "NO" | "UNCLEAR",
      "reasoning": "Detailed explanation",
      "text_examples": "Direct quotes or paraphrases from the paper",
      "location": "Page/section references where possible"
    },
    "relevant_domain": {
      "verdict": "YES" | "NO" | "UNCLEAR",
      "domains_identified": ["list of matching domains"],
      "reasoning": "Detailed explanation",
      "text_examples": "Direct quotes or paraphrases from the paper",
      "location": "Page/section references where possible"
    },
    "quality_assurance": {
      "verdict": "YES" | "NO" | "UNCLEAR",
      "metrics_identified": ["list of metrics found"],
      "reasoning": "Detailed explanation",
      "text_examples": "Direct quotes or paraphrases from the paper",
      "location": "Page/section references where possible"
    }
  },
  "confidence_level": "High" | "Medium" | "Low",
  "confidence_rationale": "Explanation of confidence level",
  "key_decision_factors": "Most important elements that led to the decision",
  "additional_notes": "Any relevant observations, edge cases, or recommendations for human reviewers"
}"""

CSV_COLUMNS = [
    "paper_id", "title", "authors", "year", "url", "file_path",
    "recommendation", "confidence", "genai_used", "relevant_domain",
    "quality_assurance", "domains_identified", "metrics_identified",
    "key_decision_factors", "additional_notes", "analyzed_at", "full_json_path"
]

BATCH_CSV_COLUMNS = ["paper_id", "title", "authors", "year", "url", "file_path"]


# ── Repository ────────────────────────────────────────────────────────────────

def ensure_repo():
    REPO_DIR.mkdir(parents=True, exist_ok=True)
    if not REPO_JSON.exists():
        REPO_JSON.write_text(json.dumps([], indent=2))
    if not REPO_CSV.exists():
        with open(REPO_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()
    # Write batch template
    if not BATCH_TEMPLATE_CSV.exists():
        with open(BATCH_TEMPLATE_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=BATCH_CSV_COLUMNS)
            writer.writeheader()
            writer.writerow({
                "paper_id": "PAPER_001",
                "title": "Example Paper Title",
                "authors": "Smith, J.; Jones, A.",
                "year": "2024",
                "url": "https://example.com/paper.pdf",
                "file_path": ""
            })


def load_repository():
    ensure_repo()
    try:
        return json.loads(REPO_JSON.read_text())
    except Exception:
        return []


def save_to_repository(entry: dict):
    ensure_repo()
    repo = load_repository()

    # Update if paper_id already exists
    for i, r in enumerate(repo):
        if r.get("paper_id") == entry.get("paper_id"):
            repo[i] = entry
            break
    else:
        repo.append(entry)

    REPO_JSON.write_text(json.dumps(repo, indent=2))
    _sync_csv(repo)


def _sync_csv(repo: list):
    """Rebuild the CSV from the JSON repository."""
    with open(REPO_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in repo:
            writer.writerow(r)


# ── PDF / URL fetching ────────────────────────────────────────────────────────

def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using pdfplumber."""
    text_parts = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for i, page in enumerate(pdf.pages):
            t = page.extract_text()
            if t:
                text_parts.append(f"[Page {i+1}]\n{t}")
    return "\n\n".join(text_parts)


def fetch_pdf_from_url(url: str) -> tuple[bytes | None, str]:
    """Try to fetch a PDF from a URL. Returns (bytes, error_msg)."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; GenAI Evidence Hub Screener)"
        }
        resp = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "pdf" in content_type or url.lower().endswith(".pdf"):
            return resp.content, ""
        # Try anyway if the content looks like a PDF
        if resp.content[:4] == b"%PDF":
            return resp.content, ""
        return None, f"URL did not return a PDF (content-type: {content_type})"
    except requests.exceptions.RequestException as e:
        return None, str(e)


# ── Claude API analysis ───────────────────────────────────────────────────────

def analyze_paper_with_claude(pdf_bytes: bytes, api_key: str,
                               progress_callback=None) -> dict:
    """Send PDF to Claude for analysis. Returns parsed result dict."""
    client = anthropic.Anthropic(api_key=api_key)

    if progress_callback:
        progress_callback("Sending paper to Claude for analysis…")

    # Encode PDF as base64
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {
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
                            "Please evaluate this paper against the GenAI Evidence Hub "
                            "inclusion criteria. Review the full paper carefully before "
                            "responding. Return ONLY valid JSON — no markdown, no preamble."
                        ),
                    },
                ],
            }
        ],
    )

    raw = response.content[0].text.strip()
    # Strip markdown fences if present
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    return json.loads(raw)


# ── GUI ───────────────────────────────────────────────────────────────────────

class PaperScreenerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1100x780")
        self.minsize(900, 650)
        self.configure(bg=PALETTE["bg"])

        ensure_repo()
        self._api_key = tk.StringVar()
        self._current_pdf_bytes: bytes | None = None
        self._busy = False

        self._build_ui()
        self._refresh_repository_tab()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        self._style_notebook()

        self.tab_single = tk.Frame(self.notebook, bg=PALETTE["bg"])
        self.tab_batch  = tk.Frame(self.notebook, bg=PALETTE["bg"])
        self.tab_repo   = tk.Frame(self.notebook, bg=PALETTE["bg"])
        self.tab_config = tk.Frame(self.notebook, bg=PALETTE["bg"])

        self.notebook.add(self.tab_single, text="  Single Paper  ")
        self.notebook.add(self.tab_batch,  text="  Batch Upload  ")
        self.notebook.add(self.tab_repo,   text="  Repository  ")
        self.notebook.add(self.tab_config, text="  Settings  ")

        self._build_single_tab()
        self._build_batch_tab()
        self._build_repo_tab()
        self._build_config_tab()

    def _build_header(self):
        hdr = tk.Frame(self, bg=PALETTE["navy"], height=64)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        tk.Label(
            hdr,
            text="GenAI Evidence Hub",
            font=("Georgia", 18, "bold"),
            fg=PALETTE["amber"],
            bg=PALETTE["navy"],
        ).pack(side="left", padx=20, pady=12)

        tk.Label(
            hdr,
            text="Paper Screening Tool  |  University of Pennsylvania · LDI",
            font=("Georgia", 10),
            fg=PALETTE["grey_light"],
            bg=PALETTE["navy"],
        ).pack(side="left", padx=0, pady=18)

    def _style_notebook(self):
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure(
            "TNotebook", background=PALETTE["bg"], borderwidth=0
        )
        style.configure(
            "TNotebook.Tab",
            background=PALETTE["grey_light"],
            foreground=PALETTE["navy"],
            padding=[12, 6],
            font=("Helvetica", 10, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", PALETTE["navy"])],
            foreground=[("selected", PALETTE["amber"])],
        )

    # ── Single Paper Tab ──────────────────────────────────────────────────────

    def _build_single_tab(self):
        pad = {"padx": 16, "pady": 8}
        f = self.tab_single

        # ── Paper metadata ──
        meta = tk.LabelFrame(f, text=" Paper Information ", bg=PALETTE["bg"],
                             fg=PALETTE["navy"], font=("Helvetica", 10, "bold"),
                             bd=1, relief="groove")
        meta.pack(fill="x", **pad)

        grid = tk.Frame(meta, bg=PALETTE["bg"])
        grid.pack(fill="x", padx=12, pady=8)

        labels = ["Paper ID *", "Title", "Authors", "Year"]
        self._meta_vars = {}
        for i, lbl in enumerate(labels):
            tk.Label(grid, text=lbl, bg=PALETTE["bg"], fg=PALETTE["grey_dark"],
                     font=("Helvetica", 9)).grid(row=i, column=0, sticky="w", pady=3)
            var = tk.StringVar()
            self._meta_vars[lbl] = var
            e = tk.Entry(grid, textvariable=var, width=60,
                         font=("Helvetica", 10), bd=1, relief="solid")
            e.grid(row=i, column=1, sticky="ew", padx=(8, 0), pady=3)
        grid.columnconfigure(1, weight=1)

        # ── Source ──
        src = tk.LabelFrame(f, text=" Paper Source ", bg=PALETTE["bg"],
                            fg=PALETTE["navy"], font=("Helvetica", 10, "bold"),
                            bd=1, relief="groove")
        src.pack(fill="x", **pad)

        src_inner = tk.Frame(src, bg=PALETTE["bg"])
        src_inner.pack(fill="x", padx=12, pady=8)

        # URL row
        url_row = tk.Frame(src_inner, bg=PALETTE["bg"])
        url_row.pack(fill="x", pady=3)
        tk.Label(url_row, text="URL:", bg=PALETTE["bg"], fg=PALETTE["grey_dark"],
                 width=10, anchor="w", font=("Helvetica", 9)).pack(side="left")
        self._url_var = tk.StringVar()
        tk.Entry(url_row, textvariable=self._url_var, font=("Helvetica", 10),
                 bd=1, relief="solid").pack(side="left", fill="x", expand=True, padx=(4, 8))
        tk.Button(url_row, text="Fetch PDF", command=self._fetch_url,
                  bg=PALETTE["teal"], fg="white", font=("Helvetica", 9, "bold"),
                  relief="flat", padx=10).pack(side="left")

        # Or upload
        upload_row = tk.Frame(src_inner, bg=PALETTE["bg"])
        upload_row.pack(fill="x", pady=3)
        tk.Label(upload_row, text="— or —", bg=PALETTE["bg"], fg=PALETTE["grey_mid"],
                 font=("Helvetica", 9, "italic")).pack(side="left", padx=8)
        tk.Button(upload_row, text="📂  Upload PDF", command=self._upload_pdf,
                  bg=PALETTE["navy_mid"], fg="white", font=("Helvetica", 9, "bold"),
                  relief="flat", padx=12).pack(side="left")
        self._file_label = tk.Label(upload_row, text="No file selected",
                                    bg=PALETTE["bg"], fg=PALETTE["grey_mid"],
                                    font=("Helvetica", 9, "italic"))
        self._file_label.pack(side="left", padx=8)

        # Analyze button
        btn_row = tk.Frame(f, bg=PALETTE["bg"])
        btn_row.pack(fill="x", padx=16, pady=4)
        self._analyze_btn = tk.Button(
            btn_row, text="▶  Analyze Paper",
            command=self._run_single_analysis,
            bg=PALETTE["amber"], fg=PALETTE["navy"],
            font=("Helvetica", 11, "bold"), relief="flat", padx=20, pady=8,
            cursor="hand2"
        )
        self._analyze_btn.pack(side="left")
        self._progress_label = tk.Label(btn_row, text="", bg=PALETTE["bg"],
                                        fg=PALETTE["teal"], font=("Helvetica", 9, "italic"))
        self._progress_label.pack(side="left", padx=12)

        # Results
        res = tk.LabelFrame(f, text=" Analysis Results ", bg=PALETTE["bg"],
                            fg=PALETTE["navy"], font=("Helvetica", 10, "bold"),
                            bd=1, relief="groove")
        res.pack(fill="both", expand=True, **pad)

        self._result_text = scrolledtext.ScrolledText(
            res, font=("Courier", 9), bg="#1e2636", fg="#c8d8f0",
            insertbackground="white", bd=0, padx=10, pady=8,
            wrap="word"
        )
        self._result_text.pack(fill="both", expand=True, padx=8, pady=8)
        self._result_text.insert("1.0", "Results will appear here after analysis…")
        self._result_text.configure(state="disabled")

        # Tag colors for result display
        self._result_text.tag_config("include",  foreground="#5BE8A0")
        self._result_text.tag_config("exclude",  foreground="#FF7B7B")
        self._result_text.tag_config("manual",   foreground="#FFD166")
        self._result_text.tag_config("heading",  foreground=PALETTE["amber_light"],
                                     font=("Courier", 10, "bold"))
        self._result_text.tag_config("key",      foreground="#94D8F0")
        self._result_text.tag_config("yes",      foreground="#5BE8A0")
        self._result_text.tag_config("no",       foreground="#FF7B7B")
        self._result_text.tag_config("unclear",  foreground="#FFD166")

    # ── Batch Tab ─────────────────────────────────────────────────────────────

    def _build_batch_tab(self):
        f = self.tab_batch
        pad = {"padx": 16, "pady": 10}

        info = tk.LabelFrame(f, text=" Batch Upload Instructions ", bg=PALETTE["bg"],
                             fg=PALETTE["navy"], font=("Helvetica", 10, "bold"),
                             bd=1, relief="groove")
        info.pack(fill="x", **pad)

        instructions = (
            "Upload a CSV file with one paper per row. Required column: paper_id. "
            "Optional columns: title, authors, year, url, file_path.\n"
            "• url — will be fetched automatically (PDF direct links work best)\n"
            "• file_path — local path to a PDF file\n"
            "• If both url and file_path are provided, file_path takes priority\n"
            "• Columns can appear in any order; extra columns are preserved as metadata"
        )
        tk.Label(info, text=instructions, bg=PALETTE["bg"], fg=PALETTE["grey_dark"],
                 font=("Helvetica", 9), justify="left", wraplength=820).pack(
            padx=12, pady=8, anchor="w")

        tk.Button(info, text="⬇  Download CSV Template",
                  command=self._download_batch_template,
                  bg=PALETTE["teal"], fg="white",
                  font=("Helvetica", 9, "bold"), relief="flat", padx=10
                  ).pack(padx=12, pady=(0, 8), anchor="w")

        # Upload button
        ctrl = tk.Frame(f, bg=PALETTE["bg"])
        ctrl.pack(fill="x", **pad)
        tk.Button(ctrl, text="📂  Select Batch CSV",
                  command=self._select_batch_csv,
                  bg=PALETTE["navy_mid"], fg="white",
                  font=("Helvetica", 10, "bold"), relief="flat", padx=12, pady=6
                  ).pack(side="left")
        self._batch_file_label = tk.Label(ctrl, text="No file selected",
                                          bg=PALETTE["bg"], fg=PALETTE["grey_mid"],
                                          font=("Helvetica", 9, "italic"))
        self._batch_file_label.pack(side="left", padx=10)

        self._batch_run_btn = tk.Button(
            ctrl, text="▶  Run Batch Analysis",
            command=self._run_batch_analysis,
            bg=PALETTE["amber"], fg=PALETTE["navy"],
            font=("Helvetica", 10, "bold"), relief="flat", padx=16, pady=6,
            cursor="hand2", state="disabled"
        )
        self._batch_run_btn.pack(side="right")

        # Progress
        prog_frame = tk.Frame(f, bg=PALETTE["bg"])
        prog_frame.pack(fill="x", padx=16)
        self._batch_progress = ttk.Progressbar(prog_frame, mode="determinate")
        self._batch_progress.pack(fill="x", pady=4)
        self._batch_status = tk.Label(prog_frame, text="", bg=PALETTE["bg"],
                                      fg=PALETTE["teal"], font=("Helvetica", 9, "italic"))
        self._batch_status.pack(anchor="w")

        # Log
        log_frame = tk.LabelFrame(f, text=" Batch Log ", bg=PALETTE["bg"],
                                  fg=PALETTE["navy"], font=("Helvetica", 10, "bold"),
                                  bd=1, relief="groove")
        log_frame.pack(fill="both", expand=True, **pad)
        self._batch_log = scrolledtext.ScrolledText(
            log_frame, font=("Courier", 9), bg="#1e2636", fg="#c8d8f0",
            bd=0, padx=10, pady=8, wrap="word"
        )
        self._batch_log.pack(fill="both", expand=True, padx=8, pady=8)
        self._batch_log.tag_config("ok",   foreground="#5BE8A0")
        self._batch_log.tag_config("err",  foreground="#FF7B7B")
        self._batch_log.tag_config("info", foreground="#FFD166")

        self._batch_csv_path: str | None = None

    # ── Repository Tab ────────────────────────────────────────────────────────

    def _build_repo_tab(self):
        f = self.tab_repo
        pad = {"padx": 16, "pady": 8}

        ctrl = tk.Frame(f, bg=PALETTE["bg"])
        ctrl.pack(fill="x", **pad)

        tk.Button(ctrl, text="🔄  Refresh", command=self._refresh_repository_tab,
                  bg=PALETTE["teal"], fg="white", font=("Helvetica", 9, "bold"),
                  relief="flat", padx=10).pack(side="left")
        tk.Button(ctrl, text="📂  Open Repository Folder",
                  command=lambda: os.startfile(REPO_DIR) if os.name == "nt"
                  else os.system(f'open "{REPO_DIR}"'),
                  bg=PALETTE["navy_mid"], fg="white", font=("Helvetica", 9, "bold"),
                  relief="flat", padx=10).pack(side="left", padx=8)

        # Filter bar
        filter_frame = tk.Frame(ctrl, bg=PALETTE["bg"])
        filter_frame.pack(side="right")
        tk.Label(filter_frame, text="Filter:", bg=PALETTE["bg"],
                 fg=PALETTE["grey_dark"], font=("Helvetica", 9)).pack(side="left")
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._refresh_repository_tab())
        tk.Entry(filter_frame, textvariable=self._filter_var, width=20,
                 font=("Helvetica", 9), bd=1, relief="solid").pack(side="left", padx=4)

        self._rec_filter = tk.StringVar(value="All")
        for val in ["All", "INCLUDE", "EXCLUDE", "MANUAL_REVIEW"]:
            color = {"All": PALETTE["grey_mid"], "INCLUDE": PALETTE["green"],
                     "EXCLUDE": PALETTE["red"], "MANUAL_REVIEW": PALETTE["orange"]}.get(val, PALETTE["grey_mid"])
            rb = tk.Radiobutton(filter_frame, text=val, variable=self._rec_filter,
                                value=val, command=self._refresh_repository_tab,
                                bg=PALETTE["bg"], fg=color, activebackground=PALETTE["bg"],
                                font=("Helvetica", 9, "bold"), selectcolor=PALETTE["bg"])
            rb.pack(side="left", padx=4)

        # Treeview
        cols = ("paper_id", "title", "year", "recommendation", "confidence", "analyzed_at")
        col_widths = (100, 320, 50, 120, 80, 130)

        tree_frame = tk.Frame(f, bg=PALETTE["bg"])
        tree_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        style = ttk.Style()
        style.configure("Repo.Treeview", rowheight=26, font=("Helvetica", 9),
                        background=PALETTE["white"], fieldbackground=PALETTE["white"],
                        foreground=PALETTE["navy"])
        style.configure("Repo.Treeview.Heading", font=("Helvetica", 9, "bold"),
                        background=PALETTE["navy"], foreground="white")

        self._tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                  style="Repo.Treeview", selectmode="browse")
        for col, w in zip(cols, col_widths):
            self._tree.heading(col, text=col.replace("_", " ").title(),
                               command=lambda c=col: self._sort_tree(c))
            self._tree.column(col, width=w, anchor="w")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self._tree.tag_configure("include", background="#EAF9F1")
        self._tree.tag_configure("exclude", background="#FDF0EF")
        self._tree.tag_configure("manual",  background="#FEF9EC")

        self._tree.bind("<Double-1>", self._view_repo_entry)

        tk.Label(f, text="Double-click a row to view full analysis",
                 bg=PALETTE["bg"], fg=PALETTE["grey_mid"],
                 font=("Helvetica", 8, "italic")).pack(pady=2)

    # ── Config Tab ────────────────────────────────────────────────────────────

    def _build_config_tab(self):
        f = self.tab_config
        pad = {"padx": 20, "pady": 10}

        tk.Label(f, text="Anthropic API Key", bg=PALETTE["bg"],
                 fg=PALETTE["navy"], font=("Helvetica", 11, "bold")).pack(anchor="w", **pad)

        key_frame = tk.Frame(f, bg=PALETTE["bg"])
        key_frame.pack(fill="x", padx=20)
        self._key_entry = tk.Entry(key_frame, textvariable=self._api_key,
                                   font=("Courier", 10), show="•", width=60,
                                   bd=1, relief="solid")
        self._key_entry.pack(side="left", fill="x", expand=True)
        tk.Button(key_frame, text="Show/Hide",
                  command=self._toggle_key_vis,
                  bg=PALETTE["grey_light"], fg=PALETTE["navy"],
                  font=("Helvetica", 9), relief="flat", padx=8
                  ).pack(side="left", padx=6)

        tk.Label(f, text="The API key is stored only in memory for this session and is never saved to disk.",
                 bg=PALETTE["bg"], fg=PALETTE["grey_mid"],
                 font=("Helvetica", 8, "italic")).pack(anchor="w", padx=20, pady=4)

        # Repository info
        sep = tk.Frame(f, bg=PALETTE["grey_light"], height=1)
        sep.pack(fill="x", padx=20, pady=16)

        tk.Label(f, text="Repository Location", bg=PALETTE["bg"],
                 fg=PALETTE["navy"], font=("Helvetica", 11, "bold")).pack(anchor="w", padx=20)
        tk.Label(f, text=str(REPO_DIR), bg=PALETTE["bg"], fg=PALETTE["teal"],
                 font=("Courier", 9)).pack(anchor="w", padx=20, pady=4)
        tk.Label(f, text="Files saved: paper_repository.json (full data) · paper_repository.csv (spreadsheet view)",
                 bg=PALETTE["bg"], fg=PALETTE["grey_mid"],
                 font=("Helvetica", 8, "italic")).pack(anchor="w", padx=20)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _toggle_key_vis(self):
        self._key_entry.config(
            show="" if self._key_entry.cget("show") == "•" else "•"
        )

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
                self._file_label.config(
                    text=f"✓ Fetched from URL ({len(pdf_bytes)//1024} KB)",
                    fg=PALETTE["green"])
                self._set_progress("PDF fetched successfully.")
            else:
                self._current_pdf_bytes = None
                self._file_label.config(
                    text=f"✗ Could not fetch: {err[:60]}",
                    fg=PALETTE["red"])
                self._set_progress(f"Fetch failed — please upload PDF manually.")
                messagebox.showwarning(
                    "Fetch Failed",
                    f"Could not retrieve PDF from URL:\n{err}\n\n"
                    "Please upload the PDF file manually."
                )
            self._set_busy(False)
        threading.Thread(target=_do, daemon=True).start()

    def _upload_pdf(self):
        path = filedialog.askopenfilename(
            title="Select PDF", filetypes=[("PDF files", "*.pdf")]
        )
        if path:
            with open(path, "rb") as fh:
                self._current_pdf_bytes = fh.read()
            name = Path(path).name
            self._file_label.config(
                text=f"✓ {name} ({len(self._current_pdf_bytes)//1024} KB)",
                fg=PALETTE["green"]
            )
            self._set_progress(f"PDF loaded: {name}")

    def _run_single_analysis(self):
        if not self._validate_ready():
            return
        paper_id = self._meta_vars["Paper ID *"].get().strip()
        if not paper_id:
            messagebox.showwarning("Missing ID", "Please enter a Paper ID.")
            return
        self._set_busy(True)
        self._set_progress("Starting analysis…")
        threading.Thread(target=self._analysis_worker,
                         args=(paper_id,), daemon=True).start()

    def _analysis_worker(self, paper_id: str):
        try:
            result = analyze_paper_with_claude(
                self._current_pdf_bytes,
                self._api_key.get().strip(),
                progress_callback=self._set_progress
            )
            entry = self._build_repo_entry(paper_id, result)
            save_to_repository(entry)
            self.after(0, self._display_result, result, paper_id)
            self.after(0, self._refresh_repository_tab)
            self.after(0, self._set_progress, "✓ Analysis complete — saved to repository.")
        except json.JSONDecodeError as e:
            self.after(0, messagebox.showerror, "Parse Error",
                       f"Claude returned non-JSON output:\n{e}")
            self.after(0, self._set_progress, "Analysis failed.")
        except Exception as e:
            self.after(0, messagebox.showerror, "Error", str(e))
            self.after(0, self._set_progress, "Analysis failed.")
        finally:
            self.after(0, self._set_busy, False)

    def _build_repo_entry(self, paper_id: str, result: dict) -> dict:
        criteria = result.get("criteria", {})
        genai    = criteria.get("genai_used", {})
        domain   = criteria.get("relevant_domain", {})
        qa       = criteria.get("quality_assurance", {})
        return {
            "paper_id":           paper_id,
            "title":              self._meta_vars["Title"].get().strip(),
            "authors":            self._meta_vars["Authors"].get().strip(),
            "year":               self._meta_vars["Year"].get().strip(),
            "url":                self._url_var.get().strip(),
            "file_path":          "",
            "recommendation":     result.get("overall_recommendation", ""),
            "confidence":         result.get("confidence_level", ""),
            "genai_used":         genai.get("verdict", ""),
            "relevant_domain":    domain.get("verdict", ""),
            "quality_assurance":  qa.get("verdict", ""),
            "domains_identified": "; ".join(domain.get("domains_identified", [])),
            "metrics_identified": "; ".join(qa.get("metrics_identified", [])),
            "key_decision_factors": result.get("key_decision_factors", ""),
            "additional_notes":   result.get("additional_notes", ""),
            "analyzed_at":        datetime.datetime.now().isoformat(timespec="seconds"),
            "full_json_path":     "",
            "_full_result":       result,
        }

    def _display_result(self, result: dict, paper_id: str):
        rec  = result.get("overall_recommendation", "?")
        conf = result.get("confidence_level", "?")
        crit = result.get("criteria", {})

        rec_tag = {"INCLUDE": "include", "EXCLUDE": "exclude",
                   "MANUAL_REVIEW": "manual"}.get(rec, "")
        verdict_tag = {"YES": "yes", "NO": "no", "UNCLEAR": "unclear"}

        lines = []
        def w(text, tag=None):
            lines.append((text, tag))

        w("━" * 70)
        w(f"  PAPER: {paper_id}", "heading")
        w(f"  RECOMMENDATION:  {rec}", rec_tag)
        w(f"  CONFIDENCE:      {conf}")
        w("━" * 70)

        for key, label in [
            ("genai_used",        "Criterion 1: GenAI Used"),
            ("relevant_domain",   "Criterion 2: Relevant Assessment Domain"),
            ("quality_assurance", "Criterion 3: Quality Assurance"),
        ]:
            c = crit.get(key, {})
            v = c.get("verdict", "?")
            w(f"\n▸ {label}", "heading")
            w(f"  Verdict: {v}", verdict_tag.get(v))
            if key == "relevant_domain" and c.get("domains_identified"):
                w(f"  Domains: {', '.join(c['domains_identified'])}")
            if key == "quality_assurance" and c.get("metrics_identified"):
                w(f"  Metrics: {', '.join(c['metrics_identified'])}")
            w(f"  Reasoning: {c.get('reasoning','')}")
            if c.get("text_examples"):
                w(f"  Evidence:  {c['text_examples']}", "key")
            if c.get("location"):
                w(f"  Location:  {c['location']}")

        w("\n▸ Key Decision Factors", "heading")
        w(f"  {result.get('key_decision_factors','')}")
        if result.get("confidence_rationale"):
            w(f"\n▸ Confidence Rationale", "heading")
            w(f"  {result.get('confidence_rationale','')}")
        if result.get("additional_notes"):
            w(f"\n▸ Additional Notes", "heading")
            w(f"  {result.get('additional_notes','')}")
        w("\n" + "━" * 70)

        self._result_text.configure(state="normal")
        self._result_text.delete("1.0", "end")
        for text, tag in lines:
            if tag:
                self._result_text.insert("end", text + "\n", tag)
            else:
                self._result_text.insert("end", text + "\n")
        self._result_text.configure(state="disabled")

    # ── Batch ─────────────────────────────────────────────────────────────────

    def _download_batch_template(self):
        dest = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile="batch_papers_template.csv"
        )
        if dest:
            import shutil
            shutil.copy(BATCH_TEMPLATE_CSV, dest)
            messagebox.showinfo("Template Saved", f"Template saved to:\n{dest}")

    def _select_batch_csv(self):
        path = filedialog.askopenfilename(
            title="Select Batch CSV", filetypes=[("CSV files", "*.csv")]
        )
        if path:
            self._batch_csv_path = path
            self._batch_file_label.config(
                text=Path(path).name, fg=PALETTE["navy"]
            )
            self._batch_run_btn.config(state="normal")

    def _run_batch_analysis(self):
        if not self._batch_csv_path:
            return
        if not self._validate_ready():
            return
        self._set_busy(True)
        self._batch_log.delete("1.0", "end")
        threading.Thread(target=self._batch_worker, daemon=True).start()

    def _batch_worker(self):
        try:
            rows = []
            with open(self._batch_csv_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            total = len(rows)
            self.after(0, self._batch_log.insert, "end",
                       f"Loaded {total} papers from CSV.\n", "info")
            self._batch_progress["maximum"] = total

            for i, row in enumerate(rows):
                paper_id  = row.get("paper_id", f"PAPER_{i+1}").strip()
                url       = row.get("url", "").strip()
                file_path = row.get("file_path", "").strip()

                self.after(0, self._batch_log.insert, "end",
                           f"\n[{i+1}/{total}] {paper_id} — ", "info")

                pdf_bytes = None

                # Try local file first
                if file_path and os.path.isfile(file_path):
                    with open(file_path, "rb") as fh:
                        pdf_bytes = fh.read()
                    self.after(0, self._batch_log.insert, "end",
                               "loaded from file. ", "ok")
                elif url:
                    self.after(0, self._batch_log.insert, "end",
                               "fetching from URL… ", "info")
                    pdf_bytes, err = fetch_pdf_from_url(url)
                    if pdf_bytes:
                        self.after(0, self._batch_log.insert, "end",
                                   "fetched. ", "ok")
                    else:
                        self.after(0, self._batch_log.insert, "end",
                                   f"FETCH FAILED ({err[:40]}). Skipping.\n", "err")
                        self.after(0, self._batch_progress.__setitem__, "value", i+1)
                        continue
                else:
                    self.after(0, self._batch_log.insert, "end",
                               "No source found. Skipping.\n", "err")
                    self.after(0, self._batch_progress.__setitem__, "value", i+1)
                    continue

                try:
                    self.after(0, self._batch_log.insert, "end", "Analyzing… ", "info")
                    result = analyze_paper_with_claude(
                        pdf_bytes, self._api_key.get().strip()
                    )
                    rec = result.get("overall_recommendation", "?")
                    rec_tag = {"INCLUDE": "ok", "EXCLUDE": "err",
                               "MANUAL_REVIEW": "info"}.get(rec, "info")

                    entry = {
                        "paper_id":    paper_id,
                        "title":       row.get("title", ""),
                        "authors":     row.get("authors", ""),
                        "year":        row.get("year", ""),
                        "url":         url,
                        "file_path":   file_path,
                        "recommendation": rec,
                        "confidence":  result.get("confidence_level", ""),
                        "genai_used":  result.get("criteria", {}).get("genai_used", {}).get("verdict", ""),
                        "relevant_domain": result.get("criteria", {}).get("relevant_domain", {}).get("verdict", ""),
                        "quality_assurance": result.get("criteria", {}).get("quality_assurance", {}).get("verdict", ""),
                        "domains_identified": "; ".join(
                            result.get("criteria", {}).get("relevant_domain", {}).get("domains_identified", [])),
                        "metrics_identified": "; ".join(
                            result.get("criteria", {}).get("quality_assurance", {}).get("metrics_identified", [])),
                        "key_decision_factors": result.get("key_decision_factors", ""),
                        "additional_notes": result.get("additional_notes", ""),
                        "analyzed_at": datetime.datetime.now().isoformat(timespec="seconds"),
                        "full_json_path": "",
                        "_full_result": result,
                    }
                    save_to_repository(entry)
                    self.after(0, self._batch_log.insert, "end",
                               f"→ {rec}\n", rec_tag)
                except Exception as e:
                    self.after(0, self._batch_log.insert, "end",
                               f"ERROR: {e}\n", "err")

                self.after(0, self._batch_progress.__setitem__, "value", i+1)

            self.after(0, self._batch_log.insert, "end",
                       f"\n✓ Batch complete. Repository updated.\n", "ok")
            self.after(0, self._refresh_repository_tab)
        except Exception as e:
            self.after(0, self._batch_log.insert, "end",
                       f"\nFATAL ERROR: {e}\n", "err")
        finally:
            self.after(0, self._set_busy, False)

    # ── Repository display ────────────────────────────────────────────────────

    def _refresh_repository_tab(self):
        repo  = load_repository()
        query = self._filter_var.get().lower() if hasattr(self, "_filter_var") else ""
        rec_f = self._rec_filter.get() if hasattr(self, "_rec_filter") else "All"

        for item in self._tree.get_children():
            self._tree.delete(item)

        for r in repo:
            rec = r.get("recommendation", "")
            if rec_f != "All" and rec != rec_f:
                continue
            if query and query not in json.dumps(r).lower():
                continue

            tag = {"INCLUDE": "include", "EXCLUDE": "exclude",
                   "MANUAL_REVIEW": "manual"}.get(rec, "")
            ts  = r.get("analyzed_at", "")[:16].replace("T", " ")
            self._tree.insert("", "end", iid=r.get("paper_id"),
                              values=(r.get("paper_id",""), r.get("title",""),
                                      r.get("year",""), rec,
                                      r.get("confidence",""), ts),
                              tags=(tag,))

    def _sort_tree(self, col):
        rows = [(self._tree.set(k, col), k) for k in self._tree.get_children("")]
        rows.sort()
        for i, (_, k) in enumerate(rows):
            self._tree.move(k, "", i)

    def _view_repo_entry(self, _event):
        sel = self._tree.selection()
        if not sel:
            return
        paper_id = sel[0]
        repo = load_repository()
        entry = next((r for r in repo if r.get("paper_id") == paper_id), None)
        if not entry:
            return

        win = tk.Toplevel(self)
        win.title(f"Paper Detail — {paper_id}")
        win.geometry("800x620")
        win.configure(bg=PALETTE["bg"])

        tk.Label(win, text=f"{paper_id}  ·  {entry.get('title','(no title)')}",
                 bg=PALETTE["navy"], fg=PALETTE["amber"],
                 font=("Georgia", 12, "bold"), padx=12, pady=8).pack(fill="x")

        txt = scrolledtext.ScrolledText(
            win, font=("Courier", 9), bg="#1e2636", fg="#c8d8f0",
            bd=0, padx=12, pady=10, wrap="word"
        )
        txt.pack(fill="both", expand=True, padx=12, pady=12)

        full = entry.get("_full_result", {})
        if full:
            txt.insert("end", json.dumps(full, indent=2))
        else:
            txt.insert("end", json.dumps(
                {k: v for k, v in entry.items() if k != "_full_result"}, indent=2
            ))
        txt.configure(state="disabled")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _validate_ready(self) -> bool:
        if not self._api_key.get().strip():
            messagebox.showwarning(
                "API Key Required",
                "Please enter your Anthropic API key in the Settings tab."
            )
            self.notebook.select(self.tab_config)
            return False
        if not self._current_pdf_bytes and not hasattr(self, "_batch_csv_path"):
            messagebox.showwarning(
                "No Paper Loaded",
                "Please fetch a PDF from a URL or upload a PDF file first."
            )
            return False
        return True

    def _set_busy(self, busy: bool):
        self._busy = busy
        state = "disabled" if busy else "normal"
        self._analyze_btn.config(state=state)

    def _set_progress(self, msg: str):
        self._progress_label.config(text=msg)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = PaperScreenerApp()
    app.mainloop()
