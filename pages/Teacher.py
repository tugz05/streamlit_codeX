# pages/1_👩‍🏫_Teacher.py
import streamlit as st
import pandas as pd
from config import get_config
from db import get_snowflake_conn, ensure_schema
from models import ActivityCreate, RubricItem
from services.activities import create_activity, recent_activities, leaderboard_for

cfg = get_config()

st.title("👩‍🏫 Teacher")
if not cfg.snowflake_all_present:
    st.error("Snowflake is required. Please set credentials to use teacher features.")
    st.stop()

conn = get_snowflake_conn(cfg)
ensure_schema(conn)

with st.expander("Create Activity", expanded=True):
    c1, c2 = st.columns([2,1])
    with c1:
        title = st.text_input("Title", placeholder="e.g., Arrays & Loops — Warmup")
    with c2:
        max_score = st.number_input("Max Score", min_value=1.0, max_value=1000.0, value=100.0, step=1.0)

    instruction = st.text_area(
        "Instructions",
        height=140,
        placeholder="Describe requirements, input/output format, example cases, constraints, etc.",
    )

    default_rubric = st.session_state.get("default_rubric", [
        {"criterion": "Correctness (passes requirements)", "weight": 0.5},
        {"criterion": "Code Quality (readability/structure)", "weight": 0.2},
        {"criterion": "Efficiency (time/space/queries)", "weight": 0.2},
        {"criterion": "Edge Cases & Robustness", "weight": 0.1},
    ])

    st.markdown("#### Criteria (weights will be normalized)")
    r_df = st.data_editor(pd.DataFrame(default_rubric), num_rows="dynamic", use_container_width=True, key="teacher_rubric_editor")

    if st.button("Create Activity", type="primary"):
        try:
            criteria = [RubricItem(**row).dict() for row in r_df.to_dict(orient="records")]
            payload = ActivityCreate(title=title, instruction=instruction, max_score=max_score, criteria=criteria).dict()
            code = create_activity(conn, payload)
            st.success(f"Activity created. Join code: **{code}**")
        except Exception as e:
            st.error(f"Failed: {e}")

st.markdown("### Recent Activities")
try:
    acts = recent_activities(conn, limit=100)
    if acts:
        st.dataframe(pd.DataFrame(acts), use_container_width=True, hide_index=True)
    else:
        st.info("No activities yet.")
except Exception as e:
    st.warning(f"Could not load activities: {e}")

st.markdown("---")
st.subheader("Leaderboard")
code = st.text_input("Enter Join Code", placeholder="e.g., ABC123").strip().upper()
if code:
    try:
        rows = leaderboard_for(conn, code)
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, height=420)
        else:
            st.info("No submissions yet.")
    except Exception as e:
        st.error(f"Error fetching leaderboard: {e}")
