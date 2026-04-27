# Luna latency benchmark — 2026-04-27

- base_url: `http://localhost:8000`
- tenant: `09f9f6f0-0c12-40fb-9fef-b5eb1cd9ad68`
- runs/cell: 2 (after 1 warmup)
- started: 2026-04-27T13:37:33.441928+00:00
- finished: 2026-04-27T13:46:55.340700+00:00

**v0 caveat:** Phase A per-stage instrumentation (recall_ms / cli_spawn_ms / cli_first_byte_ms / post_dispatch_ms) is not in yet. Numbers below are **end-to-end wall time** of `POST /messages/enhanced` — what the user feels.

## Summary by prompt class

| cell | n | n_fail | wall p50 | wall p95 | wall avg | server p50 | platforms |
|---|---|---|---|---|---|---|---|
| greeting | 2 | 0 | 21845 ms | 30258 ms | 26051 ms | 0 ms | local_gemma_tools |
| light_recall | 2 | 0 | 33452 ms | 41816 ms | 37634 ms | 0 ms | local_gemma_tools |
| entity_recall | 2 | 0 | 36915 ms | 42077 ms | 39496 ms | 0 ms | local_gemma_tools |
| tool_read | 2 | 0 | 34854 ms | 45190 ms | 40022 ms | 0 ms | local_gemma_tools |
| multi_step | 2 | 0 | 33003 ms | 36001 ms | 34502 ms | 0 ms | local_gemma_tools |

## Stage breakdown (avg ms)

| cell | cli_credentials_missing | local_llm_ms | local_overhead_ms | local_rounds | local_tool_agent | local_tool_ms | local_total_ms | setup |
|---|---|---|---|---|---|---|---|---|
| greeting | 1 | 25792 | 7 | 2 | 25863 | 62 | 25861 | 0 |
| light_recall | 1 | 37331 | 12 | 2 | 37431 | 86 | 37430 | 0 |
| entity_recall | 1 | 39173 | 5 | 2 | 39233 | 52 | 39231 | 0 |
| tool_read | 1 | 39704 | 16 | 2 | 39810 | 89 | 39809 | 0 |
| multi_step | 1 | 34212 | 6 | 2 | 34281 | 61 | 34280 | 0 |

## All rows

| cell | run | cold | wall | server | tokens | platform | ok | error / preview |
|---|---|---|---|---|---|---|---|---|
| greeting | 1 | Y | 21845 ms | — ms | — | local_gemma_tools | ✅ | ¡Hola! 👋 How can I help you today? I'm here to act as your co-pilot and help streamline things here at AgentProvision.   |
| greeting | 2 | N | 30258 ms | — ms | — | local_gemma_tools | ✅ | Hola! I'm Luna, your senior chief of staff and business co-pilot for the AgentProvision platform. How can I assist you t |
| light_recall | 1 | Y | 33452 ms | — ms | — | local_gemma_tools | ✅ | Basado en la revisión de nuestra memoria y registros recientes, no tengo acceso inmediato a la transcripción exacta de l |
| light_recall | 2 | N | 41816 ms | — ms | — | local_gemma_tools | ✅ | Lo siento, no tengo un resumen directo de lo que dijiste exactamente en nuestra última interacción, ya que la búsqueda d |
| entity_recall | 1 | Y | 36915 ms | — ms | — | local_gemma_tools | ✅ | Según la información que tengo registrada, reconozco el concepto de "tu negocio" como el tema central de nuestra convers |
| entity_recall | 2 | N | 42077 ms | — ms | — | local_gemma_tools | ✅ | Basándome en la información que tengo, entiendo que tu negocio es el tema central de nuestra conversación y que lo tengo |
| tool_read | 1 | Y | 34854 ms | — ms | — | local_gemma_tools | ✅ | I ran a check to find your recent workflows, but I don't have a specific list of them in my current memory or knowledge  |
| tool_read | 2 | N | 45190 ms | — ms | — | local_gemma_tools | ✅ | I checked your recent workflows using my available memory and knowledge graph, but I couldn't retrieve a list of your re |
| multi_step | 1 | Y | 33003 ms | — ms | — | local_gemma_tools | ✅ | No he podido encontrar un resumen específico de lo que pasó hoy utilizando mis sistemas de memoria o conocimiento genera |
| multi_step | 2 | N | 36001 ms | — ms | — | local_gemma_tools | ✅ | I ran a quick check through my memory and knowledge base for a summary of today's events, but I don't have any recent, o |
