# Call Analytics Pipeline

Automated quality assurance system that processes call recordings, generates transcriptions locally, analyzes them using LLM, and populates structured results into Google Sheets.

## 🚀 Quick Start

### 1. Installation & Setup
```bash
# Clone the repository and navigate to the project folder
git clone https://github.com/MrEug3n1o/smart-call-tracker.git
cd smart-call-tracker

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install required dependencies
pip install -r requirements.txt
```

### 2. Set your Gemini API Key

```bash
export GEMINI_API_KEY="your_actual_gemini_api_key" 
# Windows (PowerShell): $env:GEMINI_API_KEY="your_actual_gemini_api_key"
```

### 3. Execution
```bash
python main.py \
  --folder-id "YOUR_GOOGLE_DRIVE_FOLDER_ID" \
  --sheet-id "YOUR_GOOGLE_SHEETS_ID" \
  --tab "Name of the tab"
```