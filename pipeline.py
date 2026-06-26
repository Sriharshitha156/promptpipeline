"""
Essay Grader Pipeline
=====================
A 4-stage prompt pipeline that takes a short essay + rubric and produces:
  Stage 1 . UNDERSTAND  -- extracts essay metadata + rubric criteria into JSON
  Stage 2 . REASON      -- scores each criterion with chain-of-thought justification
  Stage 3 . PRODUCE     -- writes a polished, student-facing feedback note
  Stage 4 . SELF-CHECK  -- critic pass; revises if constraints are violated (stretch)

Each stage is one LLM call. Stages communicate via JSON only.
"""

import os
import sys
import io
import json
import re
import time
import requests
from dotenv import load_dotenv

# =============================================================================
# Windows UTF-8 fix
# Rewrap stdout/stderr so piping to `tee` on Windows never garbles characters.
# =============================================================================
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# =============================================================================
# Load secrets from .env (never committed to Git)
# Priority order:
#   1. .env file in the project folder  <-- recommended, edit this file
#   2. Real environment variable already set in the shell
#   3. Falls back to "YOUR_KEY_HERE" and prints a helpful error at runtime
#
# Setup:
#   copy .env.example .env          (Windows PowerShell)
#   cp .env.example .env            (Mac / Linux)
#   then open .env and paste your key
# =============================================================================
load_dotenv()   # reads .env silently; does nothing if file is missing

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "YOUR_KEY_HERE")
MODEL              = os.environ.get("MODEL", "anthropic/claude-3-haiku")
MAX_JSON_RETRIES   = 3

# =============================================================================
# Terminal colour helpers  (plain ASCII borders -- no Unicode box chars)
# =============================================================================
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def banner(stage: str, colour: str = CYAN) -> None:
    line = "-" * 60
    print(f"\n{colour}{BOLD}{line}")
    print(f"  {stage}")
    print(f"{line}{RESET}\n")

def show(label: str, data, colour: str = GREEN) -> None:
    print(f"{colour}{BOLD}-- {label} --{RESET}")
    if isinstance(data, (dict, list)):
        print(json.dumps(data, indent=2))
    else:
        print(data)
    print()

