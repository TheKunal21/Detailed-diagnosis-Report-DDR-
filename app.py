"""
DDR Report Generator — Streamlit Web App
Upload inspection + thermal PDFs → get a structured DDR report
"""

import os
import tempfile
import streamlit as st
from dotenv import load_dotenv
from DDR.Logging.logger import logger
from DDR.Exception import DDRException
import sys

load_dotenv()  # load .env file if present

from DDR.src.pdf_extractor import extract_inspection_report, extract_thermal_report
from DDR.src.data_processor import merge_inspection_and_thermal, format_merged_data_for_llm
from DDR.src.report_generator import generate_ddr, save_report_markdown, save_report_pdf


logger.info("Starting DDR Report Generator Streamlit app...")


# --- Page Config ---
st.set_page_config(
    page_title="DDR Report Generator",
    page_icon="🏗️",
    layout="wide",
)

st.title("🏗️ DDR Report Generator")
st.markdown(
    "Upload site inspection documents to generate a **Detailed Diagnostic Report** "
    "powered by AI. The system extracts observations from both reports, merges them, "
    "and produces a structured client-ready DDR."
)
st.divider()


# --- Sidebar ---
api_key = os.getenv("GOOGLE_API_KEY", "")

with st.sidebar:
    st.header("⚙️ Configuration")

    if api_key:
        st.success("API key loaded from environment ✓")
    else:
        st.error("GOOGLE_API_KEY not found in .env file. Add it and restart.")

    st.divider()
    st.markdown("**How it works:**")
    st.markdown(
        "1. Upload Inspection Report PDF\n"
        "2. Upload Thermal Images PDF\n"
        "3. Click Generate\n"
        "4. Review & download the DDR"
    )
    
    run_validation = st.checkbox("Run validation pass", value=True, 
                                  help="Double-checks the generated report against source data")


# --- File Uploads ---
col1, col2 = st.columns(2)

with col1:
    st.subheader("📋 Inspection Report")
    inspection_file = st.file_uploader(
        "Upload the site inspection report PDF",
        type=["pdf"],
        key="inspection",
    )
    if inspection_file:
        st.success(f"Uploaded: {inspection_file.name}")

with col2:
    st.subheader("🌡️ Thermal Report")
    thermal_file = st.file_uploader(
        "Upload the thermal images report PDF",
        type=["pdf"],
        key="thermal",
    )
    if thermal_file:
        st.success(f"Uploaded: {thermal_file.name}")


# --- Generate Button ---
st.divider()

