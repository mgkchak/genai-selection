# GenAI Evidence Hub — Paper Screener

A desktop tool for screening research papers for inclusion/exclusion in the
GenAI Evidence Hub systematic literature review (Learning Data Insights, LLC).

---

## Setup

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the application

```bash
python app.py
```

---

## First-Time Configuration

1. Open the **Settings** tab
2. Paste your **Anthropic API key** (sk-ant-...)
3. The key is stored in memory only — you'll need to re-enter it each session

---

## Screening a Single Paper

1. Go to the **Single Paper** tab
2. Enter a **Paper ID** (required — used as the unique identifier in the repository)
3. Optionally fill in Title, Authors, Year
4. Either:
   - Paste a **URL** and click **Fetch PDF** (works for direct PDF links; paywalled pages will fail)
   - Or click **Upload PDF** to load a local file
5. Click **▶ Analyze Paper**
6. Results appear in the panel below and are saved automatically to the repository

---

## Batch Upload

1. Go to the **Batch Upload** tab
2. Click **Download CSV Template** to get the expected format
3. Fill in your CSV with one paper per row:

| Column | Required | Notes |
|--------|----------|-------|
| `paper_id` | ✓ | Unique identifier |
| `title` | — | Paper title |
| `authors` | — | Author names |
| `year` | — | Publication year |
| `url` | — | Direct PDF URL |
| `file_path` | — | Local path to PDF |

- If both `url` and `file_path` are given, `file_path` takes priority
- Extra columns in your CSV are preserved as metadata
- Columns can be in any order

4. Click **Select Batch CSV** then **▶ Run Batch Analysis**
5. Progress and results appear in the log panel

---

## Repository

All analyzed papers are saved to:

```
~/genai_evidence_hub/
  paper_repository.json    ← Full data including complete Claude analysis
  paper_repository.csv     ← Spreadsheet-friendly summary view
  batch_template.csv       ← Template for batch uploads
```

Use the **Repository** tab to:
- Browse all analyzed papers
- Filter by recommendation (INCLUDE / EXCLUDE / MANUAL_REVIEW)
- Search by any text
- Double-click a row to see the full analysis JSON

---

## Analysis Criteria

Papers are evaluated against three criteria from the GenAI Evidence Hub rubric:

| # | Criterion | Description |
|---|-----------|-------------|
| 1 | GenAI Used | Paper uses a generative AI model in research (post-2020) |
| 2 | Relevant Assessment Domain | Item generation, formative feedback, automated scoring, or multimodal inferences |
| 3 | Quality Assurance | Sufficient methodological detail and evaluation metrics |

**Decisions:**
- **INCLUDE** — All three criteria met
- **EXCLUDE** — Any criterion not met, pre-2022 paper, or non-English
- **MANUAL_REVIEW** — Borderline or ambiguous cases

Each result includes:
- Per-criterion verdict (YES / NO / UNCLEAR)
- Reasoning, supporting text, and page/section references
- Confidence level (High / Medium / Low)
- Key decision factors and additional notes