# =============================================================================
# LLM call
# =============================================================================
def call_llm(prompt: str, temperature: float = 0.3) -> str:
    """Single helper that wraps the OpenRouter /chat/completions endpoint."""
    if OPENROUTER_API_KEY == "YOUR_KEY_HERE":
        raise RuntimeError(
            "No API key found!\n"
            "Set it in PowerShell before running:\n"
            '  $env:OPENROUTER_API_KEY = "sk-or-v1-xxxxxxxxxxxx"\n'
            "Or paste your key directly into pipeline.py line ~40."
        )
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://essay-grader-pipeline",
    }
    body = {
        "model": MODEL,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers=headers,
        json=body,
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()

# =============================================================================
# JSON sanitiser + parse-with-retry
# =============================================================================
def sanitise_json(raw: str) -> str:
    """
    Best-effort cleanup of common model JSON mistakes before parsing:
      1. Strip markdown code fences  (```json ... ```)
      2. Replace Python-style triple-quoted strings with proper JSON strings
      3. Strip any remaining bare backticks
    """
    # 1. strip ``` fences
    text = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()

    # 2. collapse triple-double-quoted blocks -> single JSON string
    def collapse_triple(m: re.Match) -> str:
        inner = m.group(1)
        inner = inner.replace("\\", "\\\\")
        inner = inner.replace('"',  '\\"')
        inner = inner.replace("\n", "\\n")
        inner = inner.replace("\r", "")
        return f'"{inner}"'

    text = re.sub(r'"""(.*?)"""', collapse_triple, text, flags=re.DOTALL)
    return text


def parse_json(raw: str, original_prompt: str, attempt: int = 1) -> dict:
    """
    Parse JSON from model output.  Applies sanitise_json() first.
    On failure re-asks the model with the error -- up to MAX_JSON_RETRIES times.
    """
    cleaned = sanitise_json(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as err:
        if attempt >= MAX_JSON_RETRIES:
            raise ValueError(
                f"[parse_json] Failed after {MAX_JSON_RETRIES} attempts.\n"
                f"Last error : {err}\n"
                f"Raw output :\n{raw}"
            ) from err
        print(f"{YELLOW}[retry {attempt}] JSON parse error: {err} -- re-asking model...{RESET}")
        repair_prompt = (
            f"{original_prompt}\n\n"
            f"Your previous response could not be parsed as JSON.\n"
            f"Error: {err}\n"
            f"Your previous response was:\n{raw}\n\n"
            "Please return ONLY valid JSON -- no markdown, no triple quotes, no prose."
        )
        time.sleep(1)
        raw2 = call_llm(repair_prompt)
        return parse_json(raw2, original_prompt, attempt + 1)


# =============================================================================
# STAGE 1 -- UNDERSTAND
# Technique : Role prompting + structured output
# Input     : raw essay text + rubric string
# Output    : JSON with essay metadata and parsed rubric criteria
# =============================================================================
PROMPT_1 = """\
You are an expert academic analyst. Your job is to read an essay and a grading \
rubric and extract structured information -- nothing more.

ESSAY:
---
{essay}
---

RUBRIC:
---
{rubric}
---

Return ONLY a valid JSON object with this exact shape (no markdown, no prose):
{{
  "essay_metadata": {{
    "word_count": <integer>,
    "apparent_topic": "<one short sentence>",
    "language_detected": "<ISO 639-1 code, e.g. en>",
    "is_readable": <true or false>
  }},
  "rubric_criteria": [
    {{
      "criterion": "<name>",
      "max_score": <integer>,
      "description": "<what this criterion measures>"
    }}
  ],
  "raw_essay": "<the essay text verbatim>",
  "error": null
}}

If the essay is empty, gibberish, or unreadable set "is_readable" to false, \
set "error" to a short explanation, and still fill "rubric_criteria" from the rubric.
"""

def stage1_understand(essay: str, rubric: str) -> dict:
    prompt = PROMPT_1.format(essay=essay, rubric=rubric)
    raw    = call_llm(prompt)
    return parse_json(raw, prompt)


# =============================================================================
# STAGE 2 -- REASON
# Technique : Chain-of-thought (explicit step-by-step scoring)
# Input     : Stage-1 JSON
# Output    : JSON with per-criterion scores + reasoning + overall percentage
# =============================================================================
PROMPT_2 = """\
You are a careful, fair academic grader. Score the essay criterion by criterion, \
thinking step by step before committing to any score.

Structured essay brief from Stage 1:
{brief}

INSTRUCTIONS -- follow in order:
1. Check "is_readable". If false, skip scoring and return an error result.
2. For EACH criterion in "rubric_criteria":
   a. Quote or paraphrase 1-2 relevant passages from the essay.
   b. Compare them to what the criterion description demands.
   c. Assign a score 0 to max_score.
   d. Write a 1-2 sentence justification.
3. Sum all scores and express as a percentage of total possible points.
4. Assign a letter grade: A (>=90%), B (>=75%), C (>=60%), D (>=45%), F (<45%).

Return ONLY valid JSON -- no markdown, no prose outside the JSON:
{{
  "is_readable": <true or false>,
  "error": <null or "reason the essay could not be graded">,
  "scores": [
    {{
      "criterion": "<name>",
      "max_score": <integer>,
      "awarded_score": <integer>,
      "reasoning": "<step-by-step thought>",
      "justification": "<1-2 sentence summary>"
    }}
  ],
  "total_awarded": <integer>,
  "total_possible": <integer>,
  "percentage": <float one decimal place>,
  "letter_grade": "<A|B|C|D|F>"
}}
"""

def stage2_reason(brief: dict) -> dict:
    prompt = PROMPT_2.format(brief=json.dumps(brief, indent=2))
    raw    = call_llm(prompt, temperature=0.2)
    return parse_json(raw, prompt)


# =============================================================================
# STAGE 3 -- PRODUCE
# Technique : Goal-oriented prompting + output constraints
# Input     : Stage-1 JSON + Stage-2 JSON
# Output    : Polished student-facing feedback note (plain text)
# =============================================================================
PROMPT_3 = """\
You are an encouraging but honest academic writing coach. Using the grading \
data below, write a clear constructive feedback note addressed directly to the student.

Essay brief (Stage 1):
{brief}

Grading results (Stage 2):
{decision}

CONSTRAINTS -- follow every one:
- Address the student as "you" (second person).
- Open with one sentence stating the overall grade and percentage.
- One short paragraph (3-5 sentences) of genuine strengths.
- One short paragraph (3-5 sentences) of the most important areas to improve.
- Close with one motivating sentence.
- Total length: 120-200 words. No bullet points. No headers.
- Do NOT invent scores or criteria not in the grading data.
- If the essay was unreadable, write a brief kind note asking the student \
  to resubmit -- do NOT mention any score or percentage.
"""

def stage3_produce(brief: dict, decision: dict) -> str:
    prompt = PROMPT_3.format(
        brief=json.dumps(brief, indent=2),
        decision=json.dumps(decision, indent=2),
    )
    return call_llm(prompt, temperature=0.7)


# =============================================================================
# STAGE 4 (stretch) -- SELF-CHECK / CRITIC
# Technique : Role-reversal critique with optional redo
# Input     : Stage-3 feedback text + Stage-2 JSON
# Output    : JSON with pass/fail + optional revised feedback
# =============================================================================
PROMPT_4 = """\
You are a quality-assurance editor for student feedback notes. Check the \
feedback below against the grading data and constraints.

Grading data (Stage 2):
{decision}

Feedback note to review:
---
{feedback}
---

Constraints to verify:
1. States overall grade and percentage in the first sentence.
2. Contains a strengths paragraph and an improvement paragraph.
3. Word count between 120 and 200.
4. No bullet points, no headers.
5. Does not invent scores or criteria.
6. Is encouraging but honest.
7. If the essay was unreadable (is_readable=false), the feedback must NOT \
   mention any score or percentage -- it should only ask the student to resubmit.

Return ONLY a valid JSON object.
Use standard JSON double-quoted strings. Do NOT use triple quotes or markdown.
Use \\n inside strings if you need a line break.
{{
  "passes": <true or false>,
  "violations": ["<list any violated constraints -- empty list if none>"],
  "revised_feedback": "<corrected version if passes=false, otherwise copy original unchanged>"
}}
"""

def stage4_critique(feedback: str, decision: dict) -> dict:
    prompt = PROMPT_4.format(
        decision=json.dumps(decision, indent=2),
        feedback=feedback,
    )
    raw = call_llm(prompt, temperature=0.2)
    return parse_json(raw, prompt)


# =============================================================================
# RUN -- chains all stages and prints every step
# =============================================================================
def run(essay: str, rubric: str, label: str = "Run", enable_stage4: bool = True) -> str:
    """
    Execute the full pipeline on one essay + rubric.
    Prints every stage's input and output so the pipeline is fully inspectable.
    Returns the final feedback string.
    """
    banner(f"PIPELINE START  --  {label}", BOLD)

    # Stage 1
    banner("STAGE 1 -- UNDERSTAND  (role + structured output)", CYAN)
    show("INPUT -- essay (first 200 chars)", essay[:200] + ("..." if len(essay) > 200 else ""))
    show("INPUT -- rubric", rubric)
    brief = stage1_understand(essay, rubric)
    show("OUTPUT -- Stage 1 JSON", brief, GREEN)

    # Stage 2
    banner("STAGE 2 -- REASON  (chain-of-thought scoring)", CYAN)
    show("INPUT -- Stage 1 JSON", brief)
    decision = stage2_reason(brief)
    show("OUTPUT -- Stage 2 JSON", decision, GREEN)

    # Stage 3
    banner("STAGE 3 -- PRODUCE  (goal-oriented + constraints)", CYAN)
    show("INPUT -- Stage 1 JSON", brief)
    show("INPUT -- Stage 2 JSON", decision)
    feedback = stage3_produce(brief, decision)
    show("OUTPUT -- Student Feedback", feedback, GREEN)

    # Stage 4 (stretch)
    if enable_stage4:
        banner("STAGE 4 -- SELF-CHECK  (critic + optional redo)", CYAN)
        show("INPUT -- Stage 3 feedback", feedback)
        show("INPUT -- Stage 2 JSON", decision)
        critique = stage4_critique(feedback, decision)
        show("OUTPUT -- Stage 4 JSON", critique, GREEN)

        final = critique.get("revised_feedback", feedback)
        if not critique.get("passes", True):
            show("WARN: Violations found -- using revised feedback",
                 critique["violations"], YELLOW)
        else:
            show("PASS: Feedback passed QA", "No violations found.", GREEN)
        feedback = final

    banner(
        f"PIPELINE END  --  {label}  --  "
        f"Grade: {decision.get('letter_grade','?')} ({decision.get('percentage','?')}%)",
        BOLD,
    )
    return feedback


# =============================================================================
# INPUTS -- three normal + one broken
# =============================================================================
STANDARD_RUBRIC = """\
- Thesis & Argument (25 pts): Is there a clear, arguable central claim?
- Evidence & Support (25 pts): Does the essay cite relevant examples or facts?
- Organisation & Flow (20 pts): Are ideas logically ordered with clear transitions?
- Style & Clarity (15 pts): Is the writing precise, varied, and readable?
- Grammar & Mechanics (15 pts): Is the essay free of grammatical errors?"""

INPUTS = [
    {
        "label": "Run 1 - Strong Essay",
        "essay": (
            "Social media has fundamentally altered the way young people perceive their "
            "own identity. Unlike previous generations who formed self-image through "
            "face-to-face communities, today's adolescents curate digital personas that "
            "are simultaneously public, permanent, and comparative. Research by Twenge "
            "(2017) links increased smartphone use to rising rates of anxiety and "
            "depression among teenagers, suggesting the comparison culture fostered by "
            "platforms like Instagram is not benign.\n\n"
            "This essay argues that social media's algorithmic design -- optimised for "
            "engagement, not wellbeing -- is the primary driver of identity distortion "
            "in adolescents. The highlight-reel effect, where users post only flattering "
            "moments, creates a systematic gap between perceived peers' lives and one's "
            "own reality. Festinger's social comparison theory (1954) predicts that "
            "upward comparisons erode self-esteem, and modern neuroimaging studies "
            "confirm that receiving fewer likes than expected activates the brain's "
            "threat-response system.\n\n"
            "Schools and parents can counteract these effects through digital literacy "
            "programmes that teach adolescents to recognise algorithmic curation. "
            "Several Scandinavian countries have introduced such curricula with "
            "measurable improvements in students' reported self-esteem. Until platforms "
            "are regulated to prioritise wellbeing over engagement, education remains "
            "the most scalable intervention available."
        ),
        "rubric": STANDARD_RUBRIC,
    },
    {
        "label": "Run 2 - Weak Essay",
        "essay": (
            "Climate change is very bad and everyone knows it. Scientists say it is "
            "happening. The weather is getting hotter and there are more storms. We "
            "should do something about it because the planet is important. People "
            "need to recycle more and drive less. If we don't fix it things will be "
            "very bad in the future. In conclusion climate change is a big problem "
            "and we must solve it."
        ),
        "rubric": STANDARD_RUBRIC,
    },
    {
        "label": "Run 3 - Spanish Essay (language mismatch)",
        "essay": (
            "La inteligencia artificial esta cambiando el mundo de manera profunda. "
            "Desde los asistentes virtuales hasta los vehiculos autonomos, la IA "
            "penetra cada aspecto de la vida moderna. Sin embargo, surgen preguntas "
            "eticas cruciales: quien es responsable cuando un algoritmo discrimina? "
            "Como protegemos la privacidad en la era del aprendizaje automatico?\n\n"
            "Este ensayo sostiene que la regulacion proactiva es indispensable para "
            "garantizar que la IA beneficie a toda la humanidad y no solo a quienes "
            "poseen el capital tecnologico. La Union Europea ha dado el primer paso "
            "con el Reglamento de IA de 2024, pero las democracias emergentes "
            "carecen de marcos equivalentes, creando un arbitraje regulatorio peligroso."
        ),
        "rubric": STANDARD_RUBRIC,
    },
    {
        "label": "Run 4 - BROKEN Gibberish Essay",
        "essay": "asdfjkl; qwerty zxcvbn !!!@@@###",
        "rubric": STANDARD_RUBRIC,
    },
]


# =============================================================================
# MAIN
# =============================================================================
if __name__ == "__main__":
    # optionally run just one:  python pipeline.py 1
    run_index = int(sys.argv[1]) - 1 if len(sys.argv) > 1 else None
    targets   = [INPUTS[run_index]] if run_index is not None else INPUTS

    for inp in targets:
        try:
            result = run(
                essay        = inp["essay"].strip(),
                rubric       = inp["rubric"].strip(),
                label        = inp["label"],
                enable_stage4= True,
            )
            safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", inp["label"])
            out_path  = f"outputs/{safe_name}.txt"
            os.makedirs("outputs", exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(result)
            print(f"{GREEN}Saved -> {out_path}{RESET}\n")
        except Exception as exc:
            print(f"{RED}[ERROR] {inp['label']}: {exc}{RESET}\n")