# Integrations Hub: Architecture and Implementation Plan

## 1. Vision & Core Concepts

The Integrations Hub will be the central place in AgentProvision for connecting to external data sources and services. It will function like a marketplace where users can discover, configure, and manage all third-party integrations. This is a key step towards making AgentProvision a data-driven platform, similar to PostgreSQL, by enabling seamless data ingestion and automation.

**Key Components:**

*   **Connectors:** Reusable components that connect to specific services (e.g., Salesforce, Snowflake, a generic REST API). We will leverage **n8n** as the engine for building and executing these connectors.
*   **Apache Spark:** For large-scale, distributed data processing jobs that can be triggered by data pipelines, which in turn can be fed by our connectors.
*   **Data-Driven Backend:** The FastAPI backend will be extended to manage integrations, credentials, and orchestrate n8n workflows and Spark jobs.
*   **Intuitive Frontend:** The React-based dashboard will provide a user-friendly interface for managing the entire integration lifecycle.

## 2. Data Model Extensions

To support the Integrations Hub, we will extend the existing data model:

*   **`Connector` Model:** This will be enhanced to store more metadata, such as:
    *   `type`: (e.g., `n8n`, `spark`)
    *   `n8n_workflow_id`: The ID of the n8n workflow that powers this connector.
    *   `spark_job_id`: The ID of the Spark job associated with this connector.
    *   `schema`: A JSON field to define the expected configuration schema for the connector (e.g., API keys, hostnames).

*   **`Credential` Model (New):** A new model to securely store encrypted credentials for connectors. This will be linked to a `Tenant` and a `Connector`.

*   **`Integration` Model (New):** Represents a user-configured instance of a `Connector`. It will store the user-provided configuration and a reference to the `Credential`.

## 3. Backend Implementation (FastAPI)

### 3.1. Apache Spark & n8n Integration

*   **n8n:** We will add an n8n container to our `docker-compose.yml`. The API will communicate with the n8n API to trigger workflows (connectors).
*   **Apache Spark:** We will add a Spark container to our `docker-compose.yml`. The API will use Spark's REST API (Livy) or `spark-submit` to execute jobs.

### 3.2. API Endpoints

We will create new API endpoints under `/api/v1/integrations`:

*   `GET /integrations/available`: List all available connectors (from a predefined catalog or discovered from n8n).
*   `POST /integrations/`: Create a new user-configured integration (an instance of a connector).
*   `GET /integrations/`: List all of the user's configured integrations.
*   `GET /integrations/{id}`: Get details of a specific integration.
*   `PUT /integrations/{id}`: Update an integration's configuration.
*   `DELETE /integrations/{id}`: Delete an integration.
*   `POST /integrations/{id}/run`: Trigger an integration (e.g., run an n8n workflow or a Spark job).

## 4. Frontend Implementation (React)

### 4.1. UI/UX Design

The Integrations Hub in the dashboard will have:

*   **A gallery/marketplace view:** Displaying available connectors with logos, descriptions, and categories.
*   **A configuration wizard:** A step-by-step modal or page to guide users through setting up a new integration, including providing credentials and configuration parameters.
*   **A list view:** Showing the user's configured integrations with their status, last run time, and actions (run, edit, delete).

### 4.2. Component Plan

*   `IntegrationsHubPage.js`: The main page for the Integrations Hub.
*   `ConnectorCard.js`: A card component for the marketplace view.
*   `IntegrationForm.js`: A form/wizard for configuring a new integration.
*   `IntegrationsList.js`: A table or list to display configured integrations.

## 5. Implementation Steps

1.  **Backend:**
    *   Add Spark and n8n to `docker-compose.yml`.
    *   Extend the `Connector` model and create the `Credential` and `Integration` models.
    *   Create the corresponding schemas and services.
    *   Implement the new API endpoints.
2.  **Frontend:**
    *   Create the placeholder pages and components for the Integrations Hub.
    *   Implement the UI/UX for the marketplace, configuration, and list views.
    *   Connect the frontend to the new backend API endpoints.

This plan provides a comprehensive roadmap for building a powerful and user-friendly Integrations Hub, making AgentProvision a true data-driven platform.
