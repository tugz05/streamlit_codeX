# services/module_gen.py
import json
from typing import List, Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential
from openai import OpenAI

def _build_prompt(
    subject: str,
    title: str,
    level: str,
    duration: str,
    outcomes: List[str],
    num_lessons: int,
    constraints: str
) -> list[dict]:
    system = (
        "You are an expert instructional designer. "
        "Generate a teaching module in JSON only with sections: "
        "title, learning_outcomes[], lessons[], activities[], rubric[], resources[], answers[]. "
        "Each lesson: {title, summary}. "
        "Each activity: {type, description}. "
        "Each rubric row: {criterion, weight, description}. "
        "Do not include any extra fields."
    )

    # Keep example JSON out of f-string
    example = (
        '{"title":"...",'
        '"learning_outcomes":["..."],'
        '"lessons":[{"title":"...","summary":"..."}],'
        '"activities":[{"type":"quiz","description":"..."}],'
        '"rubric":[{"criterion":"Correctness","weight":0.5,"description":"..." }],'
        '"resources":["..."],'
        '"answers":["..."]}'
    )

    user = (
        f"Subject: {subject}\n"
        f"Module Title: {title}\n"
        f"Level: {level}\n"
        f"Duration: {duration}\n"
        f"Target Outcomes:\n- " + "\n- ".join(outcomes) + "\n\n"
        f"Number of lessons: {num_lessons}\n"
        f"Constraints/Preferences: {constraints or 'None'}\n\n"
        "Return STRICT JSON (no markdown). "
        "Weights in rubric must sum to ~1.0.\n"
        "JSON shape example (for structure only, not content):\n" + example
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]

def _parse_json(text: str) -> Dict[str, Any]:
    try:
        i, j = text.find("{"), text.rfind("}")
        if i != -1 and j != -1 and j > i:
            return json.loads(text[i:j+1])
        return json.loads(text)
    except Exception:
        return {"title": "", "learning_outcomes": [], "lessons": [], "activities": [], "rubric": [], "resources": [], "answers": []}

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def generate_module(
    api_key: str,
    model: str,
    subject: str,
    title: str,
    level: str,
    duration: str,
    outcomes: List[str],
    num_lessons: int,
    constraints: str
) -> Dict[str, Any]:
    client = OpenAI(api_key=api_key)
    messages = _build_prompt(subject, title, level, duration, outcomes, num_lessons, constraints)
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.4,
        response_format={"type": "json_object"},
    )
    data = _parse_json(resp.choices[0].message.content)

    # Normalize rubric weights if provided
    rows = data.get("rubric", [])
    if isinstance(rows, list) and rows:
        total = sum(float(r.get("weight", 0)) for r in rows) or 1.0
        for r in rows:
            try:
                r["weight"] = float(r.get("weight", 0)) / total
            except Exception:
                r["weight"] = 0.0

    return data
