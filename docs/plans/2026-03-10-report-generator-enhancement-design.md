# Report Generator Enhancement — Design

## Goal

Enhance the report_generator agent to accept uploaded PDFs and CSVs, extract structured data via LLM, and generate downloadable Excel reports matching a configurable template format. Both formatted chat summary and Excel download link returned.

## Architecture

Hybrid approach: ADK agent handles AI-driven data extraction and mapping. API server handles Excel generation, file storage, and serving.

```
User uploads files (PDF/CSV) in chat
  → media_utils extracts raw text (pdfplumber for PDFs, csv reader for CSVs)
  → Text passed to ADK agent as message parts
  → LLM extracts structured JSON from each file on upload
  → Structured data accumulated in session state

User says "generate the report"
  → report_generator aggregates all extracted JSON
  → Calls generate_excel_report tool → POST /api/v1/reports/generate
  → API builds Excel with openpyxl, stores file, returns download URL
  → Agent responds with formatted summary + download link
```

## Components

### ADK Server

**`tools/report_tools.py`** (new):
- `extract_document_data(file_text, filename, document_type)` — LLM extracts structured JSON from uploaded file
- `generate_excel_report(report_data, report_title, tenant_id)` — Sends aggregated JSON to API, returns download URL

**`report_generator.py`** (modify):
- Enhanced instructions for file extraction on upload
- Aggregation and report generation flow
- Returns both chat summary and download link

### API Server

**`app/api/v1/reports.py`** (new):
- `POST /api/v1/reports/generate` — Accepts structured JSON, builds Excel, returns download URL
- `GET /api/v1/reports/download/{file_id}` — Serves generated Excel, tenant-scoped

**`media_utils.py`** (modify):
- Add CSV/Excel file classification and text extraction

**Dependencies:** `openpyxl` in API requirements.txt

## Structured Data Schema

```json
{
  "practice_name": "string",
  "report_period": "string",
  "production": {
    "doctor": 0.0,
    "specialty": 0.0,
    "hygiene": 0.0,
    "total": 0.0,
    "net_production": 0.0,
    "collections": 0.0
  },
  "providers": [
    {
      "name": "string",
      "role": "doctor|specialist|hygienist",
      "visits": 0,
      "gross_production": 0.0,
      "production_per_visit": 0.0,
      "treatment_presented": 0.0,
      "treatment_accepted": 0.0,
      "acceptance_rate": 0.0
    }
  ],
  "hygiene": {
    "visits": 0,
    "capacity": 0,
    "capacity_pct": 0.0,
    "reappointment_rate": 0.0,
    "net_production": 0.0
  }
}
```

LLM populates from any file format. Null fields result in blank Excel cells.

## Constraints

- File size: Existing limits (PDFs 20MB, CSVs/Excel 10MB)
- Extraction failures: Agent tells user what it couldn't parse
- Partial data: Report generates with available data, blank cells for missing
- File cleanup: Auto-delete generated files after 24 hours
- Tenant isolation: Download URLs tenant-scoped
- No new database models: Files are ephemeral

## Date

2026-03-10
