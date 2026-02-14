"""
PDF Text Extraction Module
Handles extracting and cleaning text from inspection & thermal report PDFs.
Uses pdfplumber as primary, falls back to PyPDF2 for tricky PDFs.
"""

import re
import sys
import os
import logging
import warnings
from pathlib import Path

# suppress noisy parsing warnings from PDF libraries
logging.getLogger("pdfminer").setLevel(logging.ERROR)
logging.getLogger("pdfplumber").setLevel(logging.ERROR)
logging.getLogger("PyPDF2").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", category=UserWarning, module="PyPDF2")


def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extract all text from a PDF file.
    Tries pdfplumber first, falls back to PyPDF2 if needed.
    Returns the combined text from all pages with page markers.
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # try pdfplumber first (better for tables and complex layouts)
    text = _extract_with_pdfplumber(str(path))

    # if pdfplumber got nothing useful, fall back to PyPDF2
    if not text or len(text.strip()) < 50:
        text = _extract_with_pypdf2(str(path))

    if not text or len(text.strip()) < 20:
        raise ValueError(f"No text could be extracted from: {pdf_path}")

    return text


def _extract_with_pdfplumber(file_path: str) -> str:
    """Extract text using pdfplumber."""
    try:
        import pdfplumber
    except ImportError:
        return ""

    all_text = []
    try:
        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                try:
                    text = page.extract_text()
                    if text and text.strip():
                        all_text.append(f"[Page {page_num}]\n{text.strip()}")
                    else:
                        tables = page.extract_tables()
                        if tables:
                            table_text = "\n".join(
                                " | ".join(str(cell or '') for cell in row)
                                for table in tables for row in table
                            )
                            if table_text.strip():
                                all_text.append(f"[Page {page_num}]\n{table_text}")
                except Exception:
                    pass
    except Exception:
        return ""

    return "\n\n".join(all_text)


def _extract_with_pypdf2(file_path: str) -> str:
    """Extract text using PyPDF2 as fallback."""
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        return ""

    all_text = []
    try:
        # suppress PyPDF2's noisy "Multiple definitions" stderr output
        _stderr = sys.stderr
        sys.stderr = open(os.devnull, 'w')
        try:
            reader = PdfReader(file_path, strict=False)
            for page_num, page in enumerate(reader.pages, start=1):
                try:
                    text = page.extract_text()
                    if text:
                        # fix UTF-16 encoded text (null bytes between chars)
                        cleaned = text.replace('\x00', '')
                        if cleaned.strip():
                            all_text.append(f"[Page {page_num}]\n{cleaned.strip()}")
                except Exception:
                    pass
        finally:
            sys.stderr.close()
            sys.stderr = _stderr
    except Exception:
        return ""

    return "\n\n".join(all_text)


def clean_extracted_text(raw_text: str) -> str:
    """
    Clean up common PDF extraction artifacts.
    - Collapse multiple spaces/newlines
    - Fix broken words at line endings
    - Remove page headers/footers if repeated
    """
    # collapse multiple spaces into one
    text = re.sub(r'[ \t]+', ' ', raw_text)

    # collapse 3+ newlines into 2
    text = re.sub(r'\n{3,}', '\n\n', text)

    # fix words broken across lines (ending with hyphen)
    text = re.sub(r'-\s*\n\s*', '', text)

    # strip leading/trailing whitespace per line
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)

    return text.strip()


def extract_inspection_report(pdf_path: str) -> dict:
    """
    Extract and structure data from the inspection report PDF.
    Returns a dict with identified sections.
    """
    raw_text = extract_text_from_pdf(pdf_path)
    cleaned = clean_extracted_text(raw_text)

    sections = {
        "raw_text": cleaned,
        "site_details": _extract_site_details(cleaned),
        "impacted_areas": _extract_impacted_areas(cleaned),
        "checklists": _extract_checklists(cleaned),
        "summary_table": _extract_summary_table(cleaned),
    }

    # warn if nothing meaningful was extracted
    if not sections["impacted_areas"] and sections["site_details"] == cleaned[:800]:
        # extraction fell through to fallbacks — pass raw text so LLM can still work
        sections["impacted_areas"] = [{
            "area_number": 1,
            "description": cleaned[:2000],
            "negative_side": "Not Available",
            "positive_side": "Not Available",
            "raw_content": cleaned[:2000],
        }]

    return sections


def extract_thermal_report(pdf_path: str) -> dict:
    """
    Extract and structure data from the thermal images PDF.
    Returns a dict with thermal readings per image.
    """
    raw_text = extract_text_from_pdf(pdf_path)
    cleaned = clean_extracted_text(raw_text)

    readings = _parse_thermal_readings(cleaned)

    return {
        "raw_text": cleaned,
        "readings": readings,
        "num_images": len(readings),
    }


# --- internal helpers ---

