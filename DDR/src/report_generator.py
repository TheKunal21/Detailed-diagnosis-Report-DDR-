"""
Report Generator Module
Handles LLM calls and output formatting.
"""

import os
import time
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types

from .prompts import SYSTEM_PROMPT, DDR_GENERATION_PROMPT, VALIDATION_PROMPT


MODEL_NAME = "gemini-2.5-flash"
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds


def _get_client(api_key: str = None):
    """Set up and return the Gemini client."""
    key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError(
            "No API key found. Set GOOGLE_API_KEY environment variable or pass it directly.\n"
            "Get a free key at: https://aistudio.google.com/apikey"
        )
    return genai.Client(api_key=key)


def _call_llm_with_retry(client, model: str, contents: str, config, max_retries: int = MAX_RETRIES) -> str:
    """
    Call the LLM with automatic retry on transient failures.
    Handles rate limits, timeouts, and empty responses.
    """
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )

            # guard against empty/None response
            if response is None or not hasattr(response, 'text') or not response.text:
                if attempt < max_retries:
                    print(f"  Empty response from LLM (attempt {attempt}/{max_retries}), retrying...")
                    time.sleep(RETRY_DELAY * attempt)
                    continue
                raise ValueError("LLM returned an empty response after all retries.")

            text = response.text.strip()
            if len(text) < 50:
                if attempt < max_retries:
                    print(f"  Response too short ({len(text)} chars, attempt {attempt}/{max_retries}), retrying...")
                    time.sleep(RETRY_DELAY * attempt)
                    continue
                raise ValueError(f"LLM response too short ({len(text)} chars). May indicate a problem.")

            return text

        except (ValueError, AttributeError) as e:
            # re-raise our own validation errors on last attempt
            last_error = e
            if attempt >= max_retries:
                raise
            print(f"  LLM error (attempt {attempt}/{max_retries}): {e}, retrying...")
            time.sleep(RETRY_DELAY * attempt)

        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            # retry on rate limit / quota / timeout / server errors
            if any(keyword in error_str for keyword in ['rate', 'quota', 'timeout', '429', '500', '503', 'overloaded', 'unavailable']):
                if attempt < max_retries:
                    wait = RETRY_DELAY * attempt * 2  # longer wait for rate limits
                    print(f"  Rate limit/server error (attempt {attempt}/{max_retries}), waiting {wait}s...")
                    time.sleep(wait)
                    continue
            raise

    raise last_error or RuntimeError("LLM call failed after all retries.")


def generate_ddr(merged_data_text: str, api_key: str = None, validate: bool = True) -> dict:
    """
    Generate a DDR report using the LLM.
    
    Args:
        merged_data_text: Pre-processed and formatted data from both reports
        api_key: Google API key (optional, will use env var)
        validate: Whether to run a validation pass on the generated report
    
    Returns:
        dict with 'report', 'validation' (if enabled), and 'metadata'
    """
    client = _get_client(api_key)

    # --- Step 1: Generate the DDR ---
    prompt = DDR_GENERATION_PROMPT.format(merged_data=merged_data_text)

    print("Generating DDR report...")
    start_time = time.time()

    report_text = _call_llm_with_retry(
        client,
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.3,
            max_output_tokens=8000,
            top_p=0.9,
        ),
    )

    gen_time = time.time() - start_time
    print(f"  Report generated in {gen_time:.1f}s")

    result = {
        "report": report_text,
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "model": MODEL_NAME,
            "generation_time_seconds": round(gen_time, 1),
            "input_chars": len(merged_data_text),
            "output_chars": len(report_text),
        },
    }

    # --- Step 2: Validate (optional) ---
    if validate:
        print("Running validation pass...")
        val_start = time.time()

        val_prompt = VALIDATION_PROMPT.format(
            merged_data=merged_data_text,
            generated_report=report_text,
        )

        try:
            val_text = _call_llm_with_retry(
                client,
                model=MODEL_NAME,
                contents=val_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.2,
                    max_output_tokens=2000,
                ),
                max_retries=2,  # fewer retries for validation — it's optional
            )
            result["validation"] = val_text
        except Exception as e:
            print(f"  Validation failed (non-critical): {e}")
            result["validation"] = f"Validation could not be completed: {str(e)}"
        val_time = time.time() - val_start
        result["metadata"]["validation_time_seconds"] = round(val_time, 1)
        print(f"  Validation done in {val_time:.1f}s")

    return result


