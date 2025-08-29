# db.py
from typing import Optional, Dict, Any, List
import json
import snowflake.connector  # type: ignore
from config import AppConfig
from tenacity import retry, stop_after_attempt, wait_exponential

_conn_cache = {}

def _key(cfg: AppConfig) -> str:
    return "|".join([cfg.SF_ACCOUNT, cfg.SF_USER, cfg.SF_DATABASE, cfg.SF_SCHEMA, cfg.SF_WAREHOUSE])

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def get_snowflake_conn(cfg: AppConfig):
    key = _key(cfg)
    if key in _conn_cache:
        return _conn_cache[key]
    conn = snowflake.connector.connect(
        account=cfg.SF_ACCOUNT,
        user=cfg.SF_USER,
        password=cfg.SF_PASSWORD,
        warehouse=cfg.SF_WAREHOUSE,
        database=cfg.SF_DATABASE,
        schema=cfg.SF_SCHEMA,
        client_session_keep_alive=True,
    )
    _conn_cache[key] = conn
    return conn

def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ACTIVITIES (
                ID STRING DEFAULT UUID_STRING(),
                JOIN_CODE STRING,
                TITLE STRING,
                INSTRUCTION STRING,
                MAX_SCORE FLOAT,
                CRITERIA VARIANT,
                CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS PARTICIPANTS (
                ID STRING DEFAULT UUID_STRING(),
                JOIN_CODE STRING,
                STUDENT_NAME STRING,
                SECTION STRING,
                CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS SUBMISSIONS (
                ID STRING DEFAULT UUID_STRING(),
                TS TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                JOIN_CODE STRING,
                STUDENT_NAME STRING,
                SECTION STRING,
                LANGUAGE STRING,
                CODE STRING,
                AI_MODEL STRING,
                TOTAL_SCORE FLOAT,
                FEEDBACK VARIANT
            )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS MODULES (
            ID STRING DEFAULT UUID_STRING(),
            TITLE STRING,
            SUBJECT STRING,
            LEVEL STRING,
            DURATION STRING,
            LEARNING_OUTCOMES VARIANT,
            LESSONS VARIANT,
            ACTIVITIES VARIANT,
            RUBRIC VARIANT,
            RESOURCES VARIANT,
            ANSWERS VARIANT,
            RAW_JSON VARIANT,
            CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """)

def insert_activity(conn, join_code: str, title: str, instruction: str, max_score: float, criteria: List[Dict[str, Any]]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ACTIVITIES (JOIN_CODE, TITLE, INSTRUCTION, MAX_SCORE, CRITERIA) "
            "SELECT %s, %s, %s, %s, PARSE_JSON(%s)",
            (join_code, title, instruction, float(max_score), json.dumps(criteria)),
        )
    conn.commit()

def get_activity(conn, join_code: str) -> Optional[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT TITLE, INSTRUCTION, MAX_SCORE, CRITERIA, CREATED_AT "
            "FROM ACTIVITIES WHERE JOIN_CODE = %s ORDER BY CREATED_AT DESC LIMIT 1",
            (join_code,),
        )
        row = cur.fetchone()
    if not row:
        return None
    title, instruction, max_score, criteria, created_at = row
    if isinstance(criteria, str):
        try:
            criteria = json.loads(criteria)
        except Exception:
            criteria = []
    return {
        "join_code": join_code,
        "title": title,
        "instruction": instruction,
        "max_score": float(max_score or 100.0),
        "criteria": criteria,
        "created_at": str(created_at),
    }

def list_activities(conn, limit: int = 100) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT JOIN_CODE, TITLE, MAX_SCORE, CREATED_AT FROM ACTIVITIES ORDER BY CREATED_AT DESC LIMIT {int(limit)}"
        )
        rows = cur.fetchall()
        if not rows:
            return []
        keys = [c[0] for c in cur.description]
        return [dict(zip(keys, r)) for r in rows]

def insert_participant(conn, join_code: str, name: str, section: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO PARTICIPANTS (JOIN_CODE, STUDENT_NAME, SECTION) SELECT %s, %s, %s",
            (join_code, name, section),
        )
    conn.commit()

def insert_submission(conn, record: Dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO SUBMISSIONS
            (JOIN_CODE, STUDENT_NAME, SECTION, LANGUAGE, CODE, AI_MODEL, TOTAL_SCORE, FEEDBACK)
            SELECT %s, %s, %s, %s, %s, %s, %s, PARSE_JSON(%s)
            """,
            (
                record["join_code"],
                record["student_name"],
                record["section"],
                record["language"],
                record["code"],
                record["ai_model"],
                record["total_score"],
                json.dumps(record["feedback_json"]),
            ),
        )
    conn.commit()

def leaderboard(conn, join_code: str) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT STUDENT_NAME, SECTION, TOTAL_SCORE, AI_MODEL, TS
            FROM SUBMISSIONS
            WHERE JOIN_CODE = %s
            ORDER BY TOTAL_SCORE DESC, TS ASC
            """,
            (join_code,),
        )
        rows = cur.fetchall()
        keys = [c[0] for c in cur.description]
        return [dict(zip(keys, r)) for r in rows]

def insert_module(conn, record: Dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO MODULES
            (TITLE, SUBJECT, LEVEL, DURATION, LEARNING_OUTCOMES, LESSONS, ACTIVITIES, RUBRIC, RESOURCES, ANSWERS, RAW_JSON)
            SELECT %s, %s, %s, %s,
                   PARSE_JSON(%s), PARSE_JSON(%s), PARSE_JSON(%s), PARSE_JSON(%s), PARSE_JSON(%s), PARSE_JSON(%s), PARSE_JSON(%s)
            """,
            (
                record.get("title"),
                record.get("subject"),
                record.get("level"),
                record.get("duration"),
                json.dumps(record.get("learning_outcomes", [])),
                json.dumps(record.get("lessons", [])),
                json.dumps(record.get("activities", [])),
                json.dumps(record.get("rubric", [])),
                json.dumps(record.get("resources", [])),
                json.dumps(record.get("answers", [])),
                json.dumps(record.get("raw_json", {})),
            ),
        )
    conn.commit()

def list_modules(conn, limit: int = 50) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT TITLE, SUBJECT, LEVEL, DURATION, CREATED_AT
            FROM MODULES
            ORDER BY CREATED_AT DESC
            LIMIT {int(limit)}
            """
        )
        rows = cur.fetchall()
        if not rows:
            return []
        keys = [c[0] for c in cur.description]
        return [dict(zip(keys, r)) for r in rows]


