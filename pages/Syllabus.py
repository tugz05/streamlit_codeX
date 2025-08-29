# pages/4_📘_Syllabus.py
import time
import json
import streamlit as st
import pandas as pd
from openai import OpenAI
from config import get_config
from db import get_snowflake_conn, ensure_schema, insert_syllabus, list_syllabi
from services.syllabus_gen import generate_syllabus, syllabus_to_markdown

st.set_page_config(page_title="📘 AI Syllabus Creator", page_icon="📘", layout="wide")
st.title("📘 AI-based Syllabus Creation")

cfg = get_config()
oa_ok = bool(cfg.OPENAI_API_KEY)
if not oa_ok:
    st.error("OpenAI is not configured. Set OPENAI_API_KEY in secrets or environment.")
    st.stop()

sf_ok = cfg.snowflake_all_present
conn = None
if sf_ok:
    try:
        conn = get_snowflake_conn(cfg)
        ensure_schema(conn)
    except Exception as e:
        st.warning(f"Snowflake init failed: {e}")

with st.expander("Syllabus Inputs", expanded=True):
    c1, c2, c3, c4 = st.columns([1.5, 1, 1, 1])
    with c1:
        title = st.text_input("Course Title", placeholder="e.g., Data Structures & Algorithms")
    with c2:
        level = st.selectbox("Level", ["Introductory", "Intermediate", "Advanced"], index=0)
    with c3:
        weeks = st.number_input("Duration (weeks)", min_value=4, max_value=52, value=12, step=1)
    with c4:
        modality = st.selectbox("Modality", ["In-person", "Online", "Hybrid"], index=2)

    target_learners = st.text_input("Target Learners", placeholder="e.g., 2nd-year BSCS students with basic programming")
    prerequisites = st.text_input("Prerequisites", placeholder="e.g., Programming Fundamentals / CS101")

    outcomes = st.text_area("Learning Outcomes (one per line)", height=140, placeholder="- Design and analyze algorithms\n- Implement data structures in language X\n- Evaluate algorithmic complexity")
    seed_topics = st.text_area("Seed Topics (comma-separated)", placeholder="Arrays, Linked Lists, Stacks, Queues, Trees, Graphs, Sorting, Searching")

    st.markdown("#### Assessment Mix")
    colg1, colg2, colg3, colg4 = st.columns(4)
    with colg1: wt_proj = st.number_input("Projects %", min_value=0, max_value=100, value=40, step=5)
    with colg2: wt_quiz = st.number_input("Quizzes %", min_value=0, max_value=100, value=20, step=5)
    with colg3: wt_mid  = st.number_input("Midterm %", min_value=0, max_value=100, value=20, step=5)
    with colg4: wt_final= st.number_input("Final %", min_value=0, max_value=100, value=20, step=5)

    include_rubrics = st.checkbox("Include generic rubrics for major assessments", value=True)

    # Normalize grading weights display
    total_w = wt_proj + wt_quiz + wt_mid + wt_final
    if total_w != 100:
        st.warning(f"Grading weights total {total_w}%. Consider balancing to 100%.", icon="⚖️")

payload = {
    "title": title,
    "level": level,
    "weeks": int(weeks),
    "modality": modality,
    "target_learners": target_learners,
    "prerequisites": prerequisites,
    "learning_outcomes": [ln.strip("- ").strip() for ln in outcomes.splitlines() if ln.strip()],
    "seed_topics": [t.strip() for t in seed_topics.split(",") if t.strip()],
    "grading_breakdown": [
        {"component": "Projects", "weight": wt_proj},
        {"component": "Quizzes", "weight": wt_quiz},
        {"component": "Midterm",  "weight": wt_mid},
        {"component": "Final",    "weight": wt_final},
    ],
    "include_rubrics": include_rubrics,
}

left, right = st.columns([1,1])
with left:
    gen = st.button("🤖 Generate Syllabus", type="primary", use_container_width=True)
with right:
    save_toggle = st.toggle("Save to Snowflake after generation", value=bool(conn))

