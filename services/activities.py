# services/activities.py
import uuid
from typing import List, Dict, Any, Optional
from db import insert_activity, get_activity, list_activities, insert_participant, insert_submission, leaderboard

def gen_join_code() -> str:
    return uuid.uuid4().hex[:6].upper()

def create_activity(conn, payload: Dict[str, Any]) -> str:
    # ensure unique join code (simple retry loop)
    for _ in range(5):
        code = gen_join_code()
        existing = get_activity(conn, code)
        if not existing:
            insert_activity(conn, code, payload["title"], payload["instruction"], float(payload["max_score"]), payload["criteria"])
            return code
    raise RuntimeError("Failed to generate unique join code")

def fetch_activity(conn, join_code: str) -> Optional[Dict[str, Any]]:
    return get_activity(conn, join_code)

def add_participant_to_activity(conn, join_code: str, name: str, section: str):
    insert_participant(conn, join_code, name, section)

def save_student_submission(conn, record: Dict[str, Any]):
    insert_submission(conn, record)

def leaderboard_for(conn, join_code: str) -> List[Dict[str, Any]]:
    return leaderboard(conn, join_code)

def recent_activities(conn, limit: int = 100) -> List[Dict[str, Any]]:
    return list_activities(conn, limit=limit)
