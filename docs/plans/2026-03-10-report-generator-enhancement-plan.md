# Report Generator Enhancement Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enhance the report_generator agent to accept uploaded PDFs/CSVs, extract structured data via LLM, and generate downloadable Excel reports + formatted chat summaries.

**Architecture:** Hybrid approach — ADK agent handles LLM-driven data extraction and mapping via new `report_tools.py`. API server handles Excel generation (`openpyxl`), file storage, and serving via new `reports.py` route. Existing multimedia upload pipeline (media_utils → ADK parts) carries files to the agent.

**Tech Stack:** Google ADK (Gemini), openpyxl (Excel generation), FastAPI (file serving), pdfplumber (existing PDF text extraction), httpx (ADK→API callbacks)

---

### Task 1: Add CSV/Excel Support to media_utils.py

**Files:**
- Modify: `apps/api/app/services/media_utils.py`

**Step 1: Add CSV/Excel MIME types and size limits**

Add after line 32 (`PDF_MIMES = {"application/pdf"}`):

```python
SPREADSHEET_MIMES = {
    "text/csv",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

MAX_SPREADSHEET_SIZE = 10 * 1024 * 1024  # 10 MB
```

**Step 2: Update classify_media to handle spreadsheets**

In `classify_media()`, add before the `return "unsupported"` line:

```python
    if clean in SPREADSHEET_MIMES:
        return "spreadsheet"
```

**Step 3: Add size check for spreadsheets in build_media_parts**

After the PDF size check (line 99-102), add:

```python
    if media_class == "spreadsheet" and size > MAX_SPREADSHEET_SIZE:
        raise ValueError(
            f"Spreadsheet too large: {size} bytes (max {MAX_SPREADSHEET_SIZE} bytes)"
        )
```

**Step 4: Add spreadsheet branch in build_media_parts**

Update the if/elif/else chain (lines 105-110) to include spreadsheets. Change the `else:` to `elif media_class == "pdf":` and add:

```python
    elif media_class == "spreadsheet":
        parts = _build_spreadsheet_parts(media_bytes, clean_mime, caption, filename)
```

And update `attachment_meta` — no changes needed, it already captures the type dynamically.

**Step 5: Implement _build_spreadsheet_parts helper**

Add at the end of the file:

```python
MAX_SPREADSHEET_CHARS = 50_000


def _build_spreadsheet_parts(
    file_bytes: bytes,
    mime_type: str,
    caption: str,
    filename: str,
) -> List[Dict]:
    """Extract text from CSV or Excel and return a text part."""
    try:
        if mime_type == "text/csv":
            text_content = file_bytes.decode("utf-8", errors="replace")
        else:
            # Excel file — extract with openpyxl
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
            sheets = []
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                rows = []
                for row in ws.iter_rows(values_only=True):
                    row_vals = [str(c) if c is not None else "" for c in row]
                    if any(v for v in row_vals):
                        rows.append(",".join(row_vals))
                if rows:
                    sheets.append(f"--- Sheet: {sheet_name} ---\n" + "\n".join(rows))
            text_content = "\n\n".join(sheets)

        truncated = False
        if len(text_content) > MAX_SPREADSHEET_CHARS:
            text_content = text_content[:MAX_SPREADSHEET_CHARS]
            truncated = True

        header_parts = []
        if filename:
            header_parts.append(f"Filename: {filename}")
        if truncated:
            header_parts.append(f"(truncated to {MAX_SPREADSHEET_CHARS} chars)")
        header = " | ".join(header_parts) if header_parts else "Spreadsheet"

        prompt = caption if caption else "The user sent a spreadsheet. Please review and respond."
        content = f"{prompt}\n\n--- Spreadsheet Content ({header}) ---\n{text_content}"

        return [{"text": content}]
    except Exception:
        logger.exception("Failed to extract spreadsheet content")
        return [{"text": f"{caption or 'The user sent a spreadsheet.'}\n\n[Could not extract spreadsheet content from {filename}]"}]
```

**Step 6: Commit**

