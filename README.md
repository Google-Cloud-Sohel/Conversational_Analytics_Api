# Conversational Analytics API vs MCP Toolbox

Two Google Cloud agents answer the same natural-language questions about the
same BigQuery e-commerce table, by different means, so the two approaches can
be compared under identical conditions.

| Agent | How it reaches the data |
|---|---|
| `ecom_agent` | Google's managed **Conversational Analytics** Data Agent generates and runs the SQL server-side |
| `ecom_mcp_agent` | The ADK agent writes its own GoogleSQL and executes it through **MCP Toolbox** |

Both are built with the [Agent Development Kit](https://google.github.io/adk-docs/)
and share the same business definitions, a mandatory output disclaimer, and the
same evaluation suite.

## Architecture

```
                    ┌─────────────────────────────┐
                    │   analytics_dataset          │
                    │   .ecom_orders_large          │
                    │   (BigQuery, 10k orders)      │
                    └──────────┬───────┬────────────┘
                               │       │
              SQL generated    │       │   SQL generated
              by Google        │       │   by the agent
                               │       │
        ┌──────────────────────┴─┐   ┌─┴──────────────────────┐
        │  Conversational         │   │  MCP Toolbox            │
        │  Analytics Data Agent   │   │  (Cloud Run)            │
        │  schema → SQL → run     │   │  4 BigQuery tools       │
        │  → narrative            │   │                         │
        └──────────┬──────────────┘   └─┬───────────────────────┘
                   │ one tool call      │ execute_sql
        ┌──────────┴──────────────┐   ┌─┴───────────────────────┐
        │  ecom_agent             │   │  ecom_mcp_agent         │
        │  short instruction,     │   │  full schema + rules    │
        │  delegates SQL          │   │  in every prompt        │
        └─────────────────────────┘   └─────────────────────────┘
                        ADK · gemini-2.5-flash
```

The difference is where the SQL is written. `ecom_agent` sends a question and
gets back an answer, with schema resolution, query generation, execution and
narrative synthesis all happening inside Google's Data Agent. `ecom_mcp_agent`
carries the table schema and business rules in its own prompt, writes the
GoogleSQL itself, and uses MCP Toolbox only to execute it.

That choice drives everything else: prompt size, how many round trips a
question costs, and where latency accumulates.

## Layout

```
create_data_agent.py          Creates/updates the Conversational Analytics Data Agent
ingest_bq_data.py             Generates 10,000 synthetic orders → BigQuery
ecom_agent/                   Conversational Analytics API agent
ecom_mcp_agent/               MCP Toolbox agent
MCP Toolbox/tools.yaml        Toolbox config: 4 BigQuery tools
tests/eval/                   Evaluation dataset, metrics, results
pyproject.toml                Dependencies (also required for agent-eval paths)
```

## Setup

Requires Python 3.10+, the [gcloud CLI](https://cloud.google.com/sdk/docs/install),
and a Google Cloud project with BigQuery and Vertex AI enabled.

```bash
python -m venv venv
source venv/bin/activate          # Windows: .\venv\Scripts\Activate.ps1
pip install -e .

gcloud auth login
gcloud auth application-default login
gcloud services enable aiplatform.googleapis.com bigquery.googleapis.com \
  geminidataanalytics.googleapis.com run.googleapis.com
```

Copy `.env.example` to `.env` in **both** agent folders and fill in the values.
Each example file documents what its agent needs and why.

### Data

> **Warning:** `ingest_bq_data.py` uses `WRITE_TRUNCATE` with unseeded random
> data. Re-running it replaces the table with different numbers, which
> invalidates the golden values in `tests/eval/dataset.jsonl`. Run it only when
> setting up a new project, and regenerate the goldens afterwards.

```bash
python ingest_bq_data.py
```

Creates `analytics_dataset.ecom_orders_large`:

| Column | Type |
|---|---|
| `order_id` | STRING |
| `customer_id` | INTEGER |
| `customer_name` | STRING |
| `product_category` | STRING |
| `quantity` | INTEGER |
| `order_amount` | FLOAT |
| `discount_percent` | INTEGER |
| `order_date` | TIMESTAMP |
| `status` | STRING |

Business definitions used by both agents: revenue is `SUM(order_amount)`,
customers is `COUNT(DISTINCT customer_id)`, and active orders excludes
`Cancelled` and `Refunded`. The table has no geographic, tax or margin columns;
both agents are instructed to say so rather than guess.

### `ecom_agent` — Conversational Analytics API

```bash
python create_data_agent.py       # creates, or updates if it already exists
adk web ecom_agent --port 8504
```

The script carries the business definitions as the Data Agent's system
instruction, so it — not `agent.py` — is what decides how revenue and active
orders are computed. Edit it there and re-run the script to apply changes.

### `ecom_mcp_agent` — MCP Toolbox

Deploy MCP Toolbox to Cloud Run using `MCP Toolbox/tools.yaml`, which exposes
`list_datasets`, `list_tables`, `get_table_info` and `execute_sql`. Put the
resulting URL in `TOOLBOX_URL`.

The agent authenticates with `CredentialStrategy.workload_identity()`. On Cloud
Run that resolves through the metadata server. **Locally there is no metadata
server**, so every tool call waits ~12 seconds and times out. For local runs,
point `GOOGLE_APPLICATION_CREDENTIALS` at a key for a service account holding
`roles/run.invoker` on the Toolbox service:

```bash
gcloud run services add-iam-policy-binding toolbox --region=us-central1 \
  --member="serviceAccount:YOUR_SA@PROJECT.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

Without that role the agent generates correct SQL but returns empty responses.

```bash
adk web ecom_mcp_agent --port 8503
```

## Evaluation

Uses [`agent-eval`](https://github.com/GoogleCloudPlatform/professional-services/tree/main/tools/agent-eval).

```bash
uv pip install "agent-eval @ git+https://github.com/GoogleCloudPlatform/professional-services.git@main#subdirectory=tools/agent-eval"
```

On Windows, run `git config --global core.longpaths true` first — the install
clones a monorepo containing paths over 260 characters.

`tests/eval/` holds 5 multi-turn and 5 single-turn test rows covering revenue,
customer counts, active orders, an unsupported-dimension request and a
typo-laden query. Six metrics score them: three managed Vertex AI judges
(`general_quality`, `hallucination`, `instruction_following`) and three
deterministic Python checks in `custom_metrics.py` — disclaimer compliance,
numeric accuracy against golden values, and out-of-domain refusal.

Start the agent's server, then run its evaluation. **One at a time** — both
share `tests/eval/dataset.jsonl` and `.agent_eval_tmp/`.

```powershell
$env:PYTHONUTF8 = "1"

# Point the dataset at the agent you are evaluating
(Get-Content "tests\eval\dataset.jsonl") -replace '"app_name": "ecom_agent"', '"app_name": "ecom_mcp_agent"' | Set-Content "tests\eval\dataset.jsonl"

agent-eval run --agent-dir "<absolute path>\ecom_mcp_agent" `
               --base-url "http://127.0.0.1:8503" --tag mcp
```

Every row's `app_name` must match the agent folder being evaluated, and
`--agent-dir` must be absolute — a relative path fails with a confusing
"directory does not exist" error. Results land in
`tests/eval/results/<run-id>/`, including a browsable `report.html`.

## License

Apache 2.0