if gen:
    if not title.strip():
        st.error("Please provide a Course Title.")
        st.stop()

    try:
        client = OpenAI(api_key=cfg.OPENAI_API_KEY)
        start = time.time()
        syl = generate_syllabus(client, cfg.OPENAI_MODEL, payload)
        latency_ms = int((time.time() - start) * 1000)
    except Exception as e:
        st.exception(e)
        st.stop()

    if "error" in syl:
        st.error("Syllabus generation failed. Try adjusting inputs.")
        st.json(syl)
        st.stop()

    st.success(f"Syllabus generated in {latency_ms} ms ✅")

    # Preview main fields
    meta_cols = st.columns([2,1,1,1])
    with meta_cols[0]:
        st.markdown(f"**Title:** {syl.get('title', title)}")
        st.markdown(f"**Level:** {syl.get('level', level)}")
        st.markdown(f"**Modality:** {syl.get('modality', modality)}")
    with meta_cols[1]:
        st.metric("Weeks", syl.get("weeks", weeks))
    with meta_cols[2]:
        st.metric("Outcomes", len(syl.get("learning_outcomes", []) or []))
    with meta_cols[3]:
        st.metric("Schedule Weeks", len(syl.get("schedule", []) or []))

    # Learning Outcomes / Grading
    cA, cB = st.columns([1,1])
    with cA:
        st.subheader("Learning Outcomes")
        st.write(pd.DataFrame({"Outcomes": syl.get("learning_outcomes", [])}))
    with cB:
        st.subheader("Grading Breakdown")
        st.write(pd.DataFrame(syl.get("grading_breakdown", [])))

    # Policies
    st.subheader("Policies")
    pol = syl.get("policies", {}) or {}
    st.write(pd.DataFrame(
        [{"Policy":"Late", "Detail":pol.get("late_policy","")},
         {"Policy":"Attendance", "Detail":pol.get("attendance_policy","")},
         {"Policy":"Academic Integrity", "Detail":pol.get("academic_integrity","")},
         {"Policy":"Communication", "Detail":pol.get("communication_policy","")}]
    ))

    # Weekly Schedule
    st.subheader("Weekly Schedule")
    for wk in syl.get("schedule", []):
        with st.expander(f"Week {wk.get('week','?')}: {wk.get('topic','')}", expanded=False):
            st.markdown("**Objectives**")
            st.write(pd.DataFrame({"Objectives": wk.get("objectives", [])}))
            st.markdown("**Content**")
            st.write(pd.DataFrame({"Content": wk.get("content", [])}))
            st.markdown("**Activities**")
            st.write(pd.DataFrame({"Activities": wk.get("activities", [])}))
            st.markdown("**Assignments**")
            st.write(pd.DataFrame({"Assignments": wk.get("assignments", [])}))
            st.markdown(f"**Assessment:** {wk.get('assessment','')}")

    # Rubrics
    rubrics = syl.get("rubrics", [])
    if rubrics:
        st.subheader("Rubrics")
        for rb in rubrics:
            with st.expander(rb.get("name","Rubric"), expanded=False):
                for crit in rb.get("criteria", []):
                    st.markdown(f"**{crit.get('criterion','')}**")
                    levels = crit.get("levels", [])
                    st.table(pd.DataFrame(levels))

    # Exports
    st.subheader("Export")
    md = syllabus_to_markdown(syl)
    st.download_button("⬇️ Download Markdown", md, file_name=f"{syl.get('title','syllabus').replace(' ','_')}.md")
    st.download_button("⬇️ Download JSON", json.dumps(syl, indent=2), file_name=f"{syl.get('title','syllabus').replace(' ','_')}.json")

    # Save
    if save_toggle and conn:
        try:
            insert_syllabus(
                conn,
                title=syl.get("title", title),
                level=syl.get("level", level),
                weeks=int(syl.get("weeks", weeks) or weeks),
                modality=syl.get("modality", modality),
                inputs=payload,
                syllabus=syl,
            )
            st.success("Saved to Snowflake ✅")
        except Exception as e:
            st.error(f"Save failed: {e}")

st.markdown("---")
st.subheader("Recent Syllabi")
if conn:
    try:
        rows = list_syllabi(conn, limit=100)
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No syllabi saved yet.")
    except Exception as e:
        st.warning(f"Could not load syllabi: {e}")
else:
    st.info("Connect Snowflake to save and list syllabi.")
