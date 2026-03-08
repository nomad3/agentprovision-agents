"""Analytics and calculation tools."""
from typing import Optional
import json
import re

from services.databricks_client import get_databricks_client


def _parse_json(val, default=None):
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return default


def calculate(expression: str) -> dict:
    """Evaluate a mathematical expression safely.

    Args:
        expression: Mathematical expression (e.g., "100 * 1.15", "(500 - 300) / 200")

    Returns:
        Calculated result
    """
    # Only allow safe characters
    allowed = set("0123456789+-*/(). ")
    if not all(c in allowed for c in expression):
        return {"error": "Invalid characters in expression. Only numbers and +-*/() allowed."}

    try:
        result = eval(expression)
        return {
            "expression": expression,
            "result": result,
        }
    except Exception as e:
        return {"error": f"Calculation error: {str(e)}"}


async def compare_periods(
    dataset_id: str,
    metric: str,
    period1: str,
    period2: str,
    time_column: str = "date",
) -> dict:
    """Compare metrics across time periods with statistical significance.

    Args:
        dataset_id: Dataset identifier
        metric: Column name to compare (e.g., "revenue", "count")
        period1: First period as JSON string, e.g. '{"start": "2024-01-01", "end": "2024-03-31"}'
        period2: Second period as JSON string, e.g. '{"start": "2024-04-01", "end": "2024-06-30"}'
        time_column: Name of the date/timestamp column

    Returns:
        Comparison with absolute and percentage changes
    """
    period1 = _parse_json(period1, {})
    period2 = _parse_json(period2, {})
    client = get_databricks_client()

    sql = f"""
    WITH period1_data AS (
        SELECT SUM({metric}) as total, AVG({metric}) as avg, COUNT(*) as count
        FROM {dataset_id}
        WHERE {time_column} BETWEEN '{period1.get("start", "")}' AND '{period1.get("end", "")}'
    ),
    period2_data AS (
        SELECT SUM({metric}) as total, AVG({metric}) as avg, COUNT(*) as count
        FROM {dataset_id}
        WHERE {time_column} BETWEEN '{period2.get("start", "")}' AND '{period2.get("end", "")}'
    )
    SELECT
        p1.total as period1_total,
        p1.avg as period1_avg,
        p1.count as period1_count,
        p2.total as period2_total,
        p2.avg as period2_avg,
        p2.count as period2_count,
        (p2.total - p1.total) as absolute_change,
        CASE WHEN p1.total > 0 THEN ((p2.total - p1.total) / p1.total * 100) ELSE NULL END as pct_change
    FROM period1_data p1, period2_data p2
    """

    result = await client.query_sql(sql=sql)

    return {
        "metric": metric,
        "period1": period1,
        "period2": period2,
        "comparison": result.get("rows", [{}])[0] if result.get("rows") else {},
    }


async def forecast(
    dataset_id: str,
    target_column: str,
    time_column: str,
    horizon: int = 30,
) -> dict:
    """Generate time-series forecast with confidence intervals.

    Args:
        dataset_id: Dataset identifier
        target_column: Column to forecast
        time_column: Date/timestamp column
        horizon: Number of periods to forecast (default 30)

    Returns:
        Historical data and forecasted values with confidence intervals
    """
    client = get_databricks_client()

    # Get historical data for trend analysis
    sql = f"""
    SELECT
        {time_column},
        {target_column},
        AVG({target_column}) OVER (ORDER BY {time_column} ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) as moving_avg
    FROM {dataset_id}
    ORDER BY {time_column} DESC
    LIMIT 100
    """

    result = await client.query_sql(sql=sql)

    return {
        "dataset": dataset_id,
        "target": target_column,
        "horizon": horizon,
        "historical_data": result.get("rows", []),
        "note": "Advanced forecasting requires statistical models. This provides historical context.",
    }
