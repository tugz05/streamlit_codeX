# pages/3_📊_Analytics.py
import streamlit as st
import pandas as pd
from typing import Optional
from config import get_config
from db import get_snowflake_conn

# Page setup
st.set_page_config(page_title="📊 Analytics — AI Code Activities", page_icon="📊", layout="wide")
st.title("📊 Analytics")

cfg = get_config()
if not cfg.snowflake_all_present:
    st.error("Snowflake is required for analytics. Please configure your Snowflake credentials.")
    st.stop()

conn = get_snowflake_conn(cfg)

# ---------- Helpers ----------
@st.cache_data(ttl=120)
def q(sql: str, join_code: Optional[str] = None) -> pd.DataFrame:
    """Run a SQL query. If join_code is provided and the SQL has a %(JOIN_CODE)s placeholder,
    bind the parameter safely; otherwise execute as-is."""
    with conn.cursor() as cur:
        if join_code is not None and "%(JOIN_CODE)s" in sql:
            cur.execute(sql, {"JOIN_CODE": join_code})
        else:
            cur.execute(sql)
        rows = cur.fetchall()
        cols = [c[0] for c in cur.description]
    return pd.DataFrame(rows, columns=cols)

def norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).upper() for c in df.columns]
    return df

def show_df_or_info(df: pd.DataFrame, *, msg: str, height: int = 380):
    if df.empty:
        st.info(msg)
    else:
        st.dataframe(df, use_container_width=True, height=height)

# ---------- Global filter ----------
with st.expander("Filters", expanded=True):
    join_code = st.text_input("Filter by Join Code (optional)", placeholder="e.g., ABC123").strip().upper()
    st.caption("Leave blank to see platform-wide metrics.")

# ---------- Activity Funnel ----------
st.subheader("Activity Funnel (Joins → Submissions → Graded)")
sql_funnel = """
WITH j AS (
  SELECT JOIN_CODE, COUNT(*) AS joins
  FROM PARTICIPANTS
  GROUP BY JOIN_CODE
),
s AS (
  SELECT JOIN_CODE,
         COUNT(*) AS submissions,
         COUNT_IF(TOTAL_SCORE IS NOT NULL) AS graded
  FROM SUBMISSIONS
  GROUP BY JOIN_CODE
)
SELECT a.JOIN_CODE, a.TITLE, a.CREATED_AT,
       COALESCE(j.joins,0)          AS joins,
       COALESCE(s.submissions,0)    AS submissions,
       COALESCE(s.graded,0)         AS graded,
       CASE WHEN COALESCE(j.joins,0)=0 THEN 0 ELSE ROUND(s.submissions/j.joins, 3) END AS join_to_submit_rate,
       CASE WHEN COALESCE(s.submissions,0)=0 THEN 0 ELSE ROUND(s.graded/s.submissions, 3) END AS submit_to_graded_rate
FROM ACTIVITIES a
LEFT JOIN j ON a.JOIN_CODE = j.JOIN_CODE
LEFT JOIN s ON a.JOIN_CODE = s.JOIN_CODE
{where_clause}
ORDER BY a.CREATED_AT DESC
"""
funnel_where = "WHERE a.JOIN_CODE = %(JOIN_CODE)s" if join_code else ""
df_funnel = norm_cols(q(sql_funnel.format(where_clause=funnel_where), join_code if join_code else None))
show_df_or_info(df_funnel, msg="No activity funnel data yet.")

# KPIs when single activity filtered
if join_code and not df_funnel.empty:
    row = df_funnel.iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric("Joins", int(row.get("JOINS", 0)))
    with c2: st.metric("Submissions", int(row.get("SUBMISSIONS", 0)))
    with c3: st.metric("Join→Submit", float(row.get("JOIN_TO_SUBMIT_RATE", 0.0)))
    with c4: st.metric("Submit→Graded", float(row.get("SUBMIT_TO_GRADED_RATE", 0.0)))

st.divider()

# ---------- Scores by Language ----------
st.subheader("Scores by Language")
sql_lang = """
SELECT LANGUAGE,
       COUNT(*) AS submissions,
       AVG(TOTAL_SCORE) AS avg_score,
       MEDIAN(TOTAL_SCORE) AS median_score
FROM SUBMISSIONS
{where_clause}
GROUP BY LANGUAGE
ORDER BY submissions DESC
"""
lang_where = "WHERE JOIN_CODE = %(JOIN_CODE)s" if join_code else ""
df_lang = norm_cols(q(sql_lang.format(where_clause=lang_where), join_code if join_code else None))

