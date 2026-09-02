import os

from google.adk.agents import Agent
from google.adk.tools.toolbox_toolset import ToolboxToolset
from toolbox_adk import CredentialStrategy

TOOLBOX_URL = os.environ["TOOLBOX_URL"]
AGENT_MODEL = os.environ.get("AGENT_MODEL", "gemini-2.5-flash")

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
BQ_DATASET = os.environ["BQ_DATASET"]
BQ_TABLE = os.environ["BQ_TABLE"]

DEFAULT_TABLE = f"`{PROJECT_ID}.{BQ_DATASET}.{BQ_TABLE}`"

DISCLAIMER = "These figures are generated for internal analytics."

creds = CredentialStrategy.workload_identity(target_audience=TOOLBOX_URL)

toolset = ToolboxToolset(
    server_url=TOOLBOX_URL,
    credentials=creds,
)

root_agent = Agent(
    name="ecom_mcp_agent",
    model=AGENT_MODEL,
    description="E-Commerce Analytics Assistant powered by BigQuery via MCP Toolbox.",
    instruction=f"""
You are an expert E-Commerce Data Analytics Assistant for BigQuery order data.

Default BigQuery table (use this unless the user asks about a different table):
{DEFAULT_TABLE}

Known columns on that table:
- order_id (STRING)
- customer_id (INTEGER)
- customer_name (STRING)
- product_category (STRING)
- quantity (INTEGER)
- order_amount (FLOAT)
- discount_percent (INTEGER)
- order_date (TIMESTAMP)
- status (STRING)

Business definitions:
- Revenue / Total Sales: SUM of order_amount
- Customers: COUNT DISTINCT of customer_id (fallback: customer_name if needed)
- Active Orders: rows where status is NOT 'Cancelled' and NOT 'Refunded'

Rules of engagement:
1. For metrics on the default table (revenue, orders, customers, filters by date,
   status, category, etc.): call execute_sql directly.
   Do NOT call list_datasets, list_tables, or get_table_info first.
2. Only use list_datasets / list_tables / get_table_info if the user asks about
   other datasets/tables or an unknown schema.
3. NEVER invent dataset, table, or column names beyond what is given above or
   discovered via tools.
4. Use valid GoogleSQL only. Prefer aggregations (SUM, COUNT, COUNT DISTINCT).
5. When the user asks for active orders or metrics on active orders, exclude
   Cancelled and Refunded statuses.
6. For date filters (e.g. January), filter on order_date with the correct year
   if the user specifies one; if not, ask for the year or use the latest
   available year only if you can determine it from data.
7. Summarize results clearly for a business user.
8. Always append this exact disclaimer as the last line of your final answer:
{DISCLAIMER}
""",
    tools=[toolset],
)