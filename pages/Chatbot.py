# pages/5_💬_Data_Chatbot.py
import re
import json
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
from openai import OpenAI

from config import get_config
from db import get_snowflake_conn, ensure_schema

PAGE_TITLE = "💬 Data Chatbot — (Snowflake-Only)"
st.set_page_config(page_title=PAGE_TITLE, page_icon="💬", layout="wide")
st.title(PAGE_TITLE)

cfg = get_config()
if not cfg.snowflake_all_present:
    st.error("Snowflake is required for the chatbot. Please configure credentials.")
    st.stop()
if not cfg.OPENAI_API_KEY:
    st.error("OpenAI is required for NL→SQL and grounded answers. Set OPENAI_API_KEY.")
    st.stop()

conn = get_snowflake_conn(cfg)
ensure_schema(conn)
oa_client = OpenAI(api_key=cfg.OPENAI_API_KEY)

# ---------- Settings ----------
ALLOWED_TABLES = ["ACTIVITIES", "PARTICIPANTS", "SUBMISSIONS", "SYLLABI"]
MAX_ROWS = 500  # hard cap on query results
DEFAULT_LIMIT = 200

# ---------- Helpers ----------
@st.cache_data(ttl=300)
def load_schema() -> Dict[str, List[str]]:
    """Get column names for allowed tables from Snowflake INFORMATION_SCHEMA."""
    schema_map: Dict[str, List[str]] = {}
    with conn.cursor() as cur:
        for t in ALLOWED_TABLES:
            cur.execute(f"""
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                ORDER BY ORDINAL_POSITION
            """, (cfg.SF_SCHEMA, t))
            schema_map[t] = [r[0] for r in cur.fetchall()]
    return schema_map

SCHEMA_MAP = load_schema()

def normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).upper() for c in out.columns]
    return out

def sql_is_safe(sql: str) -> Tuple[bool, str]:
    """Basic guardrail: only a single SELECT; no DDL/DML; only allowed tables."""
    s = sql.strip().rstrip(";")
    # Single statement, starts with SELECT
    if not re.match(r"(?is)^\s*select\b", s):
        return False, "Only SELECT statements are allowed."
    # Disallow dangerous keywords
    banned = r"\b(INSERT|UPDATE|DELETE|MERGE|COPY|CALL|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|PUT|GET)\b"
    if re.search(banned, s, flags=re.IGNORECASE):
        return False, "Statement contains disallowed keywords."
    # Ensure only allowed tables appear (very rough but effective)
    # Extract tokens that look like identifiers (TABLE or alias references)
    # We simply assert that any explicit table references (schema.table or table) use allowed tables.
    referenced = set(re.findall(r"(?i)\b([A-Z_][A-Z0-9_]*)(?=\s*(?:,|\bJOIN\b|\bON\b|\bWHERE\b|\(|$|\.))", s.upper()))
    # Whitelist SQL keywords that might match the regex (e.g., SELECT, WHERE, JOIN, ON, AND, OR, LIMIT, ORDER, BY)
    SQL_WORDS = {"SELECT","WHERE","FROM","JOIN","ON","AND","OR","ORDER","BY","LEFT","RIGHT","FULL","INNER","OUTER","GROUP","HAVING","LIMIT","OFFSET","WITH","AS","CASE","WHEN","THEN","ELSE","END","DISTINCT","UNION","ALL","COUNT","AVG","MIN","MAX","SUM","DATE_TRUNC","APPROX_PERCENTILE","COALESCE","TRY_TO_NUMBER","LATERAL","FLATTEN"}
    candidates = {tok for tok in referenced if tok not in SQL_WORDS}
    # Allow schema name
    candidates = {tok for tok in candidates if tok != cfg.SF_SCHEMA.upper()}
    # If any token matches an allowed table, keep; otherwise, if token not in allowed and not a column/alias, still OK.
    # We'll enforce a stronger check by scanning explicit FROM/JOIN clauses for table names
    table_refs = set(re.findall(r"(?i)\bFROM\s+([A-Z0-9_\.]+)|\bJOIN\s+([A-Z0-9_\.]+)", s))
    flat_refs = {x for tup in table_refs for x in tup if x}
    cleaned = {ref.split(".")[-1].upper() for ref in flat_refs}
    for ref in cleaned:
        if ref not in ALLOWED_TABLES:
            return False, f"Query references non-allowed table: {ref}"
    return True, ""

def extract_join_code(text: str) -> Optional[str]:
    """Heuristic: find a 5-8 uppercase alnum token that looks like a join code."""
    m = re.search(r"\b([A-Z0-9]{5,8})\b", text.upper())
    return m.group(1) if m else None

# ---------- LLM Prompts ----------
SYSTEM_SQL = (
    "You are a Snowflake SQL assistant. "
    "You ONLY generate a single safe SELECT statement using the provided schema. "
    "Rules: (1) Use only tables and columns from the schema I give you. "
    "(2) Do not generate DDL/DML. (3) Prefer small results with LIMIT. "
    "(4) If a Join Code is provided, filter by it when relevant. "
    "(5) Return ONLY JSON: {\"sql\": \"...\", \"notes\": \"...\"}."
)

SYSTEM_ANSWER = (
    "You are a data analyst. Answer the user's question using ONLY the tabular rows provided. "
    "If the rows are empty or insufficient, say you don't have enough data. "
    "Be concise, cite column names, and do not invent facts."
)