```bash
git add apps/api/app/services/media_utils.py
git commit -m "feat: add CSV/Excel support to media_utils"
```

---

### Task 2: API Reports Route — Excel Generation & Download

**Files:**
- Create: `apps/api/app/api/v1/reports.py`
- Modify: `apps/api/app/api/v1/routes.py`

**Step 1: Create the reports route module**

Create `apps/api/app/api/v1/reports.py`:

```python
"""Report generation and download endpoints.

Accepts structured JSON data from the ADK report_generator agent,
builds Excel files using openpyxl, and serves them for download.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.models.user import User

router = APIRouter()

# ── File storage ──────────────────────────────────────────────────────────

REPORTS_DIR = Path("/tmp/servicetsunami_reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
REPORT_TTL_HOURS = 24


# ── Schemas ───────────────────────────────────────────────────────────────

class ProviderData(BaseModel):
    name: str
    role: str = "doctor"
    visits: Optional[int] = None
    gross_production: Optional[float] = None
    production_per_visit: Optional[float] = None
    treatment_presented: Optional[float] = None
    treatment_accepted: Optional[float] = None
    acceptance_rate: Optional[float] = None

class HygieneData(BaseModel):
    visits: Optional[int] = None
    capacity: Optional[int] = None
    capacity_pct: Optional[float] = None
    reappointment_rate: Optional[float] = None
    net_production: Optional[float] = None

class ProductionData(BaseModel):
    doctor: Optional[float] = None
    specialty: Optional[float] = None
    hygiene: Optional[float] = None
    total: Optional[float] = None
    net_production: Optional[float] = None
    collections: Optional[float] = None

class ReportRequest(BaseModel):
    practice_name: str = "Practice"
    report_period: str = ""
    production: Optional[ProductionData] = None
    providers: list[ProviderData] = []
    hygiene: Optional[HygieneData] = None
    report_title: Optional[str] = None

class ReportResponse(BaseModel):
    file_id: str
    download_url: str
    filename: str


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.post("/generate", response_model=ReportResponse)
def generate_report(
    payload: ReportRequest,
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Generate an Excel operations report from structured data."""
    _cleanup_expired_reports()

    file_id = str(uuid.uuid4())
    safe_name = payload.practice_name.replace(" ", "_")
    filename = f"{safe_name}_Operations_Report_{payload.report_period.replace(' ', '_')}.xlsx"
    file_path = REPORTS_DIR / f"{current_user.tenant_id}_{file_id}.xlsx"

    _build_excel(payload, file_path)

    base_url = os.environ.get("API_PUBLIC_URL", "")
    download_url = f"{base_url}/api/v1/reports/download/{file_id}"

    return ReportResponse(
        file_id=file_id,
        download_url=download_url,
        filename=filename,
    )


@router.get("/download/{file_id}")
def download_report(
    file_id: str,
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Download a generated Excel report."""
    file_path = REPORTS_DIR / f"{current_user.tenant_id}_{file_id}.xlsx"
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found or expired",
        )
    return FileResponse(
        path=str(file_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=file_path.name.split("_", 1)[-1] if "_" in file_path.name else file_path.name,
    )


# ── Excel builder ─────────────────────────────────────────────────────────

def _build_excel(data: ReportRequest, path: Path):
    """Build an operations report Excel file matching the dental template."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, numbers

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Operations Report"

    # ── Styles ──
    title_font = Font(name="Calibri", size=14, bold=True)
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
    subheader_font = Font(name="Calibri", size=10, bold=True)
    data_font = Font(name="Calibri", size=10)
    currency_fmt = '$#,##0.00'
    pct_fmt = '0.0%'
    number_fmt = '#,##0'

    row = 1

    # ── Title ──
    title = data.report_title or f"{data.practice_name} - Monthly Operations Report"
    ws.cell(row=row, column=1, value=title).font = title_font
    row += 1
    if data.report_period:
        ws.cell(row=row, column=1, value=f"Period: {data.report_period}").font = data_font
    row += 2

    # ── Column widths ──
    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 32
    ws.column_dimensions["C"].width = 18

    def write_section_header(r, text):
        cell = ws.cell(row=r, column=2, value=text)
        cell.font = header_font
        cell.fill = header_fill
        cell2 = ws.cell(row=r, column=3)
        cell2.fill = header_fill
        return r + 1

    def write_row(r, label, value, fmt=None, bold=False):
        c1 = ws.cell(row=r, column=2, value=label)
        c1.font = Font(name="Calibri", size=10, bold=bold)
        c2 = ws.cell(row=r, column=3, value=value)
        c2.font = Font(name="Calibri", size=10, bold=bold)
        if fmt and value is not None:
            c2.number_format = fmt
        c2.alignment = Alignment(horizontal="right")
        return r + 1

    # ── PRODUCTION & COLLECTIONS ──
    prod = data.production
    if prod:
        row = write_section_header(row, "PRODUCTION & COLLECTIONS")
        row = write_row(row, "Gross Production", None, bold=True)
        row = write_row(row, "  Doctor", prod.doctor, currency_fmt)
        row = write_row(row, "  Specialty", prod.specialty, currency_fmt)
        row = write_row(row, "  Hygiene", prod.hygiene, currency_fmt)
        row = write_row(row, "  Total", prod.total, currency_fmt, bold=True)
        row += 1
        row = write_row(row, "Net Production (Revenue)", prod.net_production, currency_fmt, bold=True)
        row = write_row(row, "Collections", prod.collections, currency_fmt, bold=True)
        if prod.net_production and prod.collections:
            pct = prod.collections / prod.net_production
            row = write_row(row, "  % Net Production", pct, pct_fmt)
        row += 1

    # ── PATIENT VISITS ──
    doctors = [p for p in data.providers if p.role == "doctor"]
    specialists = [p for p in data.providers if p.role == "specialist"]
    hygienists = [p for p in data.providers if p.role == "hygienist"]

    if any(p.visits for p in data.providers):
        row = write_section_header(row, "PATIENT VISITS")
        if doctors:
            row = write_row(row, "Doctors", None, bold=True)
            total_visits = 0
            for p in doctors:
                row = write_row(row, f"  {p.name}", p.visits, number_fmt)
                total_visits += p.visits or 0
            row = write_row(row, "  Total Doctors", total_visits, number_fmt, bold=True)

        if specialists:
            row = write_row(row, "Specialists", None, bold=True)
            for p in specialists:
                row = write_row(row, f"  {p.name}", p.visits, number_fmt)

        if hygienists:
            row = write_row(row, "Hygienists", None, bold=True)
            for p in hygienists:
                row = write_row(row, f"  {p.name}", p.visits, number_fmt)

        all_visits = sum(p.visits or 0 for p in data.providers)
        row = write_row(row, "Total", all_visits, number_fmt, bold=True)
        row += 1

    # ── GROSS PRODUCTION BY PROVIDER ──
    if any(p.gross_production for p in data.providers):
        row = write_section_header(row, "GROSS PRODUCTION BY PROVIDER")
        for p in data.providers:
            if p.gross_production:
                row = write_row(row, f"  {p.name}", p.gross_production, currency_fmt)
        total_gp = sum(p.gross_production or 0 for p in data.providers)
        row = write_row(row, "  Total", total_gp, currency_fmt, bold=True)
        row += 1

    # ── PRODUCTION PER VISIT ──
    if any(p.production_per_visit for p in data.providers):
        row = write_section_header(row, "PRODUCTION PER VISIT")
        for p in data.providers:
            if p.production_per_visit:
                row = write_row(row, f"  {p.name}", p.production_per_visit, currency_fmt)
        row += 1

    # ── CASE ACCEPTANCE ──
    if any(p.treatment_presented for p in data.providers):
        row = write_section_header(row, "CASE ACCEPTANCE")
        for p in data.providers:
            if p.treatment_presented:
                row = write_row(row, p.name, None, bold=True)
                row = write_row(row, "  Treatment Presented", p.treatment_presented, currency_fmt)
                row = write_row(row, "  Treatment Accepted", p.treatment_accepted, currency_fmt)
                row = write_row(row, "  Acceptance Rate", p.acceptance_rate, pct_fmt)
                row += 1

    # ── RECARE ──
    hyg = data.hygiene
    if hyg:
        row = write_section_header(row, "RECARE")
        row = write_row(row, "Capacity Utilization", None, bold=True)
        row = write_row(row, "  Hygiene Visits", hyg.visits, number_fmt)
        row = write_row(row, "  Hygiene Capacity", hyg.capacity, number_fmt)
        row = write_row(row, "  % Capacity", hyg.capacity_pct, pct_fmt)
        row += 1
        row = write_row(row, "Reappointment Rate", hyg.reappointment_rate, pct_fmt)
        row = write_row(row, "Hygiene Net Production", hyg.net_production, currency_fmt)

    wb.save(str(path))


def _cleanup_expired_reports():
    """Remove report files older than REPORT_TTL_HOURS."""
    cutoff = datetime.utcnow() - timedelta(hours=REPORT_TTL_HOURS)
    for f in REPORTS_DIR.iterdir():
        if f.is_file() and f.suffix == ".xlsx":
            mtime = datetime.utcfromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                f.unlink(missing_ok=True)
```

