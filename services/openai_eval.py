# services/openai_eval.py
import json
from typing import List, Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential
from openai import OpenAI

def _build_prompt(code: str, language: str, criteria: List[Dict[str, Any]], instruction: str, max_score: float):
    system = (
        "You are an expert programming instructor and strict grader. "
        "Evaluate the student's submission using ONLY the rubric and instructions. "
        "Return valid JSON with fields: per_criterion[], overall_score(0..100), summary."
    )
    example = (
        '{"per_criterion":[{"criterion":"...", "weight":0.2, "score":87, "comment":"..."}], '
        '"overall_score":88.5, "summary":"..."}.'  # keep as text in instruction
    )
    user = (
        f"Language: {language}\n\n"
        f"Instructions from teacher:\n{instruction}\n\n"
        f"Rubric (criterion, weight):\n{json.dumps(criteria, indent=2)}\n\n"
        f"Max score for activity: {max_score}\n\n"
        f"Student code (fenced):\n```{language}\n{code}\n```\n"
        "Score each criterion 0–100; compute weighted overall_score out of 100.\n"
        "Respond ONLY with JSON:\n" + example
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]

def _parse_json(text: str) -> dict:
    try:
        i, j = text.find("{"), text.rfind("}")
        if i != -1 and j != -1 and j > i:
            return json.loads(text[i:j+1])
        return json.loads(text)
    except Exception:
        return {"per_criterion": [], "overall_score": 0.0, "summary": "Parsing failed."}

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def evaluate_with_openai(client: OpenAI, model: str, *, code: str, language: str, criteria: List[Dict[str, Any]], instruction: str, max_score: float) -> dict:
    total = sum(float(c.get("weight", 0)) for c in criteria) or 1.0
    normalized = [{"criterion": c["criterion"], "weight": float(c["weight"]) / total} for c in criteria]
    messages = _build_prompt(code, language, normalized, instruction, max_score)

    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    data = _parse_json(resp.choices[0].message.content)

    if data.get("per_criterion"):
        w_map = {c["criterion"]: c["weight"] for c in normalized}
        agg = 0.0
        for row in data["per_criterion"]:
            w = row.get("weight", w_map.get(row.get("criterion", ""), 0.0))
            row["weight"] = w
            agg += float(row.get("score", 0.0)) * float(w)
        data["overall_score"] = max(0.0, min(100.0, agg))
    else:
        data["per_criterion"] = normalized
        data["overall_score"] = 0.0
        data["summary"] = data.get("summary", "No feedback returned.")

    data["_scaled_total"] = round((data["overall_score"] / 100.0) * float(max_score), 2)
    return data
