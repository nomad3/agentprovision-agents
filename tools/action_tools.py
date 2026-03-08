"""Action and reporting tools.

Handles report generation, visualizations, and exports.
"""
from typing import Optional
import json


def _parse_json(val, default=None):
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return default


def generate_report(
    title: str,
    sections: list[str],
    format: str = "markdown",
) -> dict:
    """Generate structured report from analysis results.

    Args:
        title: Report title
        sections: List of section JSON strings, each with:
            - heading: Section title
            - content_type: 'chart', 'table', or 'text'
            - data: Content data
        format: Output format ('markdown', 'html')

    Returns:
        Formatted report content
    """
    parsed_sections = [_parse_json(s, {}) for s in sections] if sections else []

    if format == "markdown":
        report = f"# {title}\n\n"
        for section in parsed_sections:
            report += f"## {section.get('heading', 'Section')}\n\n"
            content_type = section.get('content_type', 'text')
            data = section.get('data', '')

            if content_type == 'text':
                report += f"{data}\n\n"
            elif content_type == 'table':
                # Format as markdown table
                if isinstance(data, list) and len(data) > 0:
                    headers = list(data[0].keys())
                    report += "| " + " | ".join(headers) + " |\n"
                    report += "| " + " | ".join(["---"] * len(headers)) + " |\n"
                    for row in data:
                        report += "| " + " | ".join(str(row.get(h, '')) for h in headers) + " |\n"
                    report += "\n"
            elif content_type == 'chart':
                report += f"[Chart: {section.get('heading', 'Chart')}]\n\n"
                report += f"```json\n{json.dumps(data, indent=2)}\n```\n\n"

        return {
            "format": format,
            "content": report,
            "title": title,
            "section_count": len(parsed_sections),
        }
    else:
        return {"error": f"Unsupported format: {format}"}


def create_visualization(
    data: str,
    chart_type: str,
    config: str,
) -> dict:
    """Create chart specification for frontend rendering.

    Args:
        data: Data to visualize as JSON string (rows, columns)
        chart_type: Type (bar, line, pie, scatter, heatmap, funnel, sankey)
        config: Chart configuration as JSON string with keys:
            title, x_axis, y_axis, color (optional), labels (boolean)

    Returns:
        Chart specification for frontend
    """
    data = _parse_json(data, {})
    config = _parse_json(config, {})

    valid_types = ["bar", "line", "pie", "scatter", "heatmap", "funnel", "sankey"]
    if chart_type not in valid_types:
        return {"error": f"Invalid chart type. Must be one of: {valid_types}"}

    spec = {
        "type": chart_type,
        "data": data,
        "config": {
            "title": config.get("title", "Chart"),
            "x_axis": config.get("x_axis"),
            "y_axis": config.get("y_axis"),
            "color": config.get("color"),
            "labels": config.get("labels", True),
        },
    }

    return {
        "chart_spec": spec,
        "chart_type": chart_type,
        "note": "Render this specification in the frontend visualization library",
    }


async def export_data(
    dataset_id: str,
    format: str,
    destination: str,
) -> str:
    """Export dataset to external destination.

    Args:
        dataset_id: Dataset to export
        format: Export format (csv, json, parquet)
        destination: Where to export as JSON string with keys:
            type ('gcs', 's3', 'email', 'webhook'), path (destination path or URL)

    Returns:
        Export job ID or download URL
    """
    destination = _parse_json(destination, {})

    valid_formats = ["csv", "json", "parquet"]
    if format not in valid_formats:
        return f"Invalid format. Must be one of: {valid_formats}"

    valid_destinations = ["gcs", "s3", "email", "webhook"]
    dest_type = destination.get("type", "")
    if dest_type not in valid_destinations:
        return f"Invalid destination type. Must be one of: {valid_destinations}"

    return {
        "status": "queued",
        "dataset_id": dataset_id,
        "format": format,
        "destination": destination,
        "note": "Export will be processed asynchronously",
    }
