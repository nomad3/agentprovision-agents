"""Data Analyst specialist agent.

Handles all data-related operations:
- Dataset discovery and exploration
- SQL query execution via Databricks
- Statistical analysis and insights
- Natural language to SQL conversion
"""
from google.adk.agents import Agent

from tools.data_tools import (
    discover_datasets,
    get_dataset_schema,
    get_dataset_statistics,
    query_sql,
    query_natural_language,
    generate_insights,
)
from tools.analytics_tools import (
    calculate,
    compare_periods,
    forecast,
)
from tools.knowledge_tools import (
    search_knowledge,
    record_observation,
)
from config.settings import settings


data_analyst = Agent(
    name="data_analyst",
    model=settings.adk_model,
    instruction="""You are a senior data analyst with expertise in SQL, statistics, and data visualization.

Your capabilities:
- Discover and explore available datasets
- Write and execute SQL queries on Databricks Unity Catalog
- Generate statistical insights and forecasts
- Answer natural language questions about data
- Perform calculations and comparisons

Guidelines:
1. Always explore the dataset schema before writing queries
2. Explain your analysis approach before executing
3. Use clear, well-formatted SQL with appropriate LIMIT clauses
4. Record important findings as observations for the knowledge graph
5. Suggest follow-up questions when you discover interesting patterns
6. Be precise with numbers and always cite data sources

When asked about data:
1. First, discover available datasets if needed
2. Get the schema to understand columns
3. Write and execute appropriate queries
4. Summarize findings in a clear, business-friendly way
""",
    tools=[
        discover_datasets,
        get_dataset_schema,
        get_dataset_statistics,
        query_sql,
        query_natural_language,
        generate_insights,
        calculate,
        compare_periods,
        forecast,
        search_knowledge,
        record_observation,
    ],
)
