from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from dicom_parser import save_uploaded_files, load_dicoms, classify_rt_files, extract_plan_summary, extract_structures
from dvh_engine import approximate_metrics, dvh_note
from scorecard_engine import build_metric_table, domain_scores, final_grade
from spider_chart import make_spider_chart

st.set_page_config(page_title="DTI SPIDERPlan Scorecard", layout="wide")

@st.cache_data
def load_config():
    with open(Path(__file__).parent / "scoring_config.json", "r") as f:
        return json.load(f)

config = load_config()

st.title("DTI SPIDERPlan Scorecard™ Prototype")
st.caption("Local DICOM RT scorecard prototype for Eclipse/ARIA RT Plan exports")

with st.expander("Clinical / security disclaimer", expanded=False):
    st.warning(
        "Prototype only. Not for clinical decision-making. Do not upload identifiable PHI to public or non-HIPAA-compliant systems. "
        "A complete clinical implementation requires validated DVH rasterization, commissioning, access controls, encryption, audit logs, and formal QA."
    )

uploaded = st.file_uploader(
    "Upload Eclipse/ARIA DICOM RT export files: RP + RS + RD preferred",
    type=["dcm", "dicom", "DCM"],
    accept_multiple_files=True,
)

manual_rx = st.number_input("Prescription dose for scoring fallback (Gy)", min_value=0.0, max_value=100.0, value=70.0, step=0.1)

if uploaded:
    try:
        paths = save_uploaded_files(uploaded)
        datasets = load_dicoms(paths)
        grouped = classify_rt_files(datasets)

        rp = grouped["RP"][0] if grouped["RP"] else None
        rs = grouped["RS"][0] if grouped["RS"] else None
        rd = grouped["RD"][0] if grouped["RD"] else None

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("RT Plan Files", len(grouped["RP"]))
        c2.metric("RT Structure Files", len(grouped["RS"]))
        c3.metric("RT Dose Files", len(grouped["RD"]))
        c4.metric("CT Slices", len(grouped["CT"]))

        plan_summary = extract_plan_summary(rp)
        structures = extract_structures(rs)
        rx_gy = float(plan_summary.get("Rx Dose Gy") or manual_rx or 0)

        st.subheader("Plan Summary")
        summary_display = {k: v for k, v in plan_summary.items() if k != "Beams"}
        st.dataframe(pd.DataFrame([summary_display]), use_container_width=True)

        if plan_summary.get("Beams"):
            st.subheader("Beam / MU Summary")
            st.dataframe(pd.DataFrame(plan_summary["Beams"]), use_container_width=True)

        st.subheader("Structures Detected")
        if structures:
            st.dataframe(pd.DataFrame(structures), use_container_width=True)
        else:
            st.info("No RT Structure Set detected.")

        st.subheader("DVH / Dose Metrics")
        metrics = approximate_metrics(rd, rs, structures, config, rx_gy)
        st.info(dvh_note())

        if metrics:
            flat = []
            for structure, vals in metrics.items():
                for metric, value in vals.items():
                    flat.append({"Structure": structure, "Metric": metric, "Value": value})
            st.dataframe(pd.DataFrame(flat), use_container_width=True)
        else:
            st.warning("No RT Dose file detected. Upload RD + RS files for DVH scoring.")

        st.subheader("ProKnow-Type Metric Scorecard")
        metric_df = build_metric_table(plan_summary, metrics, config, rx_gy)
        st.dataframe(metric_df, use_container_width=True)

        completeness = 100.0
        if rp is None: completeness -= 30
        if rs is None: completeness -= 25
        if rd is None: completeness -= 25
        if not structures: completeness -= 10
        completeness = max(0.0, completeness)

        domain_df = domain_scores(metric_df, config, completeness)
        score, grade = final_grade(domain_df, config)

        st.subheader("DTI-SPIDER Domain Scorecard")
        a, b = st.columns([1, 2])
        with a:
            st.metric("Final SPIDER Score", score)
            st.metric("Plan Grade", grade)
            st.dataframe(domain_df, use_container_width=True)
        with b:
            st.plotly_chart(make_spider_chart(domain_df), use_container_width=True)

        st.subheader("Export")
        csv = metric_df.to_csv(index=False).encode("utf-8")
        st.download_button("Download Metric Scorecard CSV", csv, "dti_spider_metric_scorecard.csv", "text/csv")

        domain_csv = domain_df.to_csv(index=False).encode("utf-8")
        st.download_button("Download SPIDER Domain CSV", domain_csv, "dti_spider_domain_scorecard.csv", "text/csv")

    except Exception as e:
        st.error("The app crashed while processing the uploaded DICOM files.")
        st.exception(e)