def save_report_markdown(report_text: str, output_path: str = None) -> str:
    """Save the DDR report as a Markdown file."""
    if not output_path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"output/DDR_Report_{timestamp}.md"

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # add header
    full_content = f"""# Detailed Diagnostic Report (DDR)

**Generated on:** {datetime.now().strftime("%d %B %Y, %I:%M %p")}  
**System:** AI-Powered DDR Generator  

---

{report_text}

---

*This report was generated using an AI-assisted diagnostic system. All observations are based on data extracted from the provided inspection documents. Please verify critical findings with on-site professionals before proceeding with remediation work.*
"""

    path.write_text(full_content, encoding="utf-8")
    print(f"Report saved to: {path}")
    return str(path)


def save_report_pdf(report_text: str, output_path: str = None) -> str:
    """Save the DDR report as a PDF file."""
    try:
        from fpdf import FPDF
    except ImportError:
        print("fpdf2 not installed. Install with: pip install fpdf2")
        print("Falling back to Markdown output.")
        fallback_path = output_path.replace(".pdf", ".md") if output_path else None
        return save_report_markdown(report_text, fallback_path)

    if not output_path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"output/DDR_Report_{timestamp}.pdf"

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # sanitize text for PDF — replace unicode chars that Helvetica can't handle
    def _sanitize(text):
        replacements = {
            '\u2022': '-',     # bullet
            '\u2013': '-',     # en-dash
            '\u2014': '--',    # em-dash
            '\u2018': "'",     # left smart quote
            '\u2019': "'",     # right smart quote
            '\u201c': '"',     # left double smart quote
            '\u201d': '"',     # right double smart quote
            '\u2026': '...',   # ellipsis
            '\u00b0': 'deg',   # degree symbol
            '\u2190': '<-',
            '\u2192': '->',
            '\u2705': '[OK]',
            '\u26a0': '[!]',
            '\u274c': '[X]',
            '\u2248': '~',     # approximately
            '\u2265': '>=',    # greater than or equal
            '\u2264': '<=',    # less than or equal
            '\u00d7': 'x',     # multiplication sign
            '\u2103': 'degC',  # degree celsius
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        # remove any remaining non-latin1 chars
        text = text.encode('latin-1', errors='replace').decode('latin-1')
        return text

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "Detailed Diagnostic Report (DDR)", ln=True, align="C")
    pdf.ln(5)

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Generated on: {datetime.now().strftime('%d %B %Y, %I:%M %p')}", ln=True, align="C")
    pdf.ln(10)

    # convert markdown to plain text for reliable PDF rendering
    clean_lines = []
    for line in report_text.split('\n'):
        s = _sanitize(line.strip())
        # strip markdown formatting
        s = s.replace('**', '').replace('###', '').replace('##', '')
        clean_lines.append(s)

    full_text = '\n'.join(clean_lines)

    # write content as flowing text
    pdf.set_font("Helvetica", "", 10)
    for paragraph in full_text.split('\n\n'):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        # check if it looks like a section header (all caps or short)
        lines_in_para = paragraph.split('\n')
        first_line = lines_in_para[0].strip()

        # detect section headers (numbered like "1. PROPERTY..." or short titles)
        if (first_line and len(first_line) < 80 and
            (first_line[0].isdigit() or first_line.isupper()) and
            len(lines_in_para) == 1):
            pdf.ln(4)
            pdf.set_font("Helvetica", "B", 12)
            pdf.multi_cell(0, 7, first_line)
            pdf.ln(2)
            pdf.set_font("Helvetica", "", 10)
        else:
            for line in lines_in_para:
                line = line.strip()
                if not line:
                    pdf.ln(2)
                elif line == '---':
                    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
                    pdf.ln(3)
                else:
                    try:
                        pdf.multi_cell(0, 6, line)
                    except Exception:
                        # skip lines that can't be rendered
                        pass
            pdf.ln(3)

    # footer disclaimer
    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(0, 5,
        "This report was generated using an AI-assisted diagnostic system. "
        "All observations are based on data extracted from the provided inspection documents. "
        "Please verify critical findings with on-site professionals before proceeding with remediation work."
    )

    pdf.output(str(path))
    print(f"PDF report saved to: {path}")
    return str(path)
