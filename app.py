"""
app.py  --  Flask web server for the Essay Grader Pipeline
Reuses all stage functions from pipeline.py directly.
Run:  python app.py
Then open:  http://localhost:5000
"""

import json
import os
import sys

# Make sure pipeline.py is importable from the same folder
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, render_template, request, Response, stream_with_context
from pipeline import stage1_understand, stage2_reason, stage3_produce, stage4_critique

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/grade", methods=["POST"])
def grade():
    """
    Streams pipeline progress back to the browser as Server-Sent Events (SSE).
    Each event is a JSON object: { "stage": 1, "type": "output", "data": {...} }
    """
    essay  = request.form.get("essay", "").strip()
    rubric = request.form.get("rubric", "").strip()

    if not essay or not rubric:
        return {"error": "Essay and rubric are both required."}, 400

    def generate():
        def send(stage: int, type_: str, data):
            payload = json.dumps({"stage": stage, "type": type_, "data": data})
            yield f"data: {payload}\n\n"

        try:
            # Stage 1
            yield from send(1, "status", "Reading essay and parsing rubric...")
            brief = stage1_understand(essay, rubric)
            yield from send(1, "output", brief)

            # Stage 2
            yield from send(2, "status", "Scoring each criterion step by step...")
            decision = stage2_reason(brief)
            yield from send(2, "output", decision)

            # Stage 3
            yield from send(3, "status", "Writing student feedback note...")
            feedback = stage3_produce(brief, decision)
            yield from send(3, "output", {"feedback": feedback})

            # Stage 4
            yield from send(4, "status", "Running quality check on feedback...")
            critique = stage4_critique(feedback, decision)
            final_feedback = critique.get("revised_feedback", feedback)
            critique["final_feedback"] = final_feedback
            yield from send(4, "output", critique)

            # Done
            yield from send(0, "done", {
                "grade":      decision.get("letter_grade", "?"),
                "percentage": decision.get("percentage", 0),
                "feedback":   final_feedback,
            })

        except Exception as exc:
            yield from send(0, "error", str(exc))

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    print("\n  Essay Grader running at  http://localhost:5000\n")
    app.run(debug=True, threaded=True)