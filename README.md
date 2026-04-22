# GenAI Evidence Hub — Paper Screener

A desktop tool for screening research papers for inclusion/exclusion in the
GenAI Evidence Hub systematic literature review (Learning Data Insights, LLC).

---

## Setup

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

> On Windows, use `python -m pip install -r requirements.txt` if `pip` is not recognized.

### 2. Run the application

```bash
python app.py
```

---

## First-Time Configuration

1. Open the **Settings** tab
2. Paste your **Anthropic API key** (`sk-ant-...`)
3. The key is stored in memory only — you will need to re-enter it each session
4. Get a key at: https://console.anthropic.com → API Keys → Create Key
5. Add credits at: https://console.anthropic.com → Billing (minimum $5)

**Cost:** ~$0.01–0.03 per paper · 200 papers ≈ $4–6 total

---

## Screening a Single Paper

1. Go to the **Single Paper** tab
2. Enter a **Paper ID** (required — used as the unique identifier in the repository)
3. Either:
   - Paste a **URL** and click **Fetch PDF** (works for direct PDF links; paywalled pages will fail and require manual upload)
   - Or click **Upload PDF** to load a local file
4. Click **▶ Analyze Paper**
5. Results appear in the panel below and are saved automatically to the repository

All metadata (title, authors, year, journal, DOI, abstract) is extracted automatically
from the PDF — no manual entry required beyond the Paper ID.

---

## Batch Upload

1. Go to the **Batch Upload** tab
2. Click **Download CSV Template** to get the expected format
3. Fill in your CSV with one paper per row:

| Column | Required | Notes |
|--------|----------|-------|
| `paper_id` | ✓ | Unique identifier you define |
| `url` | one of these | Direct PDF link, fetched automatically |
| `file_path` | one of these | Local path to a PDF file |

- If both `url` and `file_path` are provided, `file_path` takes priority
- All metadata (title, authors, year, journal, DOI, abstract) is extracted from the PDF automatically — no need to include it in the CSV
- Columns can be in any order; extra columns are ignored

4. Click **Select Batch CSV** then **▶ Run Batch Analysis**
5. Progress, per-paper timing, and running counts appear in the progress panel
6. Click **⏹ Stop** at any time to halt after the current paper finishes — completed results are saved

---

## Repository

All analyzed papers are saved to:

```
~/genai_evidence_hub/
  paper_repository.json    ← Full data including complete Claude analysis
  paper_repository.csv     ← Spreadsheet-friendly summary view
  batch_template.csv       ← Template for batch uploads
```

The repository is sorted by Paper ID in ascending order (numerically when IDs are
numbers, alphabetically otherwise). Re-analyzing a paper with the same Paper ID
overwrites the previous result — no duplicates are created.

Use the **Repository** tab to:
- Browse all analyzed papers with title, authors, year, and venue visible
- Filter by recommendation: INCLUDE / EXCLUDE / MANUAL_REVIEW
- Search by any text across all fields
- Click column headers to re-sort
- Double-click any row to view the full analysis JSON

---

## Analysis Criteria

Papers are evaluated against three criteria:

### Criterion 1: GenAI Used
The primary AI system must be a generative model (GPT-3/4/4o, Claude, Gemini,
LLaMA, Mistral, DeepSeek, T5, etc.). Traditional ML approaches (SVM, Random Forest,
KNN, logistic regression) without a GenAI component are excluded.

### Criterion 2: Relevant Assessment Domain
The GenAI system must directly perform one of these four tasks:

| Domain | Description |
|--------|-------------|
| **Item Generation** | GenAI creates assessment questions, test items, or rubrics |
| **Formative Feedback** | GenAI generates feedback text delivered to students |
| **Automated Item Scoring** | GenAI assigns scores to student-produced work (essays, short answer, etc.) |
| **Multimodal Inferences** | GenAI processes classroom audio/video for assessment |

Papers that only *discuss* these domains without the GenAI system executing the task
are excluded. Also excluded: AI detection, data annotation/labeling, plagiarism
detection, and fairness-only analyses.

### Criterion 3: Quality Assurance
The paper must report quantitative evaluation metrics (F1, Kappa, QWK, AUROC,
BLEU/ROUGE, accuracy vs. human raters, etc.) for the GenAI system's outputs.

---

## Decision Rules

| Decision | Condition |
|----------|-----------|
| **INCLUDE** | All three criteria YES |
| **EXCLUDE** | Any criterion NO; paper published before 2023; non-English paper |
| **MANUAL_REVIEW** | Any criterion UNCLEAR; genuine domain boundary case |

---

## Confidence Levels

| Level | Meaning |
|-------|---------|
| **High** | All criteria unambiguous — no domain boundary judgment required |
| **Medium** | At least one criterion required meaningful interpretation |
| **Low** | Genuine boundary case, missing information, or conflicting signals |

---

## Output Fields

Each analyzed paper is stored with the following fields:

| Field | Source |
|-------|--------|
| `paper_id` | Entered by user |
| `title` | Extracted from PDF |
| `authors` | Extracted from PDF |
| `publication_year` | Extracted from PDF |
| `journal_or_venue` | Extracted from PDF |
| `doi` | Extracted from PDF |
| `abstract` | Extracted from PDF |
| `url` / `file_path` | From CSV or manual entry |
| `recommendation` | INCLUDE / EXCLUDE / MANUAL_REVIEW |
| `confidence` | High / Medium / Low |
| `genai_used` | YES / NO / UNCLEAR |
| `relevant_domain` | YES / NO / UNCLEAR |
| `quality_assurance` | YES / NO / UNCLEAR |
| `domains_identified` | List of matching domains |
| `metrics_identified` | List of reported metrics |
| `key_decision_factors` | Factual summary of determining evidence |
| `additional_notes` | Domain boundary flags, missing info, reviewer notes |
| `analyzed_at` | Timestamp of analysis |
| `model_used` | Claude model version |
