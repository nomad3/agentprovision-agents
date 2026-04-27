# Luna latency benchmark — 2026-04-27

- base_url: `http://localhost:8000`
- tenant: `09f9f6f0-0c12-40fb-9fef-b5eb1cd9ad68`
- runs/cell: 2 (after 1 warmup)
- started: 2026-04-27T13:21:58.651858+00:00
- finished: 2026-04-27T13:31:15.627533+00:00

**v0 caveat:** Phase A per-stage instrumentation (recall_ms / cli_spawn_ms / cli_first_byte_ms / post_dispatch_ms) is not in yet. Numbers below are **end-to-end wall time** of `POST /messages/enhanced` — what the user feels.

## Summary by prompt class

| cell | n | n_fail | wall p50 | wall p95 | wall avg | server p50 | platforms |
|---|---|---|---|---|---|---|---|
| greeting | 2 | 0 | 20805 ms | 29081 ms | 24943 ms | 0 ms | local_gemma_tools |
| light_recall | 2 | 0 | 34942 ms | 47518 ms | 41230 ms | 0 ms | local_gemma_tools |
| entity_recall | 2 | 0 | 35578 ms | 35765 ms | 35671 ms | 0 ms | local_gemma_tools |
| tool_read | 2 | 0 | 37838 ms | 39716 ms | 38777 ms | 0 ms | local_gemma_tools |
| multi_step | 2 | 0 | 34157 ms | 35392 ms | 34774 ms | 0 ms | local_gemma_tools |

## Stage breakdown (avg ms)

| cell | cli_credentials_missing | local_tool_agent | setup |
|---|---|---|---|
| greeting | 1 | 24788 | 0 |
| light_recall | 1 | 40927 | 0 |
| entity_recall | 1 | 35341 | 0 |
| tool_read | 1 | 38476 | 0 |
| multi_step | 1 | 34602 | 0 |

## All rows

| cell | run | cold | wall | server | tokens | platform | ok | error / preview |
|---|---|---|---|---|---|---|---|---|
| greeting | 1 | Y | 20805 ms | — ms | — | local_gemma_tools | ✅ | Hola! I'm Luna, your senior chief of staff and business co-pilot for AgentProvision. How can I assist you today? |
| greeting | 2 | N | 29081 ms | — ms | — | local_gemma_tools | ✅ | Hola. I'm Luna, your senior chief of staff and business co-pilot for the AgentProvision platform.  How can I help you to |
| light_recall | 1 | Y | 34942 ms | — ms | — | local_gemma_tools | ✅ | I'm sorry, but my search of our recent interactions didn't pull up the exact detail you are referring to.  To help you b |
| light_recall | 2 | N | 47518 ms | — ms | — | local_gemma_tools | ✅ | No tengo registro de lo que dijiste la última vez. El sistema de búsqueda de conocimiento no recuperó información especí |
| entity_recall | 1 | Y | 35765 ms | — ms | — | local_gemma_tools | ✅ | I don't have specific information about your business in my current memory or knowledge graph based on the general query |
| entity_recall | 2 | N | 35578 ms | — ms | — | local_gemma_tools | ✅ | Based on the knowledge graph search and entity retrieval, I don't have any specific information stored about "tu negocio |
| tool_read | 1 | Y | 39716 ms | — ms | — | local_gemma_tools | ✅ | I checked our knowledge base for your recent workflows using both entity lookups and general knowledge search, but I cou |
| tool_read | 2 | N | 37838 ms | — ms | — | local_gemma_tools | ✅ | I checked my knowledge base for "workflows," but unfortunately, I couldn't retrieve a list of your recent ones.  To help |
| multi_step | 1 | Y | 35392 ms | — ms | — | local_gemma_tools | ✅ | Based on my initial check of the available knowledge and memory, I do not have a recorded summary of what happened today |
| multi_step | 2 | N | 34157 ms | — ms | — | local_gemma_tools | ✅ | No tengo un resumen automático de los eventos de hoy. Los sistemas de memoria y conocimiento no arrojaron detalles espec |
