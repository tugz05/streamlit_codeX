# pages/4_📘_AI_Module_Creation.py
import streamlit as st
import pandas as pd
from typing import List, Dict, Any
from config import get_config
from db import get_snowflake_conn, ensure_schema, insert_module, list_modules
from services.module_gen import generate_module

st.set_page_config(page_title="📘 AI Module Creation", page_icon="📘", layout="wide")
st.title("📘 AI-based Module Creation")

cfg = get_config()

with st.sidebar:
    st.markdown("**OpenAI Model:**")
    model_name = st.text_input("Model", value=cfg.OPENAI_MODEL, key="module_openai_model")

st.subheader("Module Parameters")
c1, c2, c3 = st.columns([1,1,1])
with c1:
    subject = st.text_input("Subject / Course", placeholder="e.g., Data Structures")
with c2:
    level = st.selectbox("Level", ["Beginner", "Intermediate", "Advanced"])
with c3:
    duration = st.text_input("Duration", placeholder="e.g., 2 weeks or 6 hours")

c4, c5 = st.columns([2,1])
with c4:
    module_title = st.text_input("Module Title", placeholder="e.g., Mastering Arrays and Linked Lists")
with c5:
    num_lessons = st.number_input("Number of Lessons", min_value=1, max_value=20, value=4, step=1)

learning_outcomes = st.text_area(
    "Target Competencies / Learning Outcomes (one per line)",
    height=120,
    placeholder="Explain the role of arrays and linked lists in memory.\nAnalyze time/space complexity for common operations.\nImplement basic linked list methods."
)

constraints = st.text_area(
    "Constraints & Preferences (optional)",
    height=100,
    placeholder="Align to CHED outcomes; include formative quizzes; prefer project-based activities; C++ examples; add rubric."
)

st.markdown("—")

gen = st.button("✨ Generate Module with AI", type="primary", use_container_width=True)