**Step 2: Register route in routes.py**

Add import at the top of `apps/api/app/api/v1/routes.py`:

```python
from app.api.v1 import reports
```

Add router inclusion:

```python
router.include_router(reports.router, prefix="/reports", tags=["reports"])
```

**Step 3: Commit**

```bash
git add apps/api/app/api/v1/reports.py apps/api/app/api/v1/routes.py
git commit -m "feat: add reports API for Excel generation and download"
```

---

### Task 3: ADK Report Tools

**Files:**
- Create: `apps/adk-server/tools/report_tools.py`

**Step 1: Create report_tools.py**

Create `apps/adk-server/tools/report_tools.py`:

```python
"""Report generation tools for the report_generator agent.

- extract_document_data: LLM-driven structured data extraction (returns guidance prompt)
- generate_excel_report: Sends structured JSON to API for Excel generation
"""
import json
import logging
from typing import Optional

import httpx

from config.settings import settings
from tools.knowledge_tools import _resolve_tenant_id

logger = logging.getLogger(__name__)

_api_client: Optional[httpx.AsyncClient] = None


def _get_api_client() -> httpx.AsyncClient:
    global _api_client
    if _api_client is None:
        _api_client = httpx.AsyncClient(
            base_url=settings.api_base_url,
            timeout=60.0,
        )
    return _api_client


def extract_document_data(
    file_text: str,
    filename: str,
    document_type: str = "auto",
) -> dict:
    """Provide the extraction schema for parsing uploaded document data.

    This tool returns the target JSON schema that the LLM should use
    to structure its extraction from the provided file text. The LLM
    reads the file_text and fills in the schema fields.

    Args:
        file_text: The raw text content extracted from the uploaded file
        filename: Original filename for context
        document_type: Type hint — "performance_summary", "treatment_plans",
                       "csv_report", or "auto" (LLM determines)

    Returns:
        Schema definition and extraction instructions
    """
    schema = {
        "practice_name": "string — name of the dental practice",
        "report_period": "string — month and year, e.g. 'June 2025'",
        "production": {
            "doctor": "float — total doctor gross production",
            "specialty": "float — total specialty gross production",
            "hygiene": "float — total hygiene gross production",
            "total": "float — total gross production",
            "net_production": "float — net production (revenue)",
            "collections": "float — total collections",
        },
        "providers": [
            {
                "name": "string — provider full name",
                "role": "string — 'doctor', 'specialist', or 'hygienist'",
                "visits": "int — patient visit count",
                "gross_production": "float — provider gross production",
                "production_per_visit": "float — production per visit",
                "treatment_presented": "float — total treatment presented $",
                "treatment_accepted": "float — total treatment accepted $",
                "acceptance_rate": "float — acceptance rate as decimal (0.319 not 31.9%)",
            }
        ],
        "hygiene": {
            "visits": "int — hygiene visit count",
            "capacity": "int — total hygiene capacity slots",
            "capacity_pct": "float — capacity utilization as decimal",
            "reappointment_rate": "float — reappointment rate as decimal",
            "net_production": "float — hygiene net production",
        },
    }

    return {
        "status": "schema_provided",
        "target_schema": schema,
        "instructions": (
            f"Extract data from the uploaded file '{filename}' (type: {document_type}). "
            "Parse all financial figures, provider names, visit counts, and rates. "
            "Return a JSON object matching the target_schema. Use null for missing fields. "
            "Convert percentages to decimals (31.9% → 0.319). "
            "Remove currency symbols and commas from numbers. "
            "If multiple files have been uploaded, merge data — do not overwrite."
        ),
        "file_preview": file_text[:2000] if file_text else "",
    }


async def generate_excel_report(
    report_data: str,
    tenant_id: str = "auto",
) -> dict:
    """Generate a downloadable Excel operations report.

    Sends the structured report data to the API server which builds
    an Excel file and returns a download URL.

    Args:
        report_data: JSON string with the complete report data matching
                     the schema from extract_document_data. Must include:
                     practice_name, report_period, production, providers, hygiene
        tenant_id: Tenant context. Use "auto" to resolve from session state.

    Returns:
        Download URL and filename for the generated Excel report
    """
    resolved_tid = _resolve_tenant_id(tenant_id)

    data = report_data
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return {"error": "Invalid JSON in report_data. Must be valid JSON matching the report schema."}

    if not isinstance(data, dict):
        return {"error": "report_data must be a JSON object."}

    required = ["practice_name", "report_period"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return {"error": f"Missing required fields: {missing}"}

    try:
        client = _get_api_client()
        resp = await client.post(
            "/api/v1/reports/generate",
            json=data,
            headers={"X-Tenant-ID": str(resolved_tid)},
        )
        resp.raise_for_status()
        result = resp.json()
        return {
            "status": "success",
            "download_url": result.get("download_url", ""),
            "filename": result.get("filename", ""),
            "file_id": result.get("file_id", ""),
            "message": f"Excel report generated: {result.get('filename', 'report.xlsx')}",
        }
    except httpx.HTTPStatusError as e:
        logger.error("Report generation API error: %s %s", e.response.status_code, e.response.text)
        return {"error": f"API error: {e.response.status_code} — {e.response.text[:200]}"}
    except Exception as e:
        logger.exception("Failed to generate Excel report")
        return {"error": f"Failed to generate report: {str(e)}"}
```

