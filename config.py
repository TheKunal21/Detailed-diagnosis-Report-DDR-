"""
Configuration settings for the DDR Report Generator.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- LLM Settings ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
LLM_MODEL = "gemini-1.5-flash"
LLM_TEMPERATURE = 0.3           # lower = more factual
LLM_MAX_TOKENS = 8000
VALIDATION_TEMPERATURE = 0.2

# --- Output Settings ---
OUTPUT_DIR = "output"
DEFAULT_OUTPUT_FORMAT = "both"   # "md", "pdf", or "both"

# --- Processing Settings ---
MAX_TEXT_PER_SECTION = 3000      # cap text length per section to avoid token limits
THERMAL_IMAGES_PER_AREA = 3     # rough mapping of thermal images to each impacted area
