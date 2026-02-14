"""
DDR Report Generator — CLI Entry Point
Run from command line for quick generation without the web UI.

Usage:
    python main.py --inspection "path/to/inspection.pdf" --thermal "path/to/thermal.pdf"
    python main.py --inspection "input_docs/Sample Report.pdf" --thermal "input_docs/Thermal Images.pdf" --output-format pdf
"""

import argparse
import os
import sys
from dotenv import load_dotenv

from DDR.Exception.exception import DDRException
from DDR.src.pdf_extractor import extract_inspection_report, extract_thermal_report
from DDR.src.data_processor import merge_inspection_and_thermal, format_merged_data_for_llm
from DDR.src.report_generator import generate_ddr, save_report_markdown, save_report_pdf
from DDR.Logging.logger import logging

def main():
    load_dotenv()  # load .env file if present

    parser = argparse.ArgumentParser(
        description="Generate a Detailed Diagnostic Report (DDR) from inspection documents.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--inspection", "-i",
        required=True,
        help="Path to the Inspection Report PDF",
    )
    parser.add_argument(
        "--thermal", "-t",
        required=True,
        help="Path to the Thermal Images Report PDF",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output file path (default: auto-generated in output/ folder)",
    )
    parser.add_argument(
        "--output-format",
        choices=["md", "pdf", "both"],
        default="both",
        help="Output format (default: both)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Google Gemini API key (or set GOOGLE_API_KEY env var)",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip the validation pass",
    )

    args = parser.parse_args()

    # check API key
    api_key = args.api_key or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: No API key provided.")
        print("  Set GOOGLE_API_KEY environment variable, create a .env file, or use --api-key flag.")
        print("  Get a free key from: https://aistudio.google.com/apikey")
        sys.exit(1)

    # check files exist
    for label, path in [("Inspection", args.inspection), ("Thermal", args.thermal)]:
        if not os.path.exists(path):
            print(f"ERROR: {label} report not found: {path}")
            sys.exit(1)

    print("=" * 60)
    print("  DDR Report Generator")
    print("=" * 60)
    print()

    # Step 1: Extract
    print("[1/4] Extracting text from PDFs...")
    try:
        inspection_data = extract_inspection_report(args.inspection)
        print(f"  ✓ Inspection report: {len(inspection_data.get('impacted_areas', []))} impacted areas found")
    except Exception as e:
        logging.error(f"Failed to extract inspection report: {str(e)}")
        logging.info("Please check the input PDF format and ensure it contains the expected sections.")
        DDRException("Failed to extract inspection report. Check logs for details.", sys)
        sys.exit(1)

    try:
        thermal_data = extract_thermal_report(args.thermal)
        print(f"  ✓ Thermal report: {thermal_data.get('num_images', 0)} thermal readings found")
    except Exception as e:
        logging.error(f"Failed to extract thermal report: {str(e)}")
        raise DDRException(e, sys)

    # Step 2: Merge
    print("\n[2/4] Processing and merging data...")
    merged = merge_inspection_and_thermal(inspection_data, thermal_data)
    formatted_data = format_merged_data_for_llm(merged)

    conflicts = merged.get("conflicts", [])
    missing = merged.get("missing_info", [])
    if conflicts:
        print(f"  ⚠ {len(conflicts)} conflict(s) detected")
        for c in conflicts:
            print(f"    → {c['detail']}")
    if missing:
        print(f"  ℹ {len(missing)} piece(s) of missing info noted")

    print(f"  ✓ Merged data: {len(formatted_data):,} characters")

    # Step 3: Generate
    print(f"\n[3/4] Generating DDR report (this takes ~20-30 seconds)...")
    try:
        result = generate_ddr(
            formatted_data,
            api_key=api_key,
            validate=not args.no_validate,
        )
    except Exception as e:
        logging.error(f"Report generation failed: {str(e)}")
        raise DDRException(e, sys)

    report_text = result["report"]
    meta = result["metadata"]
    print(f"  ✓ Report generated ({meta['output_chars']:,} chars, {meta['generation_time_seconds']}s)")

    if result.get("validation"):
        print(f"  ✓ Validation complete ({meta.get('validation_time_seconds', '?')}s)")

    # Step 4: Save
    print(f"\n[4/4] Saving report...")
    output_files = []

    if args.output_format in ("md", "both"):
        md_out = args.output if args.output and args.output.endswith(".md") else None
        md_path = save_report_markdown(report_text, md_out)
        output_files.append(md_path)

    if args.output_format in ("pdf", "both"):
        pdf_out = args.output if args.output and args.output.endswith(".pdf") else None
        try:
            pdf_path = save_report_pdf(report_text, pdf_out)
            output_files.append(pdf_path)
        except Exception as e:
            logging.error(f"PDF generation failed: {str(e)}")
            logging.info("Falling back to Markdown output only.")
            raise DDRException(e,sys)

    # save validation results
    if result.get("validation"):
        val_path = "output/validation_results.txt"
        with open(val_path, "w", encoding="utf-8") as f:
            f.write(result["validation"])
        print(f"  ✓ Validation saved to: {val_path}")

    print()
    print("=" * 60)
    print("  Done! Output files:")
    for fp in output_files:
        print(f"    → {fp}")
    print("=" * 60)


if __name__ == "__main__":
    main()
