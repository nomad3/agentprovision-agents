"""Tool definitions for ServiceTsunami ADK server."""
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
    create_entity,
    find_entities,
    get_entity,
    update_entity,
    merge_entities,
    create_relation,
    find_relations,
    get_path,
    get_neighborhood,
    search_knowledge,
    store_knowledge,
    record_observation,
    ask_knowledge_graph,
    get_entity_timeline,
)
from tools.action_tools import (
    generate_report,
    create_visualization,
    export_data,
)

__all__ = [
    # Data tools
    "discover_datasets",
    "get_dataset_schema",
    "get_dataset_statistics",
    "query_sql",
    "query_natural_language",
    "generate_insights",
    # Analytics tools
    "calculate",
    "compare_periods",
    "forecast",
    # Knowledge tools
    "create_entity",
    "find_entities",
    "get_entity",
    "update_entity",
    "merge_entities",
    "create_relation",
    "find_relations",
    "get_path",
    "get_neighborhood",
    "search_knowledge",
    "store_knowledge",
    "record_observation",
    "ask_knowledge_graph",
    "get_entity_timeline",
    # Action tools
    "generate_report",
    "create_visualization",
    "export_data",
]