**Step 2: Commit**

```bash
git add apps/adk-server/tools/report_tools.py
git commit -m "feat: add ADK report_tools for data extraction and Excel generation"
```

---

### Task 4: Update report_generator Agent

**Files:**
- Modify: `apps/adk-server/servicetsunami_supervisor/report_generator.py`

**Step 1: Rewrite report_generator.py**

Replace the entire file content:

```python
"""Report Generator specialist agent.

Handles all reporting and visualization tasks:
- Extracting structured data from uploaded documents (PDFs, CSVs, Excel)
- Generating downloadable Excel reports
- Creating formatted reports and chart specifications
- Exporting data in various formats
"""
from google.adk.agents import Agent

from tools.data_tools import (
    query_sql,
    get_dataset_schema,
)
from tools.action_tools import (
    generate_report,
    create_visualization,
    export_data,
)
from tools.report_tools import (
    extract_document_data,
    generate_excel_report,
)
from config.settings import settings


report_generator = Agent(
    name="report_generator",
    model=settings.adk_model,
    instruction="""You are a report generation specialist who creates professional reports from uploaded documents and data.

## Core Capability: Document-to-Report Pipeline

When the user uploads files (PDFs, CSVs, Excel spreadsheets), you:

1. **Acknowledge each upload** — confirm what you received and what data you found
2. **Extract structured data** — use extract_document_data to get the target schema, then parse the file content into that schema
3. **Accumulate across files** — merge data from multiple uploads (don't overwrite, combine)
4. **Generate report on request** — when asked, use generate_excel_report with the aggregated data

## File Processing Guidelines

- **Performance Summary PDFs**: Extract provider-level production, collections, adjustments, visit counts
- **Treatment Plan PDFs**: Extract per-patient treatment details, CDT codes, fees, acceptance status
- **CSV/Excel files**: Extract all numerical data, identify column headers, map to report schema
- **Always convert**: Percentages to decimals (31.9% → 0.319), remove currency symbols/commas

## Report Generation Flow

When the user says "generate the report" (or similar):

1. Aggregate all extracted data into a single JSON matching the report schema
2. Call generate_excel_report with the complete JSON
3. Present results in chat with:
   - **Summary tables** in markdown showing key metrics (Production, Collections, Visits, Case Acceptance)
   - **Download link** for the Excel file
4. If data seems incomplete, tell the user what's missing and ask if they want to proceed

## Report Schema Fields

- practice_name, report_period
- production: doctor, specialty, hygiene, total, net_production, collections
- providers[]: name, role (doctor/specialist/hygienist), visits, gross_production, production_per_visit, treatment_presented, treatment_accepted, acceptance_rate
- hygiene: visits, capacity, capacity_pct, reappointment_rate, net_production

## Other Capabilities

You can also:
- Generate formatted reports in markdown or HTML (use generate_report)
- Create chart specifications for visualization (use create_visualization)
- Query data from datasets (use query_sql, get_dataset_schema)
- Export data to external destinations (use export_data)

## Guidelines
1. Always understand what the user wants before creating
2. Keep reports concise and focused on key insights
3. Use clear titles and labels
4. Include data sources and timestamps
5. When presenting financial data in chat, use proper currency formatting
""",
    tools=[
        query_sql,
        get_dataset_schema,
        generate_report,
        create_visualization,
        export_data,
        extract_document_data,
        generate_excel_report,
    ],
)
```

