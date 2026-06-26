# Essay Grader Pipeline

A 4-stage LLM prompt pipeline that grades essays from a short student submission and a rubric, then produces structured scores and student-facing feedback.

The project now includes both:
- a command-line pipeline in [pipeline.py](pipeline.py)
- a Flask web app in [app.py](app.py) with a polished UI in [templates/index.html](templates/index.html)

---

## What the project does

The pipeline works in four stages:

1. Understand
   - Reads the essay and rubric
   - Extracts metadata such as topic, word count, language, and readability
   - Parses the rubric into structured criteria

2. Reason
   - Scores each criterion step by step
   - Assigns a percentage and letter grade

3. Produce
   - Writes concise, student-friendly feedback

4. Self-check
   - Reviews the feedback for constraint violations and revises it if needed

---

## New web app experience

The Flask app provides a browser-based grading flow:
- Paste an essay and rubric
- Click “Grade Essay”
- Watch each stage appear live in the UI as Server-Sent Events stream back from the server
- View the resulting score breakdown, grade badge, and final feedback

Run it with:

```bash
python app.py
```

Then open:

```text
http://localhost:5000
```

---

## Project structure

```text
essay_grader_pipeline/
├── app.py                  # Flask web app and SSE endpoint
├── pipeline.py             # 4-stage prompt pipeline logic
├── templates/
│   └── index.html          # Browser UI for essay submission and live results
├── inputs/                 # Example essay/rubric text files
├── outputs/                # Generated feedback outputs
├── runs/                   # Saved run logs for submission
├── requirements.txt        # Python dependencies
└── README.md               # Project documentation
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set your OpenRouter API key

You can either set it in your shell:

```bash
$env:OPENROUTER_API_KEY="sk-or-..."
```

or place it in a `.env` file in the project folder.

### 3. Run the CLI pipeline

Run all bundled examples:

```bash
python pipeline.py
```

Run a single example input (for example, run 1):

```bash
python pipeline.py 1
```

### 4. Run the web app

```bash
python app.py
```

---

## Included sample inputs

| # | Label | Purpose |
|---|-------|---------|
| 1 | Strong Essay | Well-argued essay that should receive a strong grade |
| 2 | Weak Essay | Vague, unsupported writing that should score poorly |
| 3 | Spanish Essay | Tests language mismatch handling |
| 4 | Gibberish | Tests graceful handling of broken or unreadable input |

---

## Notes

- The CLI pipeline uses the OpenRouter API through [pipeline.py](pipeline.py).
- The web app reuses the same pipeline stages and streams progress to the browser in real time.
- The UI includes a preset rubric button and a live results panel for each stage.

---

## Reflection

The weakest part of the pipeline is Stage 2, where scoring subjective dimensions such as style and clarity can vary between runs. In future iterations, retrieval-based examples or additional objective scoring signals could improve consistency.