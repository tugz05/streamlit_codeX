# pages/3_📊_Analytics.py
import streamlit as st
import pandas as pd
from config import get_config
from db import get_snowflake_conn

st.title("📊 Analytics")
cfg = get_config()
if not cfg.snowflake_all_present:
    st.error("Snowflake required for analytics.")
    st.stop()

conn = get_snowflake_conn(cfg)

@st.cache_data(ttl=120)
def q(fsql: str) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(fsql)
        rows = cur.fetchall()
        cols = [c[0] for c in cur.description]
    return pd.DataFrame(rows, columns=cols)

st.subheader("Activity Funnel")
df_funnel = q("""
WITH j AS (
  SELECT JOIN_CODE, COUNT(*) AS joins FROM PARTICIPANTS GROUP BY JOIN_CODE
), s AS (
  SELECT JOIN_CODE, COUNT(*) AS submissions, COUNT_IF(TOTAL_SCORE IS NOT NULL) AS graded
  FROM SUBMISSIONS GROUP BY JOIN_CODE
)
SELECT a.JOIN_CODE, a.TITLE, a.CREATED_AT,
       COALESCE(j.joins,0) AS joins,
       COALESCE(s.submissions,0) AS submissions,
       COALESCE(s.graded,0) AS graded,
       CASE WHEN COALESCE(j.joins,0)=0 THEN 0 ELSE ROUND(s.submissions/j.joins,3) END AS join_to_submit_rate,
       CASE WHEN COALESCE(s.submissions,0)=0 THEN 0 ELSE ROUND(s.graded/s.submissions,3) END AS submit_to_graded_rate
FROM ACTIVITIES a
LEFT JOIN j ON a.JOIN_CODE=j.JOIN_CODE
LEFT JOIN s ON a.JOIN_CODE=s.JOIN_CODE
ORDER BY a.CREATED_AT DESC
""")
st.dataframe(df_funnel, use_container_width=True, hide_index=True)

st.subheader("Scores by Language")
df_lang = q("""
SELECT LANGUAGE, COUNT(*) AS submissions,
       AVG(TOTAL_SCORE) AS avg_score, MEDIAN(TOTAL_SCORE) AS median_score
FROM SUBMISSIONS
GROUP BY LANGUAGE
ORDER BY submissions DESC
""")
c1, c2 = st.columns([1,1])
with c1:
    st.bar_chart(df_lang.set_index("LANGUAGE")["submissions"])
with c2:
    st.bar_chart(df_lang.set_index("LANGUAGE")["avg_score"])

st.subheader("Rubric Difficulty (lowest avg first)")
df_diff = q("""
WITH flat AS (
  SELECT JOIN_CODE, c.value:"criterion"::string AS criterion, c.value:"score"::float AS score
  FROM SUBMISSIONS s, LATERAL FLATTEN(INPUT => s.PER_CRITERION) c
)
SELECT JOIN_CODE, criterion, AVG(score) AS avg_criterion_score, COUNT(*) AS samples
FROM flat
GROUP BY JOIN_CODE, criterion
ORDER BY avg_criterion_score ASC
""")
st.dataframe(df_diff, use_container_width=True, height=420)

st.subheader("LLM Health (Latency & Errors)")
df_llm = q("""
SELECT DATE_TRUNC('day', TS) AS day,
       COUNT(*) AS evals,
       AVG(LLM_LATENCY_MS) AS p50_ms,
       APPROX_PERCENTILE(LLM_LATENCY_MS, 0.95) AS p95_ms,
       COUNT_IF(LLM_ERROR IS NOT NULL) AS errors
FROM SUBMISSIONS
GROUP BY day
ORDER BY day DESC
""")
st.dataframe(df_llm, use_container_width=True)
