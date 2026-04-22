"""
GenAI Evidence Hub — Paper Screening Tool
Screens papers for inclusion/exclusion in the systematic literature review
based on the GenAI Evidence Hub criteria.

Backends:
  • Ollama  — free, fully local, no API key required (default)
  • Anthropic API — higher accuracy, requires paid credits
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
from pathlib import Path
import io
import re

# Anthropic SDK is optional — only needed for API mode
try:
    import anthropic as _anthropic_sdk
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

# ── Backend constants ─────────────────────────────────────────────────────────

MODE_OLLAMA     = "ollama"
MODE_API        = "api"
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODELS   = ["mistral", "llama3.1:8b", "llama3.1", "llama3.2", "mixtral", "gemma2", "phi3"]
DEFAULT_MODEL   = "mistral"

# ── App constants ─────────────────────────────────────────────────────────────

APP_TITLE = "GenAI Evidence Hub — Paper Screener"
REPO_DIR  = Path.home() / "genai_evidence_hub"
REPO_JSON = REPO_DIR / "paper_repository.json"
REPO_CSV  = REPO_DIR / "paper_repository.csv"
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

CSV_COLUMNS = [
    "paper_id", "title", "authors", "year", "url", "file_path",
    "recommendation", "confidence", "genai_used", "relevant_domain",
    "quality_assurance", "domains_identified", "metrics_identified",
    "key_decision_factors", "additional_notes", "analyzed_at",
    "backend_used", "model_used",
]

BATCH_CSV_COLUMNS = ["paper_id", "title", "authors", "year", "url", "file_path"]

SYSTEM_PROMPT = """You are a systematic literature review screener for the GenAI Evidence Hub,
a research initiative examining generative AI in educational assessment contexts. Your job is
to evaluate whether a research paper meets the inclusion criteria for this meta-analysis.

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
- Item Generation: Creation of assessment items (forced choice, problem-based, simulations, etc.)
- Formative Feedback: Real-time feedback to students to improve knowledge/skills/abilities
- Automated Item Scoring: AI scoring of complex student work (essays, short answer, simulations) typically scored by humans
- Multimodal (Audio/Video) Inferences: Assessment using audio/video data in classroom contexts
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
Respond ONLY with valid JSON in this exact structure (no markdown fences, no preamble):
{
  "overall_recommendation": "INCLUDE",
  "criteria": {
    "genai_used": {
      "verdict": "YES",
      "reasoning": "Detailed explanation",
      "text_examples": "Direct quotes or paraphrases from the paper",
      "location": "Page/section references where possible"
    },
    "relevant_domain": {
      "verdict": "YES",
      "domains_identified": ["Automated Item Scoring"],
      "reasoning": "Detailed explanation",
      "text_examples": "Direct quotes or paraphrases from the paper",
      "location": "Page/section references where possible"
    },
    "quality_assurance": {
      "verdict": "YES",
      "metrics_identified": ["F1", "Kappa"],
      "reasoning": "Detailed explanation",
      "text_examples": "Direct quotes or paraphrases from the paper",
      "location": "Page/section references where possible"
    }
  },
  "confidence_level": "High",
  "confidence_rationale": "Explanation of confidence level",
  "key_decision_factors": "Most important elements that led to the decision",
  "additional_notes": "Any relevant observations, edge cases, or recommendations for human reviewers"
}"""


# ── Repository ────────────────────────────────────────────────────────────────

def ensure_repo():
    REPO_DIR.mkdir(parents=True, exist_ok=True)
    if not REPO_JSON.exists():
        REPO_JSON.write_text(json.dumps([], indent=2))
    if not REPO_CSV.exists():
        with open(REPO_CSV, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_COLUMNS).writeheader()
    if not BATCH_TEMPLATE_CSV.exists():
        with open(BATCH_TEMPLATE_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=BATCH_CSV_COLUMNS)
            w.writeheader()
            w.writerow({
                "paper_id": "PAPER_001", "title": "Example Paper Title",
                "authors": "Smith, J.; Jones, A.", "year": "2024",
                "url": "https://example.com/paper.pdf", "file_path": "",
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
    REPO_JSON.write_text(json.dumps(repo, indent=2, ensure_ascii=False), encoding="utf-8")
    _sync_csv(repo)


def _sync_csv(repo: list):
    with open(REPO_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in repo:
            w.writerow(r)


# ── PDF helpers ───────────────────────────────────────────────────────────────

def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """Extract text from PDF, returning all pages with page markers."""
    parts = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for i, page in enumerate(pdf.pages):
            t = page.extract_text()
            if t:
                parts.append(f"[Page {i+1}]\n{t}")
    return "\n\n".join(parts)


# Patterns that signal the start of non-analytical content worth trimming
_REF_SECTION_RE = re.compile(
    r"\n(?:References|Bibliography|Works Cited|Acknowledgements?|Appendix|"
    r"Supplementary|Funding|Conflict of Interest|Declaration|Author Contributions)"
    r"\s*\n",
    re.IGNORECASE,
)

# Regex to strip running headers/footers: lines ≤ 6 words that repeat or look like
# page numbers, journal names, DOIs, URLs
_NOISE_LINE_RE = re.compile(
    r"^\s*(?:\d+\s*$|doi:[^\n]+|https?://[^\n]+|©[^\n]+|\[\d+\].*$)",
    re.IGNORECASE | re.MULTILINE,
)

# Section headings that are high-value for our screening task
_KEY_SECTIONS = re.compile(
    r"(abstract|introduction|background|method|approach|experiment|result|"
    r"evaluation|discussion|conclusion|dataset|model|scoring|assessment|feedback)",
    re.IGNORECASE,
)


def smart_extract_text(pdf_bytes: bytes, target_chars: int = 28000) -> tuple[str, str]:
    """
    Extract and intelligently trim PDF text for local model consumption.

    Strategy:
    1. Extract full text
    2. Strip everything after References / Bibliography / Acknowledgements
    3. Remove noisy lines (page numbers, DOIs, URLs, copyright)
    4. If still too long, keep the first 40% (intro/methods) + last 30% (results/conclusion)
       of the body, which captures the most decision-relevant content

    Returns (trimmed_text, summary_note) where summary_note explains what was trimmed.
    """
    full = extract_text_from_pdf_bytes(pdf_bytes)
    if not full.strip():
        return full, ""

    original_len = len(full)

    # Step 1 — strip reference section and everything after
    ref_match = _REF_SECTION_RE.search(full)
    if ref_match:
        body = full[:ref_match.start()]
        refs_stripped = True
    else:
        body = full
        refs_stripped = False

    # Step 2 — remove noisy lines
    body = _NOISE_LINE_RE.sub("", body)
    # Collapse runs of blank lines to single blank line
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    body_len = len(body)

    if body_len <= target_chars:
        note = ""
        if refs_stripped:
            note = (f"[References/appendices stripped. "
                    f"Extracted {body_len:,} of {original_len:,} chars.]")
        return body, note

    # Step 3 — still too long: take front 55% + back 35% of body
    front = int(target_chars * 0.55)
    back  = int(target_chars * 0.35)
    middle_cut = body_len - front - back

    trimmed = (
        body[:front]
        + f"\n\n[... ~{middle_cut:,} chars of mid-paper content omitted ...]\n\n"
        + body[-back:]
    )
    note = (
        f"[Smart trim: kept intro/methods + results/conclusion. "
        f"Used {len(trimmed):,} of {original_len:,} chars. "
        f"Refs stripped: {refs_stripped}]"
    )
    return trimmed, note


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


# ── Analysis backends ─────────────────────────────────────────────────────────

def _clean_json(raw: str) -> dict:
    # Strip markdown fences and extract the first complete JSON object
    raw = raw.strip()
    raw = re.sub(r"^```json\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"^```\s*",     "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$",     "", raw, flags=re.MULTILINE)
    raw = raw.strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1:
        raw = raw[start:end+1]
    if not raw:
        raise json.JSONDecodeError("Empty response from model", "", 0)
    return json.loads(raw)


def _user_prompt_from_text(text: str, truncate: int = 80000) -> str:
    # Build user message; truncate long papers to avoid overwhelming small models
    truncated = text[:truncate]
    note = (
        f"\n[NOTE: Paper truncated to {truncate} chars for processing.]"
        if len(text) > truncate else ""
    )
    return (
        "Evaluate the following research paper against the GenAI Evidence Hub "
        "inclusion criteria. Read carefully before deciding.\n\n"
        "IMPORTANT: Respond with ONLY a valid JSON object. "
        "Start your response with { and end with }. "
        "No prose, no markdown fences, no explanation outside the JSON.\n\n"
        f"--- PAPER TEXT ---\n{truncated}{note}"
    )


def check_ollama_status():
    # Returns (is_running: bool, installed_models: list[str])
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        models = [m["name"].split(":")[0] for m in resp.json().get("models", [])]
        return True, sorted(set(models))
    except Exception:
        return False, []


def analyze_with_ollama(pdf_bytes: bytes, model: str,
                        progress_callback=None, stop_flag=None) -> dict:
    if progress_callback:
        progress_callback("Extracting and trimming PDF text…")

    text, trim_note = smart_extract_text(pdf_bytes, target_chars=28000)

    if not text.strip():
        raise ValueError(
            "No extractable text found in the PDF.\n"
            "The file may be a scanned image. Please try a text-based PDF."
        )

    if trim_note and progress_callback:
        progress_callback(f"Text prepared. {trim_note}")

    if stop_flag and stop_flag():
        raise InterruptedError("Stopped by user.")

    if progress_callback:
        progress_callback(f"Sending to {model} (~{len(text)//1000}k chars)… "
                          f"may take 1–5 min on CPU.")

    # Stronger JSON-only prompt for local models which tend to ignore formatting
    user_msg = (
        "You are evaluating a research paper for a systematic literature review.\n\n"
        "OUTPUT RULES — CRITICAL:\n"
        "- Your entire response must be ONE valid JSON object\n"
        "- Start with { on the very first character\n"
        "- End with } on the very last character\n"
        "- Zero prose before or after the JSON\n"
        "- Zero markdown (no ```)\n\n"
        "PAPER TEXT:\n"
        "----------\n"
        f"{text}\n"
        "----------\n\n"
        "Now output the JSON evaluation object:"
    )

    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        "options": {
            "temperature": 0.0,   # deterministic — reduces hallucination
            "num_predict": 4096,
            "num_ctx": 16384,     # request larger context window if model supports it
        },
    }

    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=900
        )
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        raise ConnectionError(
            "Cannot connect to Ollama.\n\n"
            "To fix this:\n"
            "  1. Download Ollama from https://ollama.com\n"
            "  2. Install and open it — it runs in the system tray\n"
            "  3. Open Command Prompt and run:  ollama pull mistral\n"
            "     (one-time ~4 GB download)\n"
            "  4. Then click Analyze again"
        )

    raw = resp.json().get("message", {}).get("content", "").strip()

    if not raw:
        raise ValueError(
            f"Model '{model}' returned an empty response.\n\n"
            "This usually means the model's context window was exceeded or it timed out.\n"
            "Try switching to a larger model (mistral or llama3.1:8b) in Settings,\n"
            "or use the Anthropic API for reliable results."
        )

    try:
        return _clean_json(raw)
    except json.JSONDecodeError as e:
        preview = raw[:300].replace("\n", " ")
        raise ValueError(
            f"Model returned prose instead of JSON.\n\n"
            f"This is a known limitation of smaller local models.\n"
            f"Recommendation: switch to 'mistral' or 'llama3.1:8b' in Settings,\n"
            f"or use the Anthropic API for reliable JSON output.\n\n"
            f"Parse error: {e.msg}\n"
            f"Response preview: {preview}"
        )


def analyze_with_api(pdf_bytes: bytes, api_key: str, progress_callback=None) -> dict:
    if not ANTHROPIC_AVAILABLE:
        raise ImportError("Run:  pip install anthropic")
    if progress_callback:
        progress_callback("Sending PDF to Claude API...")
    client  = _anthropic_sdk.Anthropic(api_key=api_key)
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
    response = client.messages.create(
        model="claude-opus-4-5", max_tokens=4096, system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": [
            {"type": "document", "source": {
                "type": "base64", "media_type": "application/pdf", "data": pdf_b64}},
            {"type": "text", "text":
                "Evaluate this paper against the GenAI Evidence Hub inclusion criteria. "
                "Return ONLY valid JSON — no markdown, no preamble."},
        ]}],
    )
    return _clean_json(response.content[0].text)


def analyze_paper(pdf_bytes: bytes, mode: str, api_key: str = "",
                  ollama_model: str = DEFAULT_MODEL, progress_callback=None,
                  stop_flag=None) -> dict:
    if mode == MODE_API:
        return analyze_with_api(pdf_bytes, api_key, progress_callback)
    return analyze_with_ollama(pdf_bytes, ollama_model, progress_callback, stop_flag)


# ── GUI ───────────────────────────────────────────────────────────────────────

class PaperScreenerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1100x800")
        self.minsize(900, 660)
        self.configure(bg=PALETTE["bg"])

        ensure_repo()
        self._api_key       = tk.StringVar()
        self._mode          = tk.StringVar(value=MODE_OLLAMA)
        self._ollama_model  = tk.StringVar(value=DEFAULT_MODEL)
        self._current_pdf_bytes = None
        self._batch_csv_path    = None
        self._busy = False
        self._stop_requested = False
        # Timer state
        self._single_start_time  = None
        self._batch_start_time   = None
        self._paper_start_time   = None
        self._timer_after_id     = None

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
        tk.Label(hdr, text="GenAI Evidence Hub",
                 font=("Georgia", 18, "bold"),
                 fg=PALETTE["amber"], bg=PALETTE["navy"]).pack(side="left", padx=20, pady=12)
        tk.Label(hdr, text="Paper Screening Tool  |  Learning Data Insights, LLC",
                 font=("Georgia", 10),
                 fg=PALETTE["grey_light"], bg=PALETTE["navy"]).pack(side="left", pady=18)

    def _style_notebook(self):
        s = ttk.Style(self)
        s.theme_use("default")
        s.configure("TNotebook", background=PALETTE["bg"], borderwidth=0)
        s.configure("TNotebook.Tab", background=PALETTE["grey_light"],
                    foreground=PALETTE["navy"], padding=[12, 6],
                    font=("Helvetica", 10, "bold"))
        s.map("TNotebook.Tab",
              background=[("selected", PALETTE["navy"])],
              foreground=[("selected", PALETTE["amber"])])

    # ── Single Paper Tab ──────────────────────────────────────────────────────

    def _build_single_tab(self):
        f   = self.tab_single
        pad = {"padx": 16, "pady": 8}

        meta = tk.LabelFrame(f, text=" Paper Information ", bg=PALETTE["bg"],
                             fg=PALETTE["navy"], font=("Helvetica", 10, "bold"),
                             bd=1, relief="groove")
        meta.pack(fill="x", **pad)
        grid = tk.Frame(meta, bg=PALETTE["bg"])
        grid.pack(fill="x", padx=12, pady=8)
        self._meta_vars = {}
        for i, lbl in enumerate(["Paper ID *", "Title", "Authors", "Year"]):
            tk.Label(grid, text=lbl, bg=PALETTE["bg"], fg=PALETTE["grey_dark"],
                     font=("Helvetica", 9)).grid(row=i, column=0, sticky="w", pady=3)
            var = tk.StringVar()
            self._meta_vars[lbl] = var
            tk.Entry(grid, textvariable=var, width=60, font=("Helvetica", 10),
                     bd=1, relief="solid").grid(row=i, column=1, sticky="ew",
                                                padx=(8,0), pady=3)
        grid.columnconfigure(1, weight=1)

        src = tk.LabelFrame(f, text=" Paper Source ", bg=PALETTE["bg"],
                            fg=PALETTE["navy"], font=("Helvetica", 10, "bold"),
                            bd=1, relief="groove")
        src.pack(fill="x", **pad)
        inner = tk.Frame(src, bg=PALETTE["bg"])
        inner.pack(fill="x", padx=12, pady=8)

        url_row = tk.Frame(inner, bg=PALETTE["bg"])
        url_row.pack(fill="x", pady=3)
        tk.Label(url_row, text="URL:", bg=PALETTE["bg"], fg=PALETTE["grey_dark"],
                 width=10, anchor="w", font=("Helvetica", 9)).pack(side="left")
        self._url_var = tk.StringVar()
        tk.Entry(url_row, textvariable=self._url_var, font=("Helvetica", 10),
                 bd=1, relief="solid").pack(side="left", fill="x", expand=True, padx=(4,8))
        tk.Button(url_row, text="Fetch PDF", command=self._fetch_url,
                  bg=PALETTE["teal"], fg="white",
                  font=("Helvetica", 9, "bold"), relief="flat", padx=10).pack(side="left")

        up_row = tk.Frame(inner, bg=PALETTE["bg"])
        up_row.pack(fill="x", pady=3)
        tk.Label(up_row, text="— or —", bg=PALETTE["bg"], fg=PALETTE["grey_mid"],
                 font=("Helvetica", 9, "italic")).pack(side="left", padx=8)
        tk.Button(up_row, text="Upload PDF", command=self._upload_pdf,
                  bg=PALETTE["navy_mid"], fg="white",
                  font=("Helvetica", 9, "bold"), relief="flat", padx=12).pack(side="left")
        self._file_label = tk.Label(up_row, text="No file selected",
                                    bg=PALETTE["bg"], fg=PALETTE["grey_mid"],
                                    font=("Helvetica", 9, "italic"))
        self._file_label.pack(side="left", padx=8)

        btn_row = tk.Frame(f, bg=PALETTE["bg"])
        btn_row.pack(fill="x", padx=16, pady=4)
        self._analyze_btn = tk.Button(
            btn_row, text="Analyze Paper",
            command=self._run_single_analysis,
            bg=PALETTE["amber"], fg=PALETTE["navy"],
            font=("Helvetica", 11, "bold"), relief="flat",
            padx=20, pady=8, cursor="hand2")
        self._analyze_btn.pack(side="left")

        # Single paper progress panel
        sp_panel = tk.Frame(f, bg=PALETTE["navy_mid"], bd=0)
        sp_panel.pack(fill="x", padx=16, pady=(0, 4))

        sp_top = tk.Frame(sp_panel, bg=PALETTE["navy_mid"])
        sp_top.pack(fill="x", padx=10, pady=(6, 2))

        self._progress_label = tk.Label(
            sp_top, text="Ready.", bg=PALETTE["navy_mid"],
            fg=PALETTE["grey_light"], font=("Helvetica", 9, "italic"), anchor="w")
        self._progress_label.pack(side="left", fill="x", expand=True)

        self._single_timer_label = tk.Label(
            sp_top, text="", bg=PALETTE["navy_mid"],
            fg=PALETTE["amber_light"], font=("Courier", 9, "bold"), anchor="e", width=10)
        self._single_timer_label.pack(side="right")

        self._single_pbar = ttk.Progressbar(sp_panel, mode="indeterminate", length=200)
        self._single_pbar.pack(fill="x", padx=10, pady=(2, 6))

        res = tk.LabelFrame(f, text=" Analysis Results ", bg=PALETTE["bg"],
                            fg=PALETTE["navy"], font=("Helvetica", 10, "bold"),
                            bd=1, relief="groove")
        res.pack(fill="both", expand=True, **pad)
        self._result_text = scrolledtext.ScrolledText(
            res, font=("Courier", 9), bg="#1e2636", fg="#c8d8f0",
            insertbackground="white", bd=0, padx=10, pady=8, wrap="word")
        self._result_text.pack(fill="both", expand=True, padx=8, pady=8)
        self._result_text.insert("1.0", "Results will appear here after analysis.")
        self._result_text.configure(state="disabled")
        for tag, color in [("include","#5BE8A0"),("exclude","#FF7B7B"),
                           ("manual","#FFD166"),("yes","#5BE8A0"),
                           ("no","#FF7B7B"),("unclear","#FFD166"),("key","#94D8F0")]:
            self._result_text.tag_config(tag, foreground=color)
        self._result_text.tag_config("heading", foreground=PALETTE["amber_light"],
                                     font=("Courier", 10, "bold"))

    # ── Batch Tab ─────────────────────────────────────────────────────────────

    def _build_batch_tab(self):
        f   = self.tab_batch
        pad = {"padx": 16, "pady": 10}

        info = tk.LabelFrame(f, text=" Batch Upload Instructions ", bg=PALETTE["bg"],
                             fg=PALETTE["navy"], font=("Helvetica", 10, "bold"),
                             bd=1, relief="groove")
        info.pack(fill="x", **pad)
        tk.Label(info, bg=PALETTE["bg"], fg=PALETTE["grey_dark"],
                 font=("Helvetica", 9), justify="left", wraplength=820,
                 text=(
                     "Upload a CSV with one paper per row. Required column: paper_id.\n"
                     "Optional: title, authors, year, url, file_path. Columns can be in any order.\n"
                     "  file_path — local path to PDF (takes priority over url)\n"
                     "  url — direct PDF link, fetched automatically"
                 )).pack(padx=12, pady=8, anchor="w")
        tk.Button(info, text="Download CSV Template",
                  command=self._download_batch_template,
                  bg=PALETTE["teal"], fg="white",
                  font=("Helvetica", 9, "bold"), relief="flat", padx=10
                  ).pack(padx=12, pady=(0,8), anchor="w")

        ctrl = tk.Frame(f, bg=PALETTE["bg"])
        ctrl.pack(fill="x", **pad)
        tk.Button(ctrl, text="Select Batch CSV", command=self._select_batch_csv,
                  bg=PALETTE["navy_mid"], fg="white",
                  font=("Helvetica", 10, "bold"), relief="flat",
                  padx=12, pady=6).pack(side="left")
        self._batch_file_label = tk.Label(ctrl, text="No file selected",
                                          bg=PALETTE["bg"], fg=PALETTE["grey_mid"],
                                          font=("Helvetica", 9, "italic"))
        self._batch_file_label.pack(side="left", padx=10)
        self._batch_run_btn = tk.Button(
            ctrl, text="Run Batch Analysis",
            command=self._run_batch_analysis,
            bg=PALETTE["amber"], fg=PALETTE["navy"],
            font=("Helvetica", 10, "bold"), relief="flat",
            padx=16, pady=6, cursor="hand2", state="disabled")
        self._batch_run_btn.pack(side="right")

        self._batch_stop_btn = tk.Button(
            ctrl, text="⏹  Stop",
            command=self._stop_batch,
            bg=PALETTE["red"], fg="white",
            font=("Helvetica", 10, "bold"), relief="flat",
            padx=12, pady=6, cursor="hand2", state="disabled")
        self._batch_stop_btn.pack(side="right", padx=6)

        # ── Batch progress panel ──
        bp = tk.Frame(f, bg=PALETTE["navy_mid"], bd=0)
        bp.pack(fill="x", padx=16, pady=(4, 0))

        # Row 1: progress bar + % label
        bp_bar_row = tk.Frame(bp, bg=PALETTE["navy_mid"])
        bp_bar_row.pack(fill="x", padx=10, pady=(6, 2))
        self._batch_pct_label = tk.Label(
            bp_bar_row, text="0%", bg=PALETTE["navy_mid"],
            fg=PALETTE["amber_light"], font=("Courier", 9, "bold"), width=5, anchor="e")
        self._batch_pct_label.pack(side="right")
        self._batch_progress = ttk.Progressbar(bp_bar_row, mode="determinate")
        self._batch_progress.pack(side="left", fill="x", expand=True)

        # Row 2: current paper status + per-paper timer
        bp_status_row = tk.Frame(bp, bg=PALETTE["navy_mid"])
        bp_status_row.pack(fill="x", padx=10, pady=1)
        self._batch_status = tk.Label(
            bp_status_row, text="", bg=PALETTE["navy_mid"],
            fg=PALETTE["grey_light"], font=("Helvetica", 9, "italic"), anchor="w")
        self._batch_status.pack(side="left", fill="x", expand=True)
        self._paper_timer_label = tk.Label(
            bp_status_row, text="", bg=PALETTE["navy_mid"],
            fg=PALETTE["teal_light"], font=("Courier", 9), anchor="e", width=14)
        self._paper_timer_label.pack(side="right")

        # Row 3: counts + total elapsed
        bp_stats_row = tk.Frame(bp, bg=PALETTE["navy_mid"])
        bp_stats_row.pack(fill="x", padx=10, pady=(1, 6))
        self._batch_counts_label = tk.Label(
            bp_stats_row, text="", bg=PALETTE["navy_mid"],
            fg=PALETTE["grey_mid"], font=("Helvetica", 8), anchor="w")
        self._batch_counts_label.pack(side="left", fill="x", expand=True)
        self._batch_total_timer_label = tk.Label(
            bp_stats_row, text="", bg=PALETTE["navy_mid"],
            fg=PALETTE["amber_light"], font=("Courier", 9, "bold"), anchor="e", width=14)
        self._batch_total_timer_label.pack(side="right")

        lf = tk.LabelFrame(f, text=" Batch Log ", bg=PALETTE["bg"],
                           fg=PALETTE["navy"], font=("Helvetica", 10, "bold"),
                           bd=1, relief="groove")
        lf.pack(fill="both", expand=True, **pad)
        self._batch_log = scrolledtext.ScrolledText(
            lf, font=("Courier", 9), bg="#1e2636", fg="#c8d8f0",
            bd=0, padx=10, pady=8, wrap="word")
        self._batch_log.pack(fill="both", expand=True, padx=8, pady=8)
        for tag, color in [("ok","#5BE8A0"),("err","#FF7B7B"),("info","#FFD166")]:
            self._batch_log.tag_config(tag, foreground=color)

    # ── Repository Tab ────────────────────────────────────────────────────────

    def _build_repo_tab(self):
        f   = self.tab_repo
        pad = {"padx": 16, "pady": 8}

        ctrl = tk.Frame(f, bg=PALETTE["bg"])
        ctrl.pack(fill="x", **pad)
        tk.Button(ctrl, text="Refresh", command=self._refresh_repository_tab,
                  bg=PALETTE["teal"], fg="white",
                  font=("Helvetica", 9, "bold"), relief="flat", padx=10).pack(side="left")
        tk.Button(ctrl, text="Open Folder",
                  command=lambda: os.startfile(REPO_DIR),
                  bg=PALETTE["navy_mid"], fg="white",
                  font=("Helvetica", 9, "bold"), relief="flat", padx=10
                  ).pack(side="left", padx=8)

        ff = tk.Frame(ctrl, bg=PALETTE["bg"])
        ff.pack(side="right")
        tk.Label(ff, text="Search:", bg=PALETTE["bg"], fg=PALETTE["grey_dark"],
                 font=("Helvetica", 9)).pack(side="left")
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._refresh_repository_tab())
        tk.Entry(ff, textvariable=self._filter_var, width=20,
                 font=("Helvetica", 9), bd=1, relief="solid").pack(side="left", padx=4)

        self._rec_filter = tk.StringVar(value="All")
        for val, color in [("All", PALETTE["grey_mid"]), ("INCLUDE", PALETTE["green"]),
                           ("EXCLUDE", PALETTE["red"]), ("MANUAL_REVIEW", PALETTE["orange"])]:
            tk.Radiobutton(ff, text=val, variable=self._rec_filter, value=val,
                           command=self._refresh_repository_tab,
                           bg=PALETTE["bg"], fg=color, activebackground=PALETTE["bg"],
                           font=("Helvetica", 9, "bold"),
                           selectcolor=PALETTE["amber"],
                           indicatoron=1).pack(side="left", padx=4)

        cols   = ("paper_id","title","year","recommendation","confidence","backend_used","analyzed_at")
        widths = (100, 270, 50, 120, 80, 100, 130)

        tf = tk.Frame(f, bg=PALETTE["bg"])
        tf.pack(fill="both", expand=True, padx=16, pady=(0,4))

        s = ttk.Style()
        s.configure("Repo.Treeview", rowheight=26, font=("Helvetica", 9),
                    background=PALETTE["white"], fieldbackground=PALETTE["white"],
                    foreground=PALETTE["navy"])
        s.configure("Repo.Treeview.Heading", font=("Helvetica", 9, "bold"),
                    background=PALETTE["navy"], foreground="white")

        self._tree = ttk.Treeview(tf, columns=cols, show="headings",
                                  style="Repo.Treeview", selectmode="browse")
        for col, w in zip(cols, widths):
            self._tree.heading(col, text=col.replace("_"," ").title(),
                               command=lambda c=col: self._sort_tree(c))
            self._tree.column(col, width=w, anchor="w")

        vsb = ttk.Scrollbar(tf, orient="vertical", command=self._tree.yview)
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

    # ── Settings Tab ──────────────────────────────────────────────────────────

    def _build_config_tab(self):
        f = self.tab_config

        mf = tk.LabelFrame(f, text=" Analysis Backend ", bg=PALETTE["bg"],
                           fg=PALETTE["navy"], font=("Helvetica", 10, "bold"),
                           bd=1, relief="groove")
        mf.pack(fill="x", padx=20, pady=16)
        inner = tk.Frame(mf, bg=PALETTE["bg"])
        inner.pack(fill="x", padx=16, pady=12)

        # ── Ollama section ──
        tk.Radiobutton(inner,
                       text="Local (Ollama)  — Free, runs entirely on your computer",
                       variable=self._mode, value=MODE_OLLAMA,
                       bg=PALETTE["bg"], fg=PALETTE["navy"],
                       font=("Helvetica", 10, "bold"), selectcolor=PALETTE["amber"],
                       activebackground=PALETTE["bg"],
                       indicatoron=1).pack(anchor="w")

        os_row = tk.Frame(inner, bg=PALETTE["bg"])
        os_row.pack(fill="x", padx=28, pady=2)
        self._ollama_status_label = tk.Label(
            os_row, text="Click 'Check Status' to verify Ollama is running",
            bg=PALETTE["bg"], fg=PALETTE["grey_mid"], font=("Helvetica", 9))
        self._ollama_status_label.pack(side="left")
        tk.Button(os_row, text="Check Status", command=self._check_ollama,
                  bg=PALETTE["teal"], fg="white",
                  font=("Helvetica", 8), relief="flat", padx=8
                  ).pack(side="left", padx=8)

        mr = tk.Frame(inner, bg=PALETTE["bg"])
        mr.pack(fill="x", padx=28, pady=4)
        tk.Label(mr, text="Model:", bg=PALETTE["bg"], fg=PALETTE["grey_dark"],
                 font=("Helvetica", 9)).pack(side="left")
        self._model_combo = ttk.Combobox(mr, textvariable=self._ollama_model,
                                         values=OLLAMA_MODELS, width=24,
                                         font=("Helvetica", 10))
        self._model_combo.pack(side="left", padx=8)

        tk.Label(inner, bg=PALETTE["bg"], fg=PALETTE["grey_mid"],
                 font=("Helvetica", 8, "italic"), justify="left",
                 text=(
                     "First-time Ollama setup:\n"
                     "  1. Download from https://ollama.com and install it\n"
                     "  2. It will appear in your system tray and start automatically\n"
                     "  3. Open Command Prompt and run:   ollama pull mistral\n"
                     "     (recommended — ~4 GB, much more reliable JSON output than llama3.2)\n"
                     "  4. For fastest results, use the Anthropic API (~$0.01–0.05/paper)"
                 )).pack(anchor="w", padx=28, pady=(2,10))

        tk.Frame(inner, bg=PALETTE["grey_light"], height=1).pack(fill="x", pady=8)

        # ── API section ──
        tk.Radiobutton(inner,
                       text="Anthropic API  — Higher accuracy, requires paid API credits (~$0.01-0.05/paper)",
                       variable=self._mode, value=MODE_API,
                       bg=PALETTE["bg"], fg=PALETTE["navy"],
                       font=("Helvetica", 10, "bold"), selectcolor=PALETTE["amber"],
                       activebackground=PALETTE["bg"],
                       indicatoron=1).pack(anchor="w")

        kr = tk.Frame(inner, bg=PALETTE["bg"])
        kr.pack(fill="x", padx=28, pady=4)
        tk.Label(kr, text="API Key:", bg=PALETTE["bg"], fg=PALETTE["grey_dark"],
                 font=("Helvetica", 9)).pack(side="left")
        self._key_entry = tk.Entry(kr, textvariable=self._api_key,
                                   font=("Courier", 10), show="*", width=52,
                                   bd=1, relief="solid")
        self._key_entry.pack(side="left", padx=8)
        tk.Button(kr, text="Show/Hide", command=self._toggle_key_vis,
                  bg=PALETTE["grey_light"], fg=PALETTE["navy"],
                  font=("Helvetica", 8), relief="flat", padx=8).pack(side="left")

        tk.Label(inner, bg=PALETTE["bg"], fg=PALETTE["grey_mid"],
                 font=("Helvetica", 8, "italic"),
                 text=(
                     "API key stored in memory only — never written to disk.\n"
                     "Get a key: https://console.anthropic.com  -> API Keys -> Create Key\n"
                     "Add credits: https://console.anthropic.com  -> Billing  (minimum $5)"
                 )).pack(anchor="w", padx=28, pady=(0,8))

        # ── Repo location ──
        tk.Frame(f, bg=PALETTE["grey_light"], height=1).pack(fill="x", padx=20, pady=8)
        tk.Label(f, text="Repository Location", bg=PALETTE["bg"],
                 fg=PALETTE["navy"], font=("Helvetica", 10, "bold")).pack(anchor="w", padx=20)
        tk.Label(f, text=str(REPO_DIR), bg=PALETTE["bg"], fg=PALETTE["teal"],
                 font=("Courier", 9)).pack(anchor="w", padx=20, pady=2)
        tk.Label(f, bg=PALETTE["bg"], fg=PALETTE["grey_mid"],
                 font=("Helvetica", 8, "italic"),
                 text="paper_repository.json (full data)  ·  paper_repository.csv (spreadsheet)"
                 ).pack(anchor="w", padx=20)

        self.after(500, self._check_ollama)

    # ── Settings helpers ──────────────────────────────────────────────────────

    def _toggle_key_vis(self):
        self._key_entry.config(show="" if self._key_entry.cget("show") == "*" else "*")

    def _check_ollama(self):
        self._ollama_status_label.config(text="Checking…", fg=PALETTE["grey_mid"])
        def _do():
            running, models = check_ollama_status()
            def _upd():
                if running:
                    ms = ", ".join(models) if models else "none installed yet — run: ollama pull llama3.2"
                    self._ollama_status_label.config(
                        text=f"Ollama is running  |  Models: {ms}", fg=PALETTE["green"])
                    if models:
                        self._model_combo["values"] = models
                        if self._ollama_model.get() not in models:
                            self._ollama_model.set(models[0])
                else:
                    self._ollama_status_label.config(
                        text="Ollama not found — install from https://ollama.com",
                        fg=PALETTE["red"])
            self.after(0, _upd)
        threading.Thread(target=_do, daemon=True).start()

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
                    text=f"Fetched ({len(pdf_bytes)//1024} KB)", fg=PALETTE["green"]))
                self.after(0, self._set_progress, "PDF fetched.")
            else:
                self._current_pdf_bytes = None
                self.after(0, lambda: self._file_label.config(
                    text=f"Failed: {err[:55]}", fg=PALETTE["red"]))
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
                fg=PALETTE["green"])
            self._set_progress(f"Loaded: {name}")

    def _run_single_analysis(self):
        if not self._validate_ready(need_pdf=True):
            return
        paper_id = self._meta_vars["Paper ID *"].get().strip()
        if not paper_id:
            messagebox.showwarning("Missing ID", "Please enter a Paper ID.")
            return
        self._set_busy(True)
        self._set_progress("Starting analysis…")
        self._single_timer_label.config(text="")
        self._start_single_timer()
        threading.Thread(target=self._analysis_worker, args=(paper_id,), daemon=True).start()

    def _analysis_worker(self, paper_id: str):
        import time
        mode  = self._mode.get()
        model = self._ollama_model.get()
        key   = self._api_key.get().strip()
        try:
            result = analyze_paper(
                self._current_pdf_bytes, mode=mode, api_key=key, ollama_model=model,
                progress_callback=lambda m: self.after(0, self._set_progress, m))
            elapsed = time.monotonic() - (self._single_start_time or time.monotonic())
            entry = self._build_repo_entry(paper_id, result, mode, model)
            save_to_repository(entry)
            self.after(0, self._display_result, result, paper_id)
            self.after(0, self._refresh_repository_tab)
            self.after(0, self._set_progress,
                       f"Analysis complete — saved to repository.  ({self._fmt_elapsed(elapsed)})")
            self.after(0, self._stop_single_timer, elapsed)
        except ConnectionError as e:
            self.after(0, messagebox.showerror, "Ollama Not Running", str(e))
            self.after(0, self._set_progress, "Failed.")
            self.after(0, self._stop_single_timer, None)
        except json.JSONDecodeError:
            self.after(0, messagebox.showerror, "Parse Error",
                       "The model returned an unexpected response format.\n"
                       "Try again, or switch to Anthropic API in Settings for more reliable output.")
            self.after(0, self._set_progress, "Failed.")
            self.after(0, self._stop_single_timer, None)
        except Exception as e:
            self.after(0, messagebox.showerror, "Error", str(e))
            self.after(0, self._set_progress, "Failed.")
            self.after(0, self._stop_single_timer, None)
        finally:
            self.after(0, self._set_busy, False)

    def _build_repo_entry(self, paper_id, result, mode, model):
        c  = result.get("criteria", {})
        gn = c.get("genai_used", {})
        dm = c.get("relevant_domain", {})
        qa = c.get("quality_assurance", {})
        return {
            "paper_id":            paper_id,
            "title":               self._meta_vars["Title"].get().strip(),
            "authors":             self._meta_vars["Authors"].get().strip(),
            "year":                self._meta_vars["Year"].get().strip(),
            "url":                 self._url_var.get().strip(),
            "file_path":           "",
            "recommendation":      result.get("overall_recommendation",""),
            "confidence":          result.get("confidence_level",""),
            "genai_used":          gn.get("verdict",""),
            "relevant_domain":     dm.get("verdict",""),
            "quality_assurance":   qa.get("verdict",""),
            "domains_identified":  "; ".join(dm.get("domains_identified",[])),
            "metrics_identified":  "; ".join(qa.get("metrics_identified",[])),
            "key_decision_factors":result.get("key_decision_factors",""),
            "additional_notes":    result.get("additional_notes",""),
            "analyzed_at":         datetime.datetime.now().isoformat(timespec="seconds"),
            "backend_used":        "API" if mode == MODE_API else "Ollama",
            "model_used":          "claude-opus-4-5" if mode == MODE_API else model,
            "_full_result":        result,
        }

    def _display_result(self, result, paper_id):
        rec  = result.get("overall_recommendation","?")
        conf = result.get("confidence_level","?")
        crit = result.get("criteria",{})
        rtag = {"INCLUDE":"include","EXCLUDE":"exclude","MANUAL_REVIEW":"manual"}.get(rec,"")
        vtag = {"YES":"yes","NO":"no","UNCLEAR":"unclear"}

        lines = []
        def w(text, tag=None): lines.append((text, tag))

        w("="*68); w(f"  PAPER: {paper_id}", "heading")
        w(f"  RECOMMENDATION:  {rec}", rtag)
        w(f"  CONFIDENCE:      {conf}"); w("="*68)

        for key, label in [
            ("genai_used","Criterion 1: GenAI Used"),
            ("relevant_domain","Criterion 2: Relevant Assessment Domain"),
            ("quality_assurance","Criterion 3: Quality Assurance"),
        ]:
            c = crit.get(key,{})
            v = c.get("verdict","?")
            w(f"\n  {label}", "heading"); w(f"  Verdict: {v}", vtag.get(v))
            if key == "relevant_domain" and c.get("domains_identified"):
                w(f"  Domains: {', '.join(c['domains_identified'])}")
            if key == "quality_assurance" and c.get("metrics_identified"):
                w(f"  Metrics: {', '.join(c['metrics_identified'])}")
            w(f"  Reasoning: {c.get('reasoning','')}")
            if c.get("text_examples"):
                w(f"  Evidence:  {c['text_examples']}", "key")
            if c.get("location"):
                w(f"  Location:  {c['location']}")

        w("\n  Key Decision Factors", "heading"); w(f"  {result.get('key_decision_factors','')}")
        if result.get("confidence_rationale"):
            w("\n  Confidence Rationale","heading"); w(f"  {result.get('confidence_rationale','')}")
        if result.get("additional_notes"):
            w("\n  Additional Notes","heading"); w(f"  {result.get('additional_notes','')}")
        w("\n" + "="*68)

        self._result_text.configure(state="normal")
        self._result_text.delete("1.0","end")
        for text, tag in lines:
            if tag: self._result_text.insert("end", text+"\n", tag)
            else:   self._result_text.insert("end", text+"\n")
        self._result_text.configure(state="disabled")

    # ── Batch actions ─────────────────────────────────────────────────────────

    def _download_batch_template(self):
        dest = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV","*.csv")],
            initialfile="batch_papers_template.csv")
        if dest:
            import shutil; shutil.copy(BATCH_TEMPLATE_CSV, dest)
            messagebox.showinfo("Saved", f"Template saved to:\n{dest}")

    def _select_batch_csv(self):
        path = filedialog.askopenfilename(
            title="Select Batch CSV", filetypes=[("CSV files","*.csv")])
        if path:
            self._batch_csv_path = path
            self._batch_file_label.config(text=Path(path).name, fg=PALETTE["navy"])
            self._batch_run_btn.config(state="normal")

    def _run_batch_analysis(self):
        if not self._batch_csv_path: return
        if not self._validate_ready(need_pdf=False): return
        self._stop_requested = False
        self._set_busy(True)
        self._batch_log.delete("1.0","end")
        # Reset progress panel
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
        import time
        mode  = self._mode.get()
        model = self._ollama_model.get()
        key   = self._api_key.get().strip()
        rows = []
        try:
            for enc in ("utf-8-sig", "latin-1", "cp1252"):
                try:
                    with open(self._batch_csv_path, newline="", encoding=enc) as f:
                        rows = list(csv.DictReader(f))
                    self._log_batch(f"(Detected encoding: {enc})\n", "info")
                    break
                except UnicodeDecodeError:
                    continue
            else:
                with open(self._batch_csv_path, newline="",
                          encoding="utf-8", errors="replace") as f:
                    rows = list(csv.DictReader(f))
                self._log_batch("(Used fallback encoding — some characters may be replaced)\n","info")
        except Exception as e:
            self._log_batch(f"Could not read CSV: {e}\n","err")
            self.after(0, self._set_busy, False); return

        total = len(rows)
        self._log_batch(f"Loaded {total} papers.\n","info")
        self.after(0, self._batch_progress.__setitem__, "maximum", total)

        # Running counters
        n_included = n_excluded = n_manual = n_error = 0

        for i, row in enumerate(rows):
            if self._stop_requested:
                self._log_batch(f"\n⏹ Batch stopped after {i} of {total} papers.\n", "info")
                break

            pid  = row.get("paper_id", f"PAPER_{i+1}").strip()
            url  = row.get("url","").strip()
            fp   = row.get("file_path","").strip().replace("\\", os.sep).replace("/", os.sep)

            # Update status label and reset per-paper timer
            self.after(0, self._batch_status.config,
                       {"text": f"Paper {i+1}/{total}: {pid}"})
            self.after(0, self._new_paper_timer)

            self._log_batch(f"\n[{i+1}/{total}] {pid} — ","info")

            pdf_bytes = None
            if fp and os.path.isfile(fp):
                with open(fp,"rb") as fh: pdf_bytes = fh.read()
                self._log_batch("loaded from file. ","ok")
            elif url:
                self._log_batch("fetching URL… ","info")
                pdf_bytes, err = fetch_pdf_from_url(url)
                if pdf_bytes: self._log_batch("fetched. ","ok")
                else:
                    self._log_batch(f"FAILED ({err[:40]}). Skipping.\n","err")
                    n_error += 1
                    self.after(0, self._update_batch_counts,
                               i+1, total, n_included, n_excluded, n_manual, n_error)
                    continue
            else:
                self._log_batch("No source. Skipping.\n","err")
                n_error += 1
                self.after(0, self._update_batch_counts,
                           i+1, total, n_included, n_excluded, n_manual, n_error)
                continue

            paper_t0 = time.monotonic()
            try:
                self._log_batch("Analyzing… ","info")
                result = analyze_paper(
                    pdf_bytes, mode=mode, api_key=key, ollama_model=model,
                    progress_callback=lambda m: self._log_batch(f"  [{m}]\n", "info"),
                    stop_flag=lambda: self._stop_requested,
                )
                paper_elapsed = time.monotonic() - paper_t0
                rec  = result.get("overall_recommendation","?")
                rtag = {"INCLUDE":"ok","EXCLUDE":"err","MANUAL_REVIEW":"info"}.get(rec,"info")

                if rec == "INCLUDE":     n_included += 1
                elif rec == "EXCLUDE":   n_excluded += 1
                elif rec == "MANUAL_REVIEW": n_manual += 1

                c = result.get("criteria",{})
                entry = {
                    "paper_id": pid, "title": row.get("title",""),
                    "authors": row.get("authors",""), "year": row.get("year",""),
                    "url": url, "file_path": fp,
                    "recommendation": rec,
                    "confidence": result.get("confidence_level",""),
                    "genai_used":        c.get("genai_used",{}).get("verdict",""),
                    "relevant_domain":   c.get("relevant_domain",{}).get("verdict",""),
                    "quality_assurance": c.get("quality_assurance",{}).get("verdict",""),
                    "domains_identified": "; ".join(c.get("relevant_domain",{}).get("domains_identified",[])),
                    "metrics_identified": "; ".join(c.get("quality_assurance",{}).get("metrics_identified",[])),
                    "key_decision_factors": result.get("key_decision_factors",""),
                    "additional_notes": result.get("additional_notes",""),
                    "analyzed_at": datetime.datetime.now().isoformat(timespec="seconds"),
                    "backend_used": "API" if mode == MODE_API else "Ollama",
                    "model_used": "claude-opus-4-5" if mode == MODE_API else model,
                    "_full_result": result,
                }
                save_to_repository(entry)
                self._log_batch(
                    f"→ {rec}  ({self._fmt_elapsed(paper_elapsed)})\n", rtag)

            except InterruptedError:
                self._log_batch("stopped.\n", "info")
                break
            except ConnectionError as e:
                self._log_batch(f"OLLAMA ERROR: {str(e)[:80]}\n","err")
                n_error += 1
            except ValueError as e:
                self._log_batch(f"ERROR: {e}\n","err")
                n_error += 1
            except Exception as e:
                self._log_batch(f"ERROR: {e}\n","err")
                n_error += 1

            self.after(0, self._update_batch_counts,
                       i+1, total, n_included, n_excluded, n_manual, n_error)

        self._log_batch(f"\nBatch complete. Repository updated.\n","ok")
        self.after(0, self._batch_status.config,
                   {"text": f"Done — {n_included} included, {n_excluded} excluded, "
                            f"{n_manual} manual review, {n_error} errors"})
        self.after(0, self._refresh_repository_tab)
        self.after(0, self._stop_batch_timers)
        self.after(0, self._set_busy, False)

    def _log_batch(self, msg, tag=""):
        def _do():
            self._batch_log.insert("end", msg, tag)
            self._batch_log.see("end")
        self.after(0, _do)

    # ── Repository ────────────────────────────────────────────────────────────

    def _refresh_repository_tab(self):
        if not hasattr(self,"_tree"): return
        repo  = load_repository()
        query = self._filter_var.get().lower() if hasattr(self,"_filter_var") else ""
        rec_f = self._rec_filter.get() if hasattr(self,"_rec_filter") else "All"
        for item in self._tree.get_children(): self._tree.delete(item)
        for r in repo:
            rec = r.get("recommendation","")
            if rec_f != "All" and rec != rec_f: continue
            if query and query not in json.dumps(r).lower(): continue
            tag = {"INCLUDE":"include","EXCLUDE":"exclude","MANUAL_REVIEW":"manual"}.get(rec,"")
            ts  = r.get("analyzed_at","")[:16].replace("T"," ")
            self._tree.insert("","end", iid=r.get("paper_id"),
                              values=(r.get("paper_id",""), r.get("title",""),
                                      r.get("year",""), rec, r.get("confidence",""),
                                      r.get("backend_used",""), ts),
                              tags=(tag,))

    def _sort_tree(self, col):
        rows = [(self._tree.set(k,col), k) for k in self._tree.get_children("")]
        rows.sort()
        for i,(_,k) in enumerate(rows): self._tree.move(k,"",i)

    def _view_repo_entry(self, _=None):
        sel = self._tree.selection()
        if not sel: return
        repo  = load_repository()
        entry = next((r for r in repo if r.get("paper_id")==sel[0]), None)
        if not entry: return
        win = tk.Toplevel(self)
        win.title(f"Paper Detail — {sel[0]}")
        win.geometry("820x640")
        win.configure(bg=PALETTE["bg"])
        tk.Label(win, text=f"{sel[0]}  |  {entry.get('title','(no title)')}",
                 bg=PALETTE["navy"], fg=PALETTE["amber"],
                 font=("Georgia", 11, "bold"), padx=12, pady=8).pack(fill="x")
        txt = scrolledtext.ScrolledText(win, font=("Courier", 9), bg="#1e2636",
                                        fg="#c8d8f0", bd=0, padx=12, pady=10, wrap="word")
        txt.pack(fill="both", expand=True, padx=12, pady=12)
        full = entry.get("_full_result",{})
        display = full if full else {k:v for k,v in entry.items() if k!="_full_result"}
        txt.insert("end", json.dumps(display, indent=2))
        txt.configure(state="disabled")

    # ── Helpers ───────────────────────────────────────────────────────────────

    # ── Timer helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _fmt_elapsed(seconds: float) -> str:
        """Format elapsed seconds as m:ss or h:mm:ss."""
        s = int(seconds)
        if s < 3600:
            return f"{s // 60}:{s % 60:02d}"
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"

    def _start_single_timer(self):
        import time
        self._single_start_time = time.monotonic()
        self._single_pbar.start(12)
        self._tick_single()

    def _tick_single(self):
        import time
        if not self._busy or self._single_start_time is None:
            return
        elapsed = time.monotonic() - self._single_start_time
        self._single_timer_label.config(text=f"⏱ {self._fmt_elapsed(elapsed)}")
        self._timer_after_id = self.after(1000, self._tick_single)

    def _stop_single_timer(self, final_elapsed=None):
        import time
        if self._timer_after_id:
            self.after_cancel(self._timer_after_id)
            self._timer_after_id = None
        self._single_pbar.stop()
        if final_elapsed is not None:
            self._single_timer_label.config(
                text=f"✓ {self._fmt_elapsed(final_elapsed)}")
        else:
            self._single_timer_label.config(text="")

    def _start_batch_timers(self):
        import time
        self._batch_start_time = time.monotonic()
        self._paper_start_time = time.monotonic()
        self._tick_batch()

    def _new_paper_timer(self):
        import time
        self._paper_start_time = time.monotonic()

    def _tick_batch(self):
        import time
        if not self._busy:
            return
        now = time.monotonic()
        if self._paper_start_time:
            paper_e = now - self._paper_start_time
            self._paper_timer_label.config(
                text=f"Paper: {self._fmt_elapsed(paper_e)}")
        if self._batch_start_time:
            total_e = now - self._batch_start_time
            self._batch_total_timer_label.config(
                text=f"Total: {self._fmt_elapsed(total_e)}")
        self._timer_after_id = self.after(1000, self._tick_batch)

    def _stop_batch_timers(self):
        import time
        if self._timer_after_id:
            self.after_cancel(self._timer_after_id)
            self._timer_after_id = None
        if self._batch_start_time:
            total_e = time.monotonic() - self._batch_start_time
            self._batch_total_timer_label.config(
                text=f"Done: {self._fmt_elapsed(total_e)}")
        self._paper_timer_label.config(text="")

    def _update_batch_counts(self, done, total, included, excluded, manual, errors):
        pct = int(done / total * 100) if total else 0
        self._batch_progress["value"] = done
        self._batch_pct_label.config(text=f"{pct}%")
        self._batch_counts_label.config(
            text=f"{done}/{total} papers  ·  "
                 f"Include: {included}  Exclude: {excluded}  "
                 f"Manual Review: {manual}  Errors: {errors}")

    # ── Validation ────────────────────────────────────────────────────────────

    def _validate_ready(self, need_pdf=True):
        if self._mode.get() == MODE_API and not self._api_key.get().strip():
            messagebox.showwarning("API Key Required",
                                   "Please enter your Anthropic API key in the Settings tab.")
            self.notebook.select(self.tab_config); return False
        if need_pdf and not self._current_pdf_bytes:
            messagebox.showwarning("No PDF", "Please fetch or upload a PDF first.")
            return False
        return True

    def _set_busy(self, busy):
        self._busy = busy
        state = "disabled" if busy else "normal"
        self._analyze_btn.config(state=state)
        self._batch_run_btn.config(state="disabled" if busy else
                                   ("normal" if self._batch_csv_path else "disabled"))
        self._batch_stop_btn.config(
            state="normal" if busy else "disabled",
            text="⏹  Stop"
        )

    def _set_progress(self, msg):
        self._progress_label.config(text=msg)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = PaperScreenerApp()
    app.mainloop()