**Step 2: Commit**

```bash
git add apps/adk-server/servicetsunami_supervisor/report_generator.py
git commit -m "feat: enhance report_generator with document extraction and Excel tools"
```

---

### Task 5: Update Data Team Routing

**Files:**
- Modify: `apps/adk-server/servicetsunami_supervisor/data_team.py`

**Step 1: Update routing instructions**

In `data_team.py`, update the instruction string to include file/report routing:

```python
data_team = Agent(
    name="data_team",
    model=settings.adk_model,
    instruction="""You are the Data Team supervisor. You route data-related requests to the appropriate specialist.

IMPORTANT: You are a ROUTING agent only. You do NOT have tools. Your ONLY capability is to transfer tasks to your sub-agents using transfer_to_agent.

## Your team:
- **data_analyst** — SQL queries, statistical analysis, dataset discovery, natural language to SQL, insights generation
- **report_generator** — Formatted reports, chart/visualization specifications, data exports, document data extraction, Excel report generation

## Routing:
- Data queries, SQL, analytics, statistics, dataset exploration, insights -> transfer to data_analyst
- Reports, charts, visualizations, formatted outputs, data exports -> transfer to report_generator
- **File uploads (PDFs, CSVs, Excel)** for report generation -> transfer to report_generator
- **"Generate the report"** or **"create operations report"** -> transfer to report_generator
- Complex requests (analyze + visualize) -> transfer to data_analyst first, then report_generator
- "Show me the data on X" -> data_analyst
- "Create a report about X" -> report_generator

Always explain which specialist you're routing to and why.
""",
    sub_agents=[data_analyst, report_generator],
)
```

