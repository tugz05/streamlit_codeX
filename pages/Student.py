# pages/2_🎓_Student.py
import streamlit as st
import pandas as pd
from config import get_config
from db import get_snowflake_conn, ensure_schema
from models import ParticipantJoin, SubmissionCreate
from services.activities import fetch_activity, add_participant_to_activity, save_student_submission, leaderboard_for
from services.openai_eval import evaluate_with_openai
from openai import OpenAI

cfg = get_config()

st.title("🎓 Student")
if not cfg.snowflake_all_present:
    st.error("Snowflake is required to join and submit.")
    st.stop()

conn = get_snowflake_conn(cfg)
ensure_schema(conn)

with st.form("join_form"):
    jcode = st.text_input("Join Code", placeholder="e.g., ABC123").strip().upper()
    name = st.text_input("Your Name")
    section = st.text_input("Section / Year", placeholder="e.g., BSIT-2A")
    joined = st.form_submit_button("Join")

activity = None
if joined:
    try:
        pj = ParticipantJoin(join_code=jcode, name=name, section=section)
        activity = fetch_activity(conn, pj.join_code)
        if not activity:
            st.error("Activity not found.")
        else:
            add_participant_to_activity(conn, pj.join_code, pj.name, pj.section)
            st.success("Joined. Scroll for instructions and submission.")
            st.session_state["joined_act"] = pj.dict()
    except Exception as e:
        st.error(f"Failed: {e}")

if "joined_act" in st.session_state and not activity:
    activity = fetch_activity(conn, st.session_state["joined_act"]["join_code"])

if activity:
    st.markdown("### Activity Details")
    col1, col2 = st.columns([2,1])
    with col1:
        st.markdown(f"**Title:** {activity['title']}")
        st.markdown("**Instructions:**")
        st.write(activity["instruction"] or "_No instructions provided._")
    with col2:
        st.metric("Max Score", f"{activity['max_score']:.1f}")
        st.metric("Join Code", activity["join_code"])

    st.markdown("**Criteria**")
    st.dataframe(pd.DataFrame(activity["criteria"]), use_container_width=True, height=220)

    st.markdown("---")
    st.subheader("Submit Code")
    c1, c2 = st.columns([1,1])
    with c1:
        language = st.selectbox("Language", ["C++", "Java", "MySQL", "Python", "JavaScript"])
    with c2:
        model_name = st.text_input("OpenAI Model", value=cfg.OPENAI_MODEL)

    code = st.text_area("Your Code", height=260, placeholder='''// Example (C++)
#include <bits/stdc++.h>
using namespace std;
int main(){ cout << "Hello"; }''')

    if st.button("🔍 Analyze & Grade", type="primary", use_container_width=True):
        if not code.strip():
            st.error("Please paste your code.")
        else:
            try:
                client = OpenAI(api_key=cfg.OPENAI_API_KEY)
                res = evaluate_with_openai(
                    client, model_name,
                    code=code,
                    language=language,
                    criteria=activity["criteria"],
                    instruction=activity["instruction"],
                    max_score=activity["max_score"],
                )
            except Exception as e:
                st.exception(e)
                st.stop()

            overall100 = float(res.get("overall_score", 0.0))
            scaled = float(res.get("_scaled_total", 0.0))
            per = res.get("per_criterion", [])
            summary = res.get("summary", "")

            m1, m2 = st.columns([1,1])
            with m1:
                st.metric("Weighted Score (0..100)", f"{overall100:.1f}")
            with m2:
                st.metric("Activity Score", f"{scaled:.2f} / {activity['max_score']:.2f}")

            st.subheader("Per-Criterion Feedback")
            if per:
                st.dataframe(pd.DataFrame(per), use_container_width=True, height=260)
            else:
                st.info("No per-criterion feedback returned.")

            st.subheader("Summary")
            st.write(summary)

            # Save submission
            try:
                rec = SubmissionCreate(
                    join_code=activity["join_code"],
                    student_name=st.session_state["joined_act"]["name"],
                    section=st.session_state["joined_act"]["section"],
                    language=language,
                    code=code,
                    ai_model=model_name,
                    total_score=scaled,
                    feedback_json=res,
                ).dict()
                save_student_submission(conn, rec)
                st.success("Submission saved ✅")
            except Exception as e:
                st.error(f"Save failed: {e}")

    st.markdown("---")
    st.subheader("Leaderboard")
    try:
        rows = leaderboard_for(conn, activity["join_code"])
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, height=420)
        else:
            st.info("No submissions yet.")
    except Exception as e:
        st.error(f"Error fetching leaderboard: {e}")
