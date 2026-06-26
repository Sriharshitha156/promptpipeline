# Essay Grader Pipeline
### Day 2 Homework — The Prompt Pipeline

---

## What this builds

A **4-stage LLM prompt pipeline** that takes a short essay + a grading rubric
and produces structured scores plus a polished student-facing feedback note.

```
[Essay + Rubric]
      │
      ▼
┌─────────────────────────────────────────────────────┐
│  Stage 1 · UNDERSTAND  (role + structured output)   │
│  Extracts essay metadata + parses rubric criteria   │
│  → returns JSON                                     │
└─────────────────────┬───────────────────────────────┘
                      │ JSON
                      ▼
┌─────────────────────────────────────────────────────┐
│  Stage 2 · REASON  (chain-of-thought)               │
│  Scores each criterion step-by-step, assigns grade  │
│  → returns JSON                                     │
└─────────────────────┬───────────────────────────────┘
                      │ JSON
                      ▼
┌─────────────────────────────────────────────────────┐
│  Stage 3 · PRODUCE  (goal-oriented + constraints)   │
│  Writes student-facing feedback, 120–200 words      │
│  → returns plain text                               │
└─────────────────────┬───────────────────────────────┘
                      │ text + JSON
                      ▼
┌─────────────────────────────────────────────────────┐
│  Stage 4 · SELF-CHECK  (critic / QA)  [stretch]    │
│  Validates feedback against constraints, revises    │
│  if needed → returns final feedback                 │
└─────────────────────────────────────────────────────┘
```

---

## Folder structure

```
essay_grader_pipeline/
├── pipeline.py        ← all code lives here (single file)
├── README.md          ← this file
├── requirements.txt   ← one dependency: requests
├── inputs/            ← (optional) drop .txt essay files here
├── outputs/           ← final feedback notes saved here automatically
└── runs/              ← capture full terminal runs here for submission
```

---

## Setup

### 1 — Install dependency
```bash
pip install requests
```

### 2 — Set your OpenRouter API key
```bash
export OPENROUTER_API_KEY="sk-or-..."
```
Or paste it directly into `pipeline.py` line 12.

### 3 — Run all four inputs
```bash
cd essay_grader_pipeline
python pipeline.py
```

### 4 — Run a single input (e.g. Run 1 only)
```bash
python pipeline.py 1   # 1 · 2 · 3 · 4
```

### 5 — Capture a run for submission
```bash
python pipeline.py 1 | tee runs/run1_strong_essay.txt
```

---

## The four inputs included

| # | Label | Why it's interesting |
|---|-------|----------------------|
| 1 | Strong Essay | Well-argued, cited, should score A/B |
| 2 | Weak Essay | Vague, no evidence, should score D/F |
| 3 | Spanish Essay | Language mismatch — pipeline must detect & handle |
| 4 | Gibberish | Broken input — pipeline must gracefully skip grading |

---

## Techniques used (per stage)

| Stage | Technique | Why |
|-------|-----------|-----|
| 1 | Role prompting + structured output | Gives the model an expert identity; forces JSON |
| 2 | Chain-of-thought | Makes scoring transparent and auditable |
| 3 | Goal-oriented + output constraints | Exact word count, tone, and structure required |
| 4 | Critic / self-check (stretch) | Catches constraint violations before delivery |

---

## Reflection — weakest link

**Stage 2 (REASON)** is the weakest stage. Scoring creative dimensions like
"Style & Clarity" requires subjective judgement that the model approximates
rather than truly measures. Two runs on the same essay can produce scores that
differ by 3–5 points with no change in the prompt. You would know it's weak by
running the same essay five times and computing the variance in `awarded_score`.

**What would fix it:** On Day 4, retrieval could pull anchor essays (exemplars
at A/B/C/D/F) from a knowledge base and include them as few-shot comparisons —
giving the model a concrete calibration scale instead of abstract descriptions.
On Day 6–8, a tool could run a plagiarism/readability API and feed objective
metrics (Flesch score, sentence-length variance) directly into the prompt,
replacing subjective guesswork with measured data.