**Step 2: Commit**

```bash
git add apps/adk-server/servicetsunami_supervisor/data_team.py
git commit -m "feat: update data_team routing for document uploads and Excel reports"
```

---

### Task 6: Wire Reports Route Authentication for ADK Callbacks

The ADK server calls the API's `/api/v1/reports/generate` endpoint using `httpx`. The API requires JWT auth. ADK tools use the internal token endpoint pattern (like jira_tools, google_tools). However, the reports endpoint is simpler — the ADK can pass tenant_id via header and the API can accept internal calls.

**Files:**
- Modify: `apps/api/app/api/v1/reports.py`

**Step 1: Add internal generate endpoint that accepts tenant_id header**

Add an alternative internal endpoint that doesn't require JWT (for ADK→API calls), alongside the authenticated one:

```python
@router.post("/internal/generate", response_model=ReportResponse)
def generate_report_internal(
    payload: ReportRequest,
    *,
    db: Session = Depends(deps.get_db),
    tenant_id: str = None,
):
    """Internal endpoint for ADK agent callbacks. No JWT required."""
    if not tenant_id:
        from fastapi import Header
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")

    _cleanup_expired_reports()

    file_id = str(uuid.uuid4())
    safe_name = payload.practice_name.replace(" ", "_")
    filename = f"{safe_name}_Operations_Report_{payload.report_period.replace(' ', '_')}.xlsx"
    file_path = REPORTS_DIR / f"{tenant_id}_{file_id}.xlsx"

    _build_excel(payload, file_path)

    base_url = os.environ.get("API_PUBLIC_URL", "")
    download_url = f"{base_url}/api/v1/reports/download/{file_id}"

    return ReportResponse(
        file_id=file_id,
        download_url=download_url,
        filename=filename,
    )
```

