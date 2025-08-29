# services/syllabus_gen.py
import json
from typing import Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential
from openai import OpenAI

def _build_prompt(payload: Dict[str, Any]) -> list[dict]:
    """Build a strict, JSON-only prompt for syllabus creation."""
    system = (
        "You are an expert instructional designer. "
        "Create a complete, practical course syllabus aligned with best practices (backward design, scaffolding, assessment alignment). "
        "Return ONLY valid JSON with the schema described below."
    )

    schema_text = {
        "title": "string",
        "level": "string",   # e.g., Introductory, Intermediate, Advanced
        "weeks": "integer",
        "modality": "string",  # e.g., In-person, Online, Hybrid
        "target_learners": "string",
        "prerequisites": "string",
        "learning_outcomes": ["string"],
        "grading_breakdown": [
            {"component": "string", "weight": "number"}
        ],
        "policies": {
            "late_policy": "string",
            "attendance_policy": "string",
            "academic_integrity": "string",
            "communication_policy": "string"
        },
        "resources": {
            "required": ["string"],
            "recommended": ["string"]
        },
        "schedule": [
            {
                "week": "integer",
                "topic": "string",
                "objectives": ["string"],
                "content": ["string"],
                "activities": ["string"],
                "assignments": ["string"],
                "assessment": "string"
            }
        ],
        "rubrics": [
            {
                "name": "string",
                "criteria": [
                    {"criterion": "string", "levels": [
                        {"level": "Exemplary", "descriptor": "string"},
                        {"level": "Proficient", "descriptor": "string"},
                        {"level": "Developing", "descriptor": "string"},
                        {"level": "Beginning", "descriptor": "string"}
                    ]}
                ]
            }
        ]
    }

    example = (
        '{"title":"...", "level":"...", "weeks":12, "modality":"Hybrid", '
        '"target_learners":"...", "prerequisites":"...", '
        '"learning_outcomes":["...","..."], '
        '"grading_breakdown":[{"component":"Projects","weight":40},{"component":"Quizzes","weight":20},'
        '{"component":"Midterm","weight":20},{"component":"Final","weight":20}], '
        '"policies":{"late_policy":"...","attendance_policy":"...","academic_integrity":"...","communication_policy":"..."}, '
        '"resources":{"required":["..."],"recommended":["..."]}, '
        '"schedule":[{"week":1,"topic":"...","objectives":["..."],"content":["..."],"activities":["..."],"assignments":["..."],"assessment":"..."}], '
        '"rubrics":[{"name":"Project Rubric","criteria":[{"criterion":"Correctness","levels":[{"level":"Exemplary","descriptor":"..."},{"level":"Proficient","descriptor":"..."},{"level":"Developing","descriptor":"..."},{"level":"Beginning","descriptor":"..."}]}]}]}'
    )

    user = (
        "Create a course syllabus with this input (JSON):\n"
        + json.dumps(payload, indent=2)
        + "\n\nSchema (for reference only):\n"
        + json.dumps(schema_text, indent=2)
        + "\n\nOutput: Respond ONLY with a single JSON object exactly following the schema. Example format:\n"
        + example
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

def _parse_json(text: str) -> dict:
    try:
        i, j = text.find("{"), text.rfind("}")
        if i != -1 and j != -1 and j > i:
            return json.loads(text[i:j+1])
        return json.loads(text)
    except Exception:
        return {"error": "Parsing failed"}

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def generate_syllabus(client: OpenAI, model: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    messages = _build_prompt(payload)
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    return _parse_json(resp.choices[0].message.content)

def syllabus_to_markdown(syl: Dict[str, Any]) -> str:
    """Pretty Markdown export."""
    def bullet_list(items):
        return "\n".join([f"- {x}" for x in items]) if items else "-"

    md = []
    md.append(f"# {syl.get('title','Untitled Course')}")
    md.append("")
    md.append(f"**Level:** {syl.get('level','N/A')}  ")
    md.append(f"**Weeks:** {syl.get('weeks','N/A')}  ")
    md.append(f"**Modality:** {syl.get('modality','N/A')}  ")
    md.append(f"**Target Learners:** {syl.get('target_learners','')}  ")
    md.append(f"**Prerequisites:** {syl.get('prerequisites','')}  ")
    md.append("")
    md.append("## Learning Outcomes")
    md.append(bullet_list(syl.get("learning_outcomes", [])))
    md.append("")
    md.append("## Grading Breakdown")
    for gb in syl.get("grading_breakdown", []):
        md.append(f"- **{gb.get('component','')}**: {gb.get('weight',0)}%")
    md.append("")
    md.append("## Policies")
    pol = syl.get("policies", {}) or {}
    md.append(f"- **Late Policy:** {pol.get('late_policy','')}")
    md.append(f"- **Attendance Policy:** {pol.get('attendance_policy','')}")
    md.append(f"- **Academic Integrity:** {pol.get('academic_integrity','')}")
    md.append(f"- **Communication Policy:** {pol.get('communication_policy','')}")
    md.append("")
    md.append("## Resources")
    res = syl.get("resources", {}) or {}
    md.append("**Required**")
    md.append(bullet_list(res.get("required", [])))
    md.append("**Recommended**")
    md.append(bullet_list(res.get("recommended", [])))
    md.append("")
    md.append("## Weekly Schedule")
    for wk in syl.get("schedule", []):
        md.append(f"### Week {wk.get('week','?')}: {wk.get('topic','')}")
        md.append("**Objectives**")
        md.append(bullet_list(wk.get("objectives", [])))
        md.append("**Content**")
        md.append(bullet_list(wk.get("content", [])))
        md.append("**Activities**")
        md.append(bullet_list(wk.get("activities", [])))
        md.append("**Assignments**")
        md.append(bullet_list(wk.get("assignments", [])))
        md.append(f"**Assessment:** {wk.get('assessment','')}")
        md.append("")
    rubrics = syl.get("rubrics", [])
    if rubrics:
        md.append("## Rubrics")
        for rb in rubrics:
            md.append(f"### {rb.get('name','Rubric')}")
            for crit in rb.get("criteria", []):
                md.append(f"- **{crit.get('criterion','')}**")
                for lvl in crit.get("levels", []):
                    md.append(f"  - *{lvl.get('level','')}*: {lvl.get('descriptor','')}")
    return "\n".join(md)
