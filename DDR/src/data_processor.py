"""
Data Processing Module
Merges inspection + thermal data, detects conflicts, fills gaps.
"""

from typing import Optional


def merge_inspection_and_thermal(inspection_data: dict, thermal_data: dict) -> dict:
    """
    Combine data from both reports into a unified structure
    that the LLM can work with effectively.
    
    This is the key step — we want to:
    1. Pair impacted areas with relevant thermal readings
    2. Flag any conflicts between documents
    3. Note what's missing from either source
    """
    merged = {
        "property_info": _build_property_info(inspection_data),
        "observations": _merge_observations(inspection_data, thermal_data),
        "thermal_summary": _summarize_thermal(thermal_data),
        "checklist_findings": inspection_data.get("checklists", "Not Available"),
        "summary_table": inspection_data.get("summary_table", "Not Available"),
        "conflicts": _detect_conflicts(inspection_data, thermal_data),
        "missing_info": _identify_missing(inspection_data, thermal_data),
    }

    return merged


def _build_property_info(inspection_data: dict) -> dict:
    """Extract basic property details."""
    site_text = inspection_data.get("site_details", "")

    info = {
        "raw_details": site_text,
    }

    # try to pull specific fields
    import re

    fields_to_find = {
        "property_type": r'Property\s*Type\s*:?\s*(.*?)(?:\n|$)',
        "address": r'Address\s*:?\s*(.*?)(?:\n|$)',
        "floors": r'Floors\s*:?\s*(\d+)',
        "property_age": r'Property\s*Age.*?:?\s*(\d+)',
        "inspection_date": r'Inspection\s*Date.*?:?\s*([\d./]+)',
        "inspected_by": r'Inspected\s*By\s*:?\s*(.*?)(?:\n|$)',
        "previous_repairs": r'Previous\s*Repair.*?:?\s*(Yes|No)',
        "previous_audit": r'Previous\s*Structural\s*audit.*?:?\s*(Yes|No)',
    }

    for key, pattern in fields_to_find.items():
        match = re.search(pattern, site_text, re.IGNORECASE)
        info[key] = match.group(1).strip() if match else "Not Available"

    return info


def _merge_observations(inspection_data: dict, thermal_data: dict) -> list:
    """
    Merge area-wise observations from inspection report
    with any corresponding thermal readings.
    """
    areas = inspection_data.get("impacted_areas", [])
    thermal_readings = thermal_data.get("readings", [])

    merged_observations = []

    for area in areas:
        obs = {
            "area_number": area.get("area_number", "Unknown"),
            "negative_side": area.get("negative_side", area.get("description", "Not Available")),
            "positive_side": area.get("positive_side", "Not Available"),
            "raw_content": area.get("raw_content", ""),
        }

        # try to match thermal readings to this area
        # thermal readings are numbered sequentially, roughly mapping to areas
        area_num = area.get("area_number", 0)
        if isinstance(area_num, int) and area_num > 0:
            # thermal images are usually grouped — roughly 2-3 per area
            start_idx = (area_num - 1) * 3
            end_idx = min(start_idx + 3, len(thermal_readings))
            related_thermal = thermal_readings[start_idx:end_idx]

            if related_thermal:
                obs["thermal_readings"] = related_thermal
                temps = [r.get("hotspot", "") for r in related_thermal if r.get("hotspot")]
                if temps:
                    obs["temperature_range"] = f"{min(temps)} to {max(temps)}"
            else:
                obs["thermal_readings"] = []
                obs["temperature_range"] = "Not Available"
        else:
            obs["thermal_readings"] = []
            obs["temperature_range"] = "Not Available"

        merged_observations.append(obs)

    return merged_observations


def _summarize_thermal(thermal_data: dict) -> dict:
    """Build a summary of all thermal findings."""
    readings = thermal_data.get("readings", [])

    if not readings:
        return {
            "total_images": 0,
            "overall_hotspot": "Not Available",
            "overall_coldspot": "Not Available",
            "device_used": "Not Available",
            "inspection_date": "Not Available",
        }

    # find overall max/min temperatures
    hotspots = []
    coldspots = []

    for r in readings:
        if "hotspot" in r:
            try:
                temp = float(r["hotspot"].replace("°C", "").strip())
                hotspots.append(temp)
            except ValueError:
                pass
        if "coldspot" in r:
            try:
                temp = float(r["coldspot"].replace("°C", "").strip())
                coldspots.append(temp)
            except ValueError:
                pass

    summary = {
        "total_images": len(readings),
        "overall_hotspot": f"{max(hotspots):.1f} °C" if hotspots else "Not Available",
        "overall_coldspot": f"{min(coldspots):.1f} °C" if coldspots else "Not Available",
        "avg_hotspot": f"{sum(hotspots)/len(hotspots):.1f} °C" if hotspots else "Not Available",
        "temp_differential": f"{max(hotspots) - min(coldspots):.1f} °C" if hotspots and coldspots else "Not Available",
        "device_used": readings[0].get("device", "Not Available") if readings else "Not Available",
        "inspection_date": readings[0].get("date", "Not Available") if readings else "Not Available",
        "emissivity": readings[0].get("emissivity", "Not Available") if readings else "Not Available",
    }

    return summary


