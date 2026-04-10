# AgentProvision Feature Alignment

## Purpose
Document how the current AgentProvision application maps to the Master Prompt (`docs/prompt.md`) and outline the feature backlog and user flows needed for BusinessOps, LifeOps, and Hybrid tenants across the orchestration layer.

## Current Application Snapshot
- **Landing & marketing**: `apps/web/src/LandingPage.js`
- **Authentication**: `apps/web/src/pages/LoginPage.js`, `apps/web/src/pages/RegisterPage.js`
- **Core dashboard**: `apps/web/src/pages/DashboardPage.js`
- **Data operations**: `apps/web/src/pages/DataSourcesPage.js`, `apps/web/src/pages/DatasetsPage.js`, `apps/web/src/pages/DataPipelinesPage.js`
- **Agent operations**: `apps/web/src/pages/AgentsPage.js`, `apps/web/src/pages/AgentKitsPage.js`
- **Automation & tooling**: `apps/web/src/pages/ToolsPage.js`, `apps/web/src/pages/ConnectorsPage.js`, `apps/web/src/pages/DeploymentsPage.js`, `apps/web/src/pages/VectorStoresPage.js`
- **Conversational interface**: `apps/web/src/pages/ChatPage.js`

> Status: UI skeletons exist, but workflows are not yet wired to Temporal, DataLake, or agent orchestration services described in the Master Prompt.

## Tenant Alignment Overview

### BusinessOps Mode
- **Target tenants**: enterprise clients (Banco Falabella, Integral, EventBridge, Silvercreek, etc.)
- **Goals**: FinOps, RevOps, DevOps automation, governed insights, anomaly detection, executive reporting.
- **Existing assets**:
  - `DashboardPage.js` showcases analytics narratives and pipeline health (static data).
  - `DataSourcesPage.js`, `DatasetsPage.js`, and `DataPipelinesPage.js` manage ingestion primitives.
  - `ChatPage.js` allows dataset + agent kit chat sessions.
- **Gaps**:
  - No real orchestration with SchedulerAgent, DataAgent, IntegrationAgent.
  - No workflow status views (Temporal history, retries, governance approvals).
  - FinOps dashboards not backed by live connectors (AWS/Azure/GCP billing APIs).
- **Planned user flows**:
  - **FinOpsDashboardWorkflow**: connect billing APIs → normalize costs → anomaly detection → executive summary → Slack notification.
  - **GovernedDataProductFlow**: data product request → quality checks → security approvals → publish to catalog.
  - **ClosedLoopAutomationFlow**: insight detection → CoachAgent action plan → NotificationAgent follow-ups → AuditAgent logging.

### LifeOps Mode
- **Target tenant**: Personal Mastery ERP (Simon Aguilera) with LifeOps focus.
- **Goals**: discipline, health, journaling, energy management, Tao-inspired feedback loops.
- **Current app coverage**: none (only enterprise dashboards).
- **Required features**:
  - Journaling UI + prompts (JournalAgent).
  - Health/energy logging and visualization (HealthAgent, FocusAgent).
  - MorningRoutineWorkflow, MiddayResetWorkflow, EveningReflectionWorkflow (SchedulerAgent + NotificationAgent).
  - Personal insights feed with CoachAgent recommendations.
- **User flows to add**:
  - **MorningRoutineWorkflow**: at 07:00 create journal entry prompt → analyze prior entries → send focus recommendation.
  - **MiddayResetWorkflow**: midday energy check-in → suggestion for habit or break → log response.
  - **EveningReflectionWorkflow**: summarize day’s wins/lessons → set priority for tomorrow.

### Hybrid Mode
- **Target tenant**: founders/executives needing unified BusinessOps + LifeOps view.
- **Goals**: blend corporate metrics with personal effectiveness signals.
- **Feature direction**:
  - Unified dashboard slicing business KPIs beside personal discipline metrics.
  - Cross-domain insights (e.g., work calendar load impacting energy logs).
  - Role-based agents that can request data from both domains via orchestrator while respecting tenant boundaries.

## Agent & Workflow Alignment
- **SchedulerAgent**: needs Temporal-backed scheduling API; UI should surface workflow timelines, retries, and overrides.
- **DataAgent**: integrate `DataSourcesPage.js` and `DatasetsPage.js` with ingestion pipelines that persist to DataLake (S3 + Postgres + DuckDB).
- **IntegrationAgent**: connectors module must manage OAuth credentials, scopes, and sync status for Google/Slack/Stripe/etc.
- **InsightAgent**: power `DashboardPage.js` narratives and chat assistant responses with real analytics services and vector retrieval.
- **CoachAgent**: produce action recommendations surfaced in dashboards, notifications, and personal routines.
- **NotificationAgent**: unify outbound channels (Slack, Telegram, email) with templates and throttling.
- **AuditAgent**: centralize logs, metrics, streaks, and human feedback for compliance across tenants.

## Prioritized Feature Backlog
- **P1: Orchestration foundation**
  - Implement Temporal-backed workflow APIs for SchedulerAgent.
  - Wire DataAgent to ingest datasets into DataLake and expose status in UI.
  - Build IntegrationAgent credential management UI + API for core connectors (Google, Slack, AWS).
- **P2: BusinessOps workflows**
  - Activate FinOpsDashboardWorkflow with live cost ingestion and anomaly detection.
  - Add governance approval flow for data products (AuditAgent + NotificationAgent).
  - Extend chat assistant with InsightAgent retrieval from tenant vector stores.
- **P3: LifeOps routines**
  - Deliver Morning/Midday/Evening workflows with JournalAgent + NotificationAgent.
  - Create LifeOps dashboard summarizing energy, focus, habits, and insights.
  - Enable cross-tenant personalization via CoachAgent and hybrid insights.

## User Flow Definitions
- **FinOpsDashboardWorkflow** (BusinessOps)
  1. SchedulerAgent triggers periodic cost pulls via IntegrationAgent.
  2. DataAgent normalizes data into DWH schema.
  3. InsightAgent detects anomalies and trends; CoachAgent crafts narrative.
  4. UserInterfaceAgent updates dashboards and pushes summaries to Slack via NotificationAgent.
  5. AuditAgent logs execution, metrics, and feedback.

- **GovernedDataProductFlow** (BusinessOps)
  1. Data product request submitted from UI.
  2. DataAgent runs quality checks; AuditAgent records lineage and policies.
  3. Security approvals handled via NotificationAgent → human approval.
  4. Upon approval, product published; InsightAgent updates catalog.

- **MorningRoutineWorkflow** (LifeOps)
  1. SchedulerAgent triggers at 07:00.
  2. JournalAgent prompts daily entry; InsightAgent analyzes prior data.
  3. CoachAgent recommends priority; NotificationAgent delivers via Telegram.
  4. DataAgent logs responses to DataLake; AuditAgent tracks streaks.

## Documentation & Implementation Next Steps
- Create Temporal workflow definitions for prioritized flows (FinOps, Morning Routine) and add to repository.
- Update UI pages (`DashboardPage.js`, `AgentsPage.js`, `ChatPage.js`) with status cards linked to orchestrated workflows.
- Extend documentation with connector setup guides and tenant-specific onboarding playbooks.
- Coordinate backend services (Temporal workers, DataLake schema, Notification integrations) to match the Master Prompt architecture.

---

This document should be reviewed alongside `docs/prompt.md` before implementing new features to ensure consistency with the AgentProvision Orchestrator system definition.