if st.button("🚀 Generate DDR Report", type="primary", use_container_width=True):
    # validate inputs
    if not api_key:
        st.error("GOOGLE_API_KEY not set. Add it to your .env file and restart the app.")
        st.stop()

    if not inspection_file or not thermal_file:
        st.error("Please upload both the Inspection Report and Thermal Report PDFs.")
        st.stop()

    # save uploaded files to temp location
    with tempfile.TemporaryDirectory() as tmpdir:
        insp_path = os.path.join(tmpdir, "inspection.pdf")
        therm_path = os.path.join(tmpdir, "thermal.pdf")

        with open(insp_path, "wb") as f:
            f.write(inspection_file.getvalue())
        with open(therm_path, "wb") as f:
            f.write(thermal_file.getvalue())

        # --- Pipeline ---
        progress = st.progress(0, text="Starting...")

        try:
            # step 1: extract
            logger.info("Step 1: Extracting text from PDFs...")
            progress.progress(10, text="Extracting text from Inspection Report...")
            inspection_data = extract_inspection_report(insp_path)
            logger.info(f"Inspection report extracted: {len(inspection_data.get('impacted_areas', []))} impacted areas")

            progress.progress(25, text="Extracting text from Thermal Report...")
            thermal_data = extract_thermal_report(therm_path)
            logger.info(f"Thermal report extracted: {thermal_data.get('num_images', 0)} readings")

            # show extraction stats
            with st.expander("📊 Extraction Summary", expanded=False):
                ecol1, ecol2 = st.columns(2)
                with ecol1:
                    st.metric("Impacted Areas Found", len(inspection_data.get("impacted_areas", [])))
                with ecol2:
                    st.metric("Thermal Readings", thermal_data.get("num_images", 0))

            # step 2: merge & process
            logger.info("Step 2: Merging and processing data...")
            progress.progress(40, text="Merging and processing data...")
            merged = merge_inspection_and_thermal(inspection_data, thermal_data)
            formatted_data = format_merged_data_for_llm(merged)
            logger.info(f"Data merged: {len(formatted_data):,} characters")

            # show merged data (collapsed)
            with st.expander("🔍 Processed Data (for debugging)", expanded=False):
                st.text(formatted_data[:3000] + "..." if len(formatted_data) > 3000 else formatted_data)

            # show conflicts/missing
            if merged.get("conflicts"):
                st.warning(f"⚠️ Found {len(merged['conflicts'])} conflict(s) between reports")
                for c in merged["conflicts"]:
                    st.caption(f"  → {c['detail']}")

            if merged.get("missing_info"):
                st.info(f"ℹ️ {len(merged['missing_info'])} piece(s) of missing information detected")

            # step 3: generate with LLM
            logger.info("Step 3: Generating DDR report with LLM...")
            progress.progress(55, text="Generating DDR report with AI (this takes ~20-30 seconds)...")
            result = generate_ddr(formatted_data, api_key=api_key, validate=run_validation)
            logger.info(f"Report generated: {result['metadata']['output_chars']:,} chars in {result['metadata']['generation_time_seconds']}s")

            progress.progress(90, text="Formatting output...")

            # step 4: display results
            report_text = result["report"]

            st.divider()
            st.subheader("📄 Generated DDR Report")
            st.markdown(report_text)

            # show validation if available
            if result.get("validation"):
                with st.expander("✅ Validation Results", expanded=False):
                    st.markdown(result["validation"])

            # metadata
            with st.expander("📈 Generation Metadata", expanded=False):
                meta = result["metadata"]
                mcol1, mcol2, mcol3 = st.columns(3)
                with mcol1:
                    st.metric("Generation Time", f"{meta['generation_time_seconds']}s")
                with mcol2:
                    st.metric("Input Size", f"{meta['input_chars']:,} chars")
                with mcol3:
                    st.metric("Output Size", f"{meta['output_chars']:,} chars")

            # step 5: download options
            st.divider()
            st.subheader("📥 Download Report")

            dcol1, dcol2 = st.columns(2)

            with dcol1:
                # Markdown download
                md_path = save_report_markdown(report_text)
                with open(md_path, "r", encoding="utf-8") as f:
                    md_content = f.read()
                st.download_button(
                    "⬇️ Download as Markdown",
                    data=md_content,
                    file_name="DDR_Report.md",
                    mime="text/markdown",
                )

            with dcol2:
                # PDF download
                try:
                    logger.info("Attempting to generate PDF report...")
                    pdf_path = save_report_pdf(report_text)
                    with open(pdf_path, "rb") as f:
                        pdf_bytes = f.read()
                    st.download_button(
                        "⬇️ Download as PDF",
                        data=pdf_bytes,
                        file_name="DDR_Report.pdf",
                        mime="application/pdf",
                    )
                except Exception as e:
                    logger.info(f"PDF generation failed: {str(e)}. Falling back to Markdown download.")
                    raise DDRException(f"PDF generation failed: {str(e)}", sys)

            logger.info("DDR report generation completed successfully")
            progress.progress(100, text="Done! ✓")

        except DDRException as e:
            logger.error(f"DDR Exception: {str(e)}")
            progress.empty()
            st.error(f"❌ Error: {str(e)}")
            st.exception(e)
            raise DDRException(e,sys)
        