Update the download endpoint to also work with a tenant_id query param for internal calls:

```python
@router.get("/download/{file_id}")
def download_report(
    file_id: str,
    tenant_id: Optional[str] = None,
):
    """Download a generated Excel report. Works with JWT auth or tenant_id param."""
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id required")

    # Find matching file
    file_path = REPORTS_DIR / f"{tenant_id}_{file_id}.xlsx"
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found or expired",
        )

    # Extract clean filename (strip tenant prefix)
    clean_name = file_path.name.split("_", 1)[-1] if "_" in file_path.name else file_path.name

    return FileResponse(
        path=str(file_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=clean_name,
    )
```

Update the ADK report_tools.py `generate_excel_report` to call the internal endpoint:

In `apps/adk-server/tools/report_tools.py`, change the API call URL:

```python
        resp = await client.post(
            "/api/v1/reports/internal/generate",
            json=data,
            headers={"X-Tenant-ID": str(resolved_tid)},
        )
```

**Step 2: Commit**

```bash
git add apps/api/app/api/v1/reports.py apps/adk-server/tools/report_tools.py
git commit -m "feat: add internal reports endpoint for ADK callbacks"
```

---

### Task 7: Deploy & Verify

**Step 1: Push changes**

```bash
git push origin main
```

This triggers CI/CD for both API and ADK services.

**Step 2: Monitor deployments**

```bash
kubectl rollout status deployment/servicetsunami-api -n prod
kubectl rollout status deployment/servicetsunami-adk -n prod
```

**Step 3: Test end-to-end**

1. Open chat at servicetsunami.com/chat
2. Upload a sample CSV or PDF
3. Verify the agent acknowledges the upload and describes extracted data
4. Say "generate the operations report"
5. Verify response includes markdown summary + download link
6. Click download link — verify Excel opens with proper formatting

---

## Summary of Changes

| Component | File | Action |
|-----------|------|--------|
| API media_utils | `apps/api/app/services/media_utils.py` | Add CSV/Excel support |
| API reports route | `apps/api/app/api/v1/reports.py` | New — Excel generation + download |
| API routes | `apps/api/app/api/v1/routes.py` | Register reports router |
| ADK report_tools | `apps/adk-server/tools/report_tools.py` | New — extraction schema + Excel generation tool |
| ADK report_generator | `apps/adk-server/servicetsunami_supervisor/report_generator.py` | Enhanced instructions + new tools |
| ADK data_team | `apps/adk-server/servicetsunami_supervisor/data_team.py` | Updated routing for file uploads |