if df_lang.empty:
    st.info("No language data yet.")
else:
    required = {"LANGUAGE", "SUBMISSIONS", "AVG_SCORE"}
    if not required.issubset(df_lang.columns):
        st.warning(f"Expected columns {required}, got {set(df_lang.columns)}")
        st.dataframe(df_lang, use_container_width=True)
    else:
        c1, c2 = st.columns(2)
        with c1:
            st.bar_chart(df_lang.set_index("LANGUAGE")["SUBMISSIONS"])
        with c2:
            st.bar_chart(df_lang.set_index("LANGUAGE")["AVG_SCORE"])
    st.caption("Bars show submission volume by language and average score per language.")

st.divider()

# ---------- Grade Buckets ----------
st.subheader("Grade Buckets (Scaled Activity Scores)")
sql_buckets = """
SELECT JOIN_CODE,
       COUNT_IF(TOTAL_SCORE < 60)                           AS bucket_f,
       COUNT_IF(TOTAL_SCORE BETWEEN 60 AND 69.99)           AS bucket_d,
       COUNT_IF(TOTAL_SCORE BETWEEN 70 AND 79.99)           AS bucket_c,
       COUNT_IF(TOTAL_SCORE BETWEEN 80 AND 89.99)           AS bucket_b,
       COUNT_IF(TOTAL_SCORE >= 90)                          AS bucket_a
FROM SUBMISSIONS
{where_clause}
GROUP BY JOIN_CODE
ORDER BY JOIN_CODE
"""
buck_where = "WHERE JOIN_CODE = %(JOIN_CODE)s" if join_code else ""
df_buckets = norm_cols(q(sql_buckets.format(where_clause=buck_where), join_code if join_code else None))
show_df_or_info(df_buckets, msg="No submissions available to compute grade buckets.", height=300)

st.divider()

# ---------- Rubric Difficulty ----------
st.subheader("Rubric Difficulty (lowest avg first)")

# IMPORTANT: use FEEDBACK:"per_criterion" JSON (no dependency on PER_CRITERION column)
sql_difficulty = """
WITH flat AS (
  SELECT
      s.JOIN_CODE,
      c.value:"criterion"::string AS criterion,
      TRY_TO_NUMBER(c.value:"score")::float AS score
  FROM SUBMISSIONS s,
       LATERAL FLATTEN(INPUT => s.FEEDBACK:"per_criterion") c
  {where_clause_flat}
)
SELECT
    JOIN_CODE,
    criterion,
    AVG(score) AS avg_criterion_score,
    COUNT(*)   AS samples
FROM flat
GROUP BY JOIN_CODE, criterion
ORDER BY avg_criterion_score ASC
"""
diff_where_flat = "WHERE s.JOIN_CODE = %(JOIN_CODE)s" if join_code else ""
df_diff = norm_cols(q(sql_difficulty.format(where_clause_flat=diff_where_flat), join_code if join_code else None))
show_df_or_info(df_diff, msg="No rubric-level signals yet.", height=420)

st.divider()

# ---------- LLM Health ----------
st.subheader("LLM Health (Latency & Errors)")
sql_llm = """
SELECT DATE_TRUNC('day', TS) AS day,
       COUNT(*)                             AS evals,
       AVG(LLM_LATENCY_MS)                  AS p50_ms,
       APPROX_PERCENTILE(LLM_LATENCY_MS, 0.95) AS p95_ms,
       COUNT_IF(LLM_ERROR IS NOT NULL)      AS errors
FROM SUBMISSIONS
{where_clause}
GROUP BY day
ORDER BY day DESC
"""
llm_where = "WHERE JOIN_CODE = %(JOIN_CODE)s" if join_code else ""
df_llm = norm_cols(q(sql_llm.format(where_clause=llm_where), join_code if join_code else None))

if df_llm.empty:
    st.info("No LLM telemetry yet.")
else:
    needed = {"DAY", "EVALS", "P50_MS", "P95_MS", "ERRORS"}
    if not needed.issubset(df_llm.columns):
        st.warning(f"Expected columns {needed}, got {set(df_llm.columns)}")
        st.dataframe(df_llm, use_container_width=True)
    else:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.line_chart(df_llm.set_index("DAY")[["EVALS"]])
        with c2:
            st.line_chart(df_llm.set_index("DAY")[["P50_MS"]])
        with c3:
            st.line_chart(df_llm.set_index("DAY")[["P95_MS"]])
        st.dataframe(df_llm, use_container_width=True, height=320)
    st.caption("Track volume, p50/p95 latency, and error counts per day.")