def _detect_conflicts(inspection_data: dict, thermal_data: dict) -> list:
    """
    Look for inconsistencies between the two reports.
    This is important for the DDR — we must explicitly flag conflicts.
    """
    conflicts = []

    # check date consistency
    import re
    insp_text = inspection_data.get("site_details", "")
    date_match = re.search(r'(\d{2}\.\d{2}\.\d{4})', insp_text)
    insp_date = date_match.group(1) if date_match else None

    thermal_readings = thermal_data.get("readings", [])
    thermal_date = thermal_readings[0].get("date") if thermal_readings else None

    if insp_date and thermal_date:
        # normalize both dates for comparison
        # inspection might be DD.MM.YYYY, thermal might be DD/MM/YY
        # just flag if they seem different
        insp_parts = insp_date.split('.')
        thermal_parts = thermal_date.split('/')
        if len(insp_parts) >= 2 and len(thermal_parts) >= 2:
            if insp_parts[0] != thermal_parts[0] or insp_parts[1] != thermal_parts[1]:
                conflicts.append({
                    "type": "date_mismatch",
                    "detail": f"Inspection date ({insp_date}) differs from thermal scan date ({thermal_date}). "
                              f"Reports may have been prepared on different days.",
                })

    # check if number of impacted areas vs thermal images makes sense
    num_areas = len(inspection_data.get("impacted_areas", []))
    num_thermal = thermal_data.get("num_images", 0)

    if num_areas > 0 and num_thermal == 0:
        conflicts.append({
            "type": "missing_thermal",
            "detail": f"Inspection report has {num_areas} impacted areas, but no thermal readings found.",
        })

    return conflicts


def _identify_missing(inspection_data: dict, thermal_data: dict) -> list:
    """
    Identify information that's missing or marked N/A.
    The DDR must explicitly call these out.
    """
    missing = []

    # check property info
    site_text = inspection_data.get("site_details", "")
    if "N/A" in site_text or not site_text:
        missing.append("Some property details are marked as N/A or not available")

    # check if impacted areas are empty
    areas = inspection_data.get("impacted_areas", [])
    if not areas:
        missing.append("No impacted areas could be extracted from the inspection report")

    for area in areas:
        neg = area.get("negative_side", "")
        pos = area.get("positive_side", "")
        num = area.get("area_number", "?")

        if neg == "Not Available":
            missing.append(f"Impacted Area {num}: Negative side description not available")
        if pos == "Not Available":
            missing.append(f"Impacted Area {num}: Positive side description not available")

    # check thermal data
    if not thermal_data.get("readings"):
        missing.append("No thermal readings could be extracted from the thermal report")

    # check checklist
    checklists = inspection_data.get("checklists", "")
    if checklists == "Not Available" or not checklists:
        missing.append("Inspection checklists section not found")

    return missing


def format_merged_data_for_llm(merged_data: dict) -> str:
    """
    Convert the merged data dict into a clean text block
    that we can pass to the LLM as context.
    """
    sections = []

    # property info
    prop = merged_data.get("property_info", {})
    sections.append("=== PROPERTY INFORMATION ===")
    for key, val in prop.items():
        if key != "raw_details":
            sections.append(f"  {key.replace('_', ' ').title()}: {val}")
    sections.append("")

    # observations
    sections.append("=== AREA-WISE OBSERVATIONS ===")
    for obs in merged_data.get("observations", []):
        sections.append(f"\n--- Area {obs['area_number']} ---")
        sections.append(f"  Negative side (damage): {obs['negative_side']}")
        sections.append(f"  Positive side (source): {obs['positive_side']}")
        if obs.get("temperature_range") and obs["temperature_range"] != "Not Available":
            sections.append(f"  Temperature range: {obs['temperature_range']}")
        if obs.get("thermal_readings"):
            for tr in obs["thermal_readings"]:
                sections.append(f"  Thermal: Hotspot={tr.get('hotspot','N/A')}, Coldspot={tr.get('coldspot','N/A')}")
    sections.append("")

    # thermal summary
    sections.append("=== THERMAL SCAN SUMMARY ===")
    ts = merged_data.get("thermal_summary", {})
    for key, val in ts.items():
        sections.append(f"  {key.replace('_', ' ').title()}: {val}")
    sections.append("")

    # checklist
    sections.append("=== CHECKLIST FINDINGS ===")
    sections.append(merged_data.get("checklist_findings", "Not Available"))
    sections.append("")

    # summary table
    sections.append("=== SUMMARY TABLE FROM INSPECTION ===")
    sections.append(merged_data.get("summary_table", "Not Available"))
    sections.append("")

    # conflicts
    sections.append("=== IDENTIFIED CONFLICTS ===")
    conflicts = merged_data.get("conflicts", [])
    if conflicts:
        for c in conflicts:
            sections.append(f"  ⚠ {c['type']}: {c['detail']}")
    else:
        sections.append("  No conflicts detected between the two reports.")
    sections.append("")

    # missing info
    sections.append("=== MISSING INFORMATION ===")
    missing = merged_data.get("missing_info", [])
    if missing:
        for m in missing:
            sections.append(f"  • {m}")
    else:
        sections.append("  All expected information is present.")

    return "\n".join(sections)