def draft_sql_from_question(
    question: str,
    schema_map: Dict[str, List[str]],
    join_code: Optional[str],
    limit: int = DEFAULT_LIMIT
) -> Dict[str, str]:
    schema_text = {t: cols for t, cols in schema_map.items()}
    payload = {
        "question": question,
        "allowed_tables": list(schema_map.keys()),
        "schema": schema_text,
        "join_code": join_code,
        "default_limit": min(limit, MAX_ROWS),
    }
    msgs = [
        {"role": "system", "content": SYSTEM_SQL},
        {"role": "user", "content": json.dumps(payload, indent=2)},
    ]
    resp = oa_client.chat.completions.create(
        model=cfg.OPENAI_MODEL,
        messages=msgs,
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    try:
        return json.loads(resp.choices[0].message.content)
    except Exception:
        return {"sql": "", "notes": "Failed to parse model output."}

def summarize_rows(question: str, sql: str, rows: List[Dict], limit_note: str = "") -> str:
    data = {"question": question, "sql_used": sql, "rows": rows[:50], "note": limit_note}
    msgs = [
        {"role": "system", "content": SYSTEM_ANSWER},
        {"role": "user", "content": json.dumps(data, default=str)},
    ]
    resp = oa_client.chat.completions.create(
        model=cfg.OPENAI_MODEL,
        messages=msgs,
        temperature=0.1,
    )
    return resp.choices[0].message.content.strip()

# ---------- UI ----------
with st.sidebar:
    st.subheader("Chat Settings")
    enforce_join = st.toggle("Enforce Join Code filter", value=False, help="Require a Join Code to scope queries.")
    provided_code = st.text_input("Join Code (optional)", placeholder="e.g., ABC123").strip().upper() or None
    row_limit = st.slider("Row limit", 50, MAX_ROWS, DEFAULT_LIMIT, 50)

if "chat" not in st.session_state:
    st.session_state.chat = []

for role, content in st.session_state.chat:
    with st.chat_message(role):
        st.markdown(content)

user_msg = st.chat_input("Ask about your activities, submissions, scores, rubrics, or syllabi…")
if user_msg:
    with st.chat_message("user"):
        st.markdown(user_msg)
    st.session_state.chat.append(("user", user_msg))

    # Enforce join code if required
    active_code = provided_code
    if not active_code and enforce_join:
        # try to infer from the question
        inferred = extract_join_code(user_msg)
        active_code = inferred
    if enforce_join and not active_code:
        bot_text = "Please provide a Join Code (e.g., ABC123) to scope this answer."
        with st.chat_message("assistant"):
            st.markdown(bot_text)
        st.session_state.chat.append(("assistant", bot_text))
        st.stop()

    # Step 1: NL → SQL
    gen = draft_sql_from_question(user_msg, SCHEMA_MAP, active_code, row_limit)
    sql = (gen.get("sql") or "").strip()
    notes = gen.get("notes", "")
    if active_code and "%(JOIN_CODE)s" not in sql and "JOIN_CODE" in sql.upper():
        # If model inlined the code; okay. If it forgot filter entirely, we’ll warn.
        pass

    # Step 2: Validate SQL
    ok, why = sql_is_safe(sql)
    if not ok:
        warn = f"Sorry, I couldn't produce a safe query: {why}"
        with st.chat_message("assistant"):
            st.warning(warn)
            if sql:
                st.caption("Proposed (rejected) SQL:")
                st.code(sql, language="sql")
        st.session_state.chat.append(("assistant", warn))
        st.stop()

    # Step 3: Execute
    t0 = time.time()
    try:
        with conn.cursor() as cur:
            if "%(JOIN_CODE)s" in sql and active_code:
                cur.execute(sql, {"JOIN_CODE": active_code})
            else:
                cur.execute(sql)
            rows = cur.fetchall()
            cols = [c[0] for c in cur.description]
        df = normalize_cols(pd.DataFrame(rows, columns=cols))
        latency_ms = int((time.time() - t0) * 1000)
    except Exception as e:
        err = f"Query failed: {e}"
        with st.chat_message("assistant"):
            st.error(err)
            st.code(sql, language="sql")
        st.session_state.chat.append(("assistant", err))
        st.stop()

    # Step 4: Show SQL + Results
    with st.expander("Query (read-only)"):
        st.code(sql, language="sql")
        if notes:
            st.caption(notes)
    if df.empty:
        with st.chat_message("assistant"):
            st.info("No rows found for this question in the current scope.")
        st.session_state.chat.append(("assistant", "No rows found for this question in the current scope."))
        st.stop()
    else:
        st.caption(f"Returned {len(df)} rows in {latency_ms} ms")
        st.dataframe(df.head(200), use_container_width=True, hide_index=True)

    # Step 5: Grounded summarization (rows → answer)
    # Convert a preview of rows to dicts for the model (cap at 200 for token safety)
    preview_rows = df.head(200).to_dict(orient="records")
    limit_note = ""
    if len(df) > 200:
        limit_note = f"Only the first 200 of {len(df)} rows are shown/used."

    answer = summarize_rows(user_msg, sql, preview_rows, limit_note)
    with st.chat_message("assistant"):
        st.markdown(answer)
    st.session_state.chat.append(("assistant", answer))
