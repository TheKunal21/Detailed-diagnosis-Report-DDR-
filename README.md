# DDR Report Generator — AI-Powered Diagnostic Report Builder

An AI system that reads raw site inspection documents (Inspection Report + Thermal Images Report) and generates a structured **Detailed Diagnostic Report (DDR)** — ready for client delivery.

## What It Does

1. **Extracts** text from uploaded PDF inspection and thermal reports  
2. **Processes** the raw data — identifies observations, merges findings, flags conflicts  
3. **Generates** a structured DDR with clear sections using an LLM (Google Gemini)  
4. **Outputs** the final report as a downloadable Markdown/PDF file  

## DDR Output Structure

The generated report includes:
- Property Issue Summary  
- Area-wise Observations  
- Probable Root Cause  
- Severity Assessment (with reasoning)  
- Recommended Actions  
- Additional Notes  
- Missing or Unclear Information  

## Tech Stack

- **Python 3.10+**
- **PyPDF2** — PDF text extraction  
- **Google Generative AI (Gemini)** — LLM for report generation  
- **Streamlit** — Simple web UI for uploading docs and viewing reports  
- **FPDF2** — PDF output generation  

## Setup

### 1. Clone the repo
```bash
git clone <repo-url>
cd Assignment
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Set your API key
Create a `.env` file in the project root:
```
GOOGLE_API_KEY=your_gemini_api_key_here
```
You can get a free API key from [Google AI Studio](https://aistudio.google.com/apikey).

### 4. Run the Streamlit app
```bash
streamlit run app.py
```

### 5. Or run from command line
```bash
python main.py --inspection "input_docs/Sample Report.pdf" --thermal "input_docs/Thermal Images.pdf"
```

## How It Works

1. **PDF Extraction**: Uses PyPDF2 to pull raw text from both input documents. The extractor handles messy PDF formatting — extra whitespace, broken lines, table fragments.

2. **Data Processing**: A pre-processing step cleans the extracted text, structures it into logical chunks (site details, observations per area, checklist findings, thermal readings), and identifies any gaps or conflicts between the two documents.

3. **LLM Report Generation**: The cleaned data is fed to Google Gemini with a carefully designed prompt that:
   - Instructs the model to ONLY use facts from the documents (no hallucination)
   - Forces "Not Available" for missing information
   - Requires explicit mention of any conflicting data
   - Structures output into the required DDR sections
   - Uses client-friendly language

4. **Output**: The final DDR is formatted and can be downloaded as Markdown or PDF.

## Design Decisions

- **Why Gemini?** Free tier is generous (15 RPM, 1M tokens/min), good at structured extraction tasks, and handles long context well.
- **Why not fine-tuning?** The prompt-based approach generalizes better to different inspection reports without needing training data.
- **Why pre-processing before LLM?** Sending raw PDF text directly leads to hallucination. Cleaning and structuring first gives the LLM better signal.

## Limitations

- PDF text extraction can miss data from heavily formatted tables or image-only pages
- Thermal image data is text-based only (temperature readings) — actual thermal image analysis would need a vision model
- The system relies on the LLM following instructions — edge cases in very unusual reports might need prompt tweaks
- Photo references are extracted as labels only (Photo 1, Photo 2...) since actual images need separate handling

## What I'd Improve With More Time

- Add vision model (GPT-4V / Gemini Vision) to actually analyze thermal images and site photos
- Build a feedback loop where users can flag incorrect sections and the system learns
- Add multi-document comparison for tracking changes across inspections over time
- Implement structured validation — cross-check generated severity against actual readings
- Add support for more input formats (Word docs, Excel checklists)
