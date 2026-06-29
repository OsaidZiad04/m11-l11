"""RAG smoke evaluator -- 3 pre-shipped questions, binary PASS/FAIL per question.

The Lab smoke evaluator proves the grounding-check logic that the Integration's
RAG grounding-rate harness scales up. It is binary by design (PASS/FAIL per
question, exit 0 iff all PASS); it does not aggregate a rate, and it does NOT
apply decline-exclusion -- the three smoke questions are all answerable
against the seeded fixtures, so a decline at the Lab tier is a defect.

Grounding-check methodology (Lab smoke):

  A response is grounded iff (a) response.citations has length >= 1 AND
  (b) every chunk_id in response.citations is present in the candidate set
  returned by the retrieval call for the same question. The Lab smoke does
  NOT apply decline-exclusion (the Lab's 3 questions are all answerable
  against the seeded Weaviate; decline is not in scope at the Lab tier).

The same paragraph appears in the published Applied Lab page so the
documented methodology and the code that scores against it stay in sync.
"""

import json
import os
import sys
from typing import Any

import httpx


API_URL = os.environ.get("API_URL", "http://localhost:8000")


def _extract_chunk_id(item: Any) -> str | None:
    """Extract a chunk_id from a citation-like or retrieved-like object."""
    if isinstance(item, str):
        return item

    if isinstance(item, dict):
        value = item.get("chunk_id")
        if isinstance(value, str):
            return value

    return None


def score_grounding(response: dict, candidate_ids) -> bool:
    """Return True iff `response` is grounded per the Lab smoke methodology.

    `response` is the JSON body returned by POST /rag/answer.
    `candidate_ids` is the set of chunk_ids returned for the same question.
    """
    citations = response.get("citations", [])

    if not citations:
        return False

    cited_chunk_ids = [_extract_chunk_id(citation) for citation in citations]

    if any(chunk_id is None for chunk_id in cited_chunk_ids):
        return False

    return all(chunk_id in candidate_ids for chunk_id in cited_chunk_ids)


def evaluate_question(question: dict) -> bool:
    """Issue one POST /rag/answer; return True iff the response is grounded."""
    api_url = API_URL.rstrip("/")
    payload = {
        "question": question["question"],
        "k": question.get("k", 4),
    }

    try:
        response = httpx.post(
            f"{api_url}/rag/answer",
            json=payload,
            timeout=60.0,
        )
        response.raise_for_status()
        response_body = response.json()
    except Exception as exc:
        question_id = question.get("question_id", "unknown")
        print(f"ERROR {question_id}: {exc}", file=sys.stderr)
        return False

    retrieved = response_body.get("retrieved", [])
    candidate_ids = {
        chunk["chunk_id"]
        for chunk in retrieved
        if isinstance(chunk, dict) and isinstance(chunk.get("chunk_id"), str)
    }

    return score_grounding(response_body, candidate_ids)


def main() -> int:
    """Iterate the three smoke questions, print PASS/FAIL, return 0 iff all PASS."""
    fixture_path = os.path.join(os.path.dirname(__file__), "data", "rag_smoke.json")

    with open(fixture_path, encoding="utf-8") as fh:
        questions = json.load(fh)

    all_passed = True

    for index, question in enumerate(questions, start=1):
        question_id = question.get("question_id", f"q{index}")
        passed = evaluate_question(question)

        status = "PASS" if passed else "FAIL"
        print(f"{status} {question_id}")

        if not passed:
            all_passed = False

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())