def _extract_site_details(text: str) -> str:
    """Pull out the site/property details section."""
    # look for the block between common header markers and the first area/checklist section
    # widened to handle various report formats
    patterns = [
        r'(Customer\s*Name.*?(?=Impacted\s*Area|Affected\s*Area|Observation\s*Area|Area\s*(?:of\s*)?(?:Concern|Inspection)|Checklists?|Check\s*List|Findings|$))',
        r'(Inspection\s*(?:Form|Report|Details?).*?(?=Impacted\s*Area|Affected\s*Area|Observation|Area\s*\d|Checklists?|$))',
        r'((?:Site|Property|Project)\s*(?:Details?|Information|Info).*?(?=Impacted\s*Area|Affected\s*Area|Observation|Area\s*\d|Checklists?|$))',
        r'((?:Client|Owner)\s*(?:Name|Details?).*?(?=Impacted\s*Area|Affected\s*Area|Observation|Area\s*\d|Checklists?|$))',
    ]
    for pat in patterns:
        match = re.search(pat, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    # fallback — first 800 chars
    return text[:800]


def _extract_impacted_areas(text: str) -> list:
    """Parse out individual impacted area observations."""
    areas = []

    # try multiple area header patterns (most specific first)
    area_patterns = [
        r'Impacted\s*Area\s*(\d+)',
        r'Affected\s*Area\s*(\d+)',
        r'Observation\s*Area\s*(\d+)',
        r'Area\s*(?:of\s*)?(?:Concern|Inspection)\s*(\d+)',
        r'(?:Location|Zone|Section)\s*(\d+)',
        r'Area\s*#?\s*(\d+)',
    ]

    parts = None
    for area_pat in area_patterns:
        parts = re.split(area_pat, text, flags=re.IGNORECASE)
        if len(parts) > 1:
            break

    if parts is None or len(parts) <= 1:
        # try alternate splitting by observation markers
        obs_patterns = [
            r'(?:Negative|Positive)\s*side\s*(?:Description|Observations?)',
            r'(?:Damage|Issue)\s*(?:Observed|Description)',
            r'Observation\s*(?:Details?|Description)',
        ]
        for obs_pat in obs_patterns:
            parts = re.split(obs_pat, text, flags=re.IGNORECASE)
            if len(parts) > 1:
                for i, part in enumerate(parts[1:], 1):
                    snippet = part[:500].strip()
                    if snippet:
                        areas.append({
                            "area_number": i,
                            "description": snippet,
                        })
                return areas
        return areas

    # process matched groups
    i = 1
    while i < len(parts) - 1:
        area_num = parts[i].strip()
        content = parts[i + 1].strip()

        # extract negative and positive side descriptions (widened patterns)
        neg_match = re.search(
            r'Negative\s*side\s*(?:Description|Observations?)\s*(.*?)(?=Positive\s*side|Impacted\s*Area|Affected\s*Area|Observation\s*Area|Area\s*#?\s*\d|$)',
            content, re.DOTALL | re.IGNORECASE
        )
        if not neg_match:
            neg_match = re.search(
                r'(?:Damage|Issue|Problem)\s*(?:Observed|Description|Details?)\s*:?\s*(.*?)(?=Positive\s*side|Probable\s*(?:Source|Cause)|Impacted|Affected|Area\s*#?\s*\d|$)',
                content, re.DOTALL | re.IGNORECASE
            )

        pos_match = re.search(
            r'Positive\s*side\s*(?:Description|Observations?)\s*(.*?)(?=Impacted\s*Area|Affected\s*Area|Observation\s*Area|Negative\s*side|Area\s*#?\s*\d|$)',
            content, re.DOTALL | re.IGNORECASE
        )
        if not pos_match:
            pos_match = re.search(
                r'(?:Probable\s*(?:Source|Cause)|Source\s*(?:of\s*)?(?:Issue|Problem|Leak))\s*:?\s*(.*?)(?=Impacted|Affected|Negative|Damage|Area\s*#?\s*\d|$)',
                content, re.DOTALL | re.IGNORECASE
            )

        area = {
            "area_number": int(area_num) if area_num.isdigit() else area_num,
            "negative_side": neg_match.group(1).strip()[:400] if neg_match else "Not Available",
            "positive_side": pos_match.group(1).strip()[:400] if pos_match else "Not Available",
            "raw_content": content[:600],
        }
        areas.append(area)
        i += 2

    return areas


def _extract_checklists(text: str) -> str:
    """Pull out checklist/inspection findings."""
    # try multiple patterns for checklist sections
    checklist_patterns = [
        r'(Checklists?.*?(?=SUMMARY\s*TABLE|Summary\s*(?:of\s*)?Findings|Appendix|$))',
        r'(Check\s*List.*?(?=SUMMARY|Summary|Appendix|$))',
        r'(Inspection\s*(?:Checklist|Findings).*?(?=SUMMARY|Summary|Appendix|$))',
        r'((?:Site|Building)\s*(?:Checklist|Check\s*List).*?(?=SUMMARY|Summary|Appendix|$))',
    ]
    for pat in checklist_patterns:
        match = re.search(pat, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()[:3000]  # cap it
    return "Not Available"


def _extract_summary_table(text: str) -> str:
    """Pull out the summary table if present."""
    summary_patterns = [
        r'(SUMMARY\s*TABLE.*?)(?=Appendix|Photo\s*1|$)',
        r'(Summary\s*(?:of\s*)?(?:Findings|Observations|Issues).*?)(?=Appendix|Photo|Annexure|$)',
        r'((?:Observation|Inspection)\s*Summary.*?)(?=Appendix|Photo|Annexure|$)',
        r'((?:Final|Overall)\s*Summary.*?)(?=Appendix|Photo|Annexure|$)',
    ]
    for pat in summary_patterns:
        match = re.search(pat, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return "Not Available"


def _parse_thermal_readings(text: str) -> list:
    """
    Parse thermal image data into structured readings.
    Each thermal page typically has: hotspot, coldspot, emissivity, date, image filename.
    """
    readings = []

    # split by page markers
    pages = re.split(r'\[Page\s*\d+\]', text)

    for page_text in pages:
        if not page_text.strip():
            continue

        reading = {}

        # hotspot temperature — handles: Hotspot, Hot Spot, Max Temp, Maximum Temperature
        hot = re.search(r'(?:Hot\s*spot|Max(?:imum)?\s*Temp(?:erature)?)\s*:?\s*([\d.]+\s*°?\s*C)', page_text, re.IGNORECASE)
        if hot:
            reading['hotspot'] = hot.group(1).replace(' ', '')
            if '°' not in reading['hotspot']:
                reading['hotspot'] = reading['hotspot'].replace('C', ' °C')

        # coldspot temperature — handles: Coldspot, Cold Spot, Min Temp, Minimum Temperature
        cold = re.search(r'(?:Cold\s*spot|Min(?:imum)?\s*Temp(?:erature)?)\s*:?\s*([\d.]+\s*°?\s*C)', page_text, re.IGNORECASE)
        if cold:
            reading['coldspot'] = cold.group(1).replace(' ', '')
            if '°' not in reading['coldspot']:
                reading['coldspot'] = reading['coldspot'].replace('C', ' °C')

        # emissivity
        emis = re.search(r'Emissivity\s*:?\s*([\d.]+)', page_text, re.IGNORECASE)
        if emis:
            reading['emissivity'] = emis.group(1)

        # reflected temperature
        ref = re.search(r'Reflected\s*(?:Apparent)?\s*Temp(?:erature)?\s*:?\s*([\d.]+\s*°?\s*C)', page_text, re.IGNORECASE)
        if ref:
            reading['reflected_temp'] = ref.group(1)

        # image filename — handles .jpg, .jpeg, .png, .bmp, .tiff
        img = re.search(r'(?:Thermal\s*)?[Ii]mage\s*:?\s*(\S+\.(?:jpe?g|png|bmp|tiff?))', page_text, re.IGNORECASE)
        if img:
            reading['image_file'] = img.group(1)

        # device info
        dev = re.search(r'(?:Device|Camera|Equipment)\s*:?\s*(.*?)(?:Serial|\n|$)', page_text, re.IGNORECASE)
        if dev:
            reading['device'] = dev.group(1).strip()

        # date — handles DD/MM/YY, DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY, YYYY-MM-DD
        date = re.search(r'(\d{2}[/\-.]\d{2}[/\-.]\d{2,4}|\d{4}[/\-.]\d{2}[/\-.]\d{2})', page_text)
        if date:
            reading['date'] = date.group(1)

        # image number — usually a standalone number at end
        num = re.search(r'\n(\d{1,3})\s*$', page_text.strip())
        if num:
            reading['image_number'] = int(num.group(1))

        if reading:  # only add if we found something
            readings.append(reading)

    return readings


if __name__ == "__main__":
    # quick test
    import json

    print("Testing inspection report extraction...")
    try:
        result = extract_inspection_report("input_docs/Sample Report.pdf")
        print(f"  Found {len(result['impacted_areas'])} impacted areas")
        print(f"  Site details length: {len(result['site_details'])} chars")
    except FileNotFoundError:
        print("  Sample report not found in input_docs/")

    print("\nTesting thermal report extraction...")
    try:
        result = extract_thermal_report("input_docs/Thermal Images.pdf")
        print(f"  Found {result['num_images']} thermal readings")
        if result['readings']:
            print(f"  First reading: {json.dumps(result['readings'][0], indent=2)}")
    except FileNotFoundError:
        print("  Thermal images not found in input_docs/")