if gen:
    if not cfg.OPENAI_API_KEY:
        st.error("Missing OPENAI_API_KEY. Set it in your environment or Streamlit secrets.")
        st.stop()
    if not module_title.strip() or not subject.strip():
        st.error("Please provide both a Subject and a Module Title.")
        st.stop()

    with st.spinner("Generating module with OpenAI…"):
        try:
            outcomes_list = [x.strip() for x in learning_outcomes.splitlines() if x.strip()]
            payload = generate_module(
                api_key=cfg.OPENAI_API_KEY,
                model=model_name,
                subject=subject.strip(),
                title=module_title.strip(),
                level=level,
                duration=duration.strip() or "Not specified",
                outcomes=outcomes_list,
                num_lessons=int(num_lessons),
                constraints=constraints.strip(),
            )
        except Exception as e:
            st.exception(e)
            st.stop()

    # Render result
    st.success("Module generated!")
    st.markdown(f"### {payload.get('title', module_title)}")
    st.caption(f"Subject: **{subject}** • Level: **{level}** • Duration: **{duration or '—'}**")

    with st.expander("Learning Outcomes", expanded=True):
        ol = payload.get("learning_outcomes", outcomes_list)
        st.markdown("\n".join([f"- {x}" for x in ol]) if ol else "_None_")

    with st.expander("Lesson Plan / Outline", expanded=True):
        lessons = payload.get("lessons", [])
        if lessons:
            df_l = pd.DataFrame(lessons)
            st.dataframe(df_l, use_container_width=True, height=300)
        else:
            st.info("No lessons returned.")

    with st.expander("Activities & Assessments", expanded=True):
        activities = payload.get("activities", [])
        if activities:
            df_a = pd.DataFrame(activities)
            st.dataframe(df_a, use_container_width=True, height=300)
        else:
            st.info("No activities returned.")

    with st.expander("Rubric (Editable)", expanded=True):
        rubric_rows = payload.get("rubric", [])
        df_r = st.data_editor(
            pd.DataFrame(rubric_rows) if rubric_rows else pd.DataFrame([{"criterion":"Quality","weight":1.0,"description":"Overall"}]),
            num_rows="dynamic",
            use_container_width=True,
            key="module_rubric_editor"
        )

    with st.expander("Resources / References", expanded=False):
        resources = payload.get("resources", [])
        st.markdown("\n".join([f"- {x}" for x in resources]) if resources else "_None_")

    with st.expander("Answer Keys / Solutions (if any)", expanded=False):
        answers = payload.get("answers", [])
        for i, a in enumerate(answers, 1):
            st.markdown(f"**Answer {i}:**")
            st.code(a, language="text")

    # Build Markdown for export
    md_lines = []
    md_lines += [f"# {payload.get('title', module_title)}", ""]
    md_lines += [f"**Subject:** {subject}  ", f"**Level:** {level}  ", f"**Duration:** {duration or '—'}", ""]
    if outcomes_list:
        md_lines += ["## Learning Outcomes"] + [f"- {x}" for x in payload.get("learning_outcomes", outcomes_list)] + [""]
    if payload.get("lessons"):
        md_lines += ["## Lesson Plan / Outline"]
        for l in payload["lessons"]:
            md_lines += [f"- **{l.get('title','Lesson')}**: {l.get('summary','')}".strip()]
        md_lines += [""]
    if payload.get("activities"):
        md_lines += ["## Activities & Assessments"]
        for a in payload["activities"]:
            md_lines += [f"- **{a.get('type','Activity')}**: {a.get('description','')}".strip()]
        md_lines += [""]
    if not df_r.empty:
        md_lines += ["## Rubric"]
        for _, r in df_r.iterrows():
            md_lines += [f"- **{r.get('criterion','')}** (w={r.get('weight','')}): {r.get('description','')}".strip()]
        md_lines += [""]
    if payload.get("resources"):
        md_lines += ["## Resources"] + [f"- {x}" for x in payload["resources"]] + [""]
    if payload.get("answers"):
        md_lines += ["## Answer Keys / Solutions"]
        for i, a in enumerate(payload["answers"], 1):
            md_lines += [f"**Answer {i}:**", "```", a, "```", ""]
    md_blob = "\n".join(md_lines).strip()

    st.download_button("⬇️ Download Markdown", data=md_blob.encode("utf-8"), file_name="module.md", mime="text/markdown", use_container_width=True)

    st.markdown("---")
    st.subheader("Save to Snowflake")
    if not cfg.snowflake_all_present:
        st.warning("Snowflake is not configured; saving is disabled.")
    else:
        conn = get_snowflake_conn(cfg)
        ensure_schema(conn)  # will also ensure MODULES table exists
        if st.button("💾 Save Module", type="primary", use_container_width=True):
            try:
                # Normalize/clean rubric weights
                rows = df_r.to_dict(orient="records")
                total_w = sum(float(r.get("weight", 0)) for r in rows) or 1.0
                for r in rows:
                    r["weight"] = float(r.get("weight", 0)) / total_w

                record = {
                    "title": payload.get("title", module_title.strip()),
                    "subject": subject.strip(),
                    "level": level,
                    "duration": duration.strip() or "Not specified",
                    "learning_outcomes": payload.get("learning_outcomes", outcomes_list),
                    "lessons": payload.get("lessons", []),
                    "activities": payload.get("activities", []),
                    "rubric": rows,
                    "resources": payload.get("resources", []),
                    "answers": payload.get("answers", []),
                    "raw_json": payload,
                }
                insert_module(conn, record)
                st.success("Module saved to Snowflake ✅")
            except Exception as e:
                st.error(f"Failed to save: {e}")

st.markdown("---")
st.subheader("📚 Recently Saved Modules")
if cfg.snowflake_all_present:
    try:
        conn = get_snowflake_conn(cfg)
        ensure_schema(conn)
        modules = list_modules(conn, limit=50)
        if modules:
            dfm = pd.DataFrame(modules)
            st.dataframe(dfm, use_container_width=True, hide_index=True)
        else:
            st.info("No modules saved yet.")
    except Exception as e:
        st.warning(f"Could not load modules: {e}")
else:
    st.info("Connect Snowflake to list saved modules.")
