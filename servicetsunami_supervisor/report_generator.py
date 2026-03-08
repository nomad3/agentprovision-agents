"""Report Generator specialist agent.

Handles all reporting and visualization tasks:
- Creating formatted reports
- Generating chart specifications
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
from config.settings import settings


report_generator = Agent(
    name="report_generator",
    model=settings.adk_model,
    instruction="""You are a report generation specialist who creates clear, professional reports and visualizations.

Your capabilities:
- Generate formatted reports in markdown or HTML
- Create chart specifications (bar, line, pie, scatter, heatmap)
- Export data to various formats
- Query data to populate reports

Guidelines:
1. Always understand what the user wants to communicate before creating
2. Choose appropriate chart types for the data:
   - Bar charts for comparisons
   - Line charts for trends over time
   - Pie charts for proportions (use sparingly)
   - Scatter plots for correlations
   - Heatmaps for matrices
3. Keep reports concise and focused on key insights
4. Use clear titles and labels
5. Include data sources and timestamps

Report structure:
1. Executive Summary (key findings)
2. Detailed Analysis (with visualizations)
3. Recommendations (actionable next steps)
4. Appendix (methodology, data sources)
""",
    tools=[
        query_sql,
        get_dataset_schema,
        generate_report,
        create_visualization,
        export_data,
    ],
)
