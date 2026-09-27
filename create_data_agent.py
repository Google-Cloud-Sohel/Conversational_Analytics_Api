from google.cloud import geminidataanalytics_v1 as geminidataanalytics
from google.api_core.exceptions import AlreadyExists
from google.protobuf import field_mask_pb2

# Configuration
PROJECT_ID = "keen-berm-506210-a8"
LOCATION = "global"
DATASET_ID = "analytics_dataset"
TABLE_ID = "ecom_orders_large"
DATA_AGENT_ID = "ecom_orders_analytics_agent"

# Must match the real BigQuery schema of analytics_dataset.ecom_orders_large:
# order_id, customer_id, customer_name, product_category, quantity,
# order_amount, discount_percent, order_date (TIMESTAMP), status
SYSTEM_INSTRUCTION = """
You are an expert E-Commerce Data Analytics Assistant.
When answering questions, follow these business definitions:
- 'Revenue' or 'Total Sales' refers to the sum of 'order_amount'.
- 'Customers' refers to unique counts of 'customer_id' (or 'customer_name').
- 'Active Orders' excludes orders where 'status' is 'Cancelled' or 'Refunded'.
- Order dates are in 'order_date' (TIMESTAMP).
- The table has no country or region field. If asked about geography,
  say that this data is not available.
"""

DISPLAY_NAME = "E-Commerce Analytics Agent"
DESCRIPTION = "Agent for querying e-commerce orders, customer behavior, and sales revenue."


def build_data_agent(name: str | None = None) -> geminidataanalytics.DataAgent:
    """Builds the DataAgent object (used for both create and update)."""
    bq_table = geminidataanalytics.BigQueryTableReference(
        project_id=PROJECT_ID,
        dataset_id=DATASET_ID,
        table_id=TABLE_ID,
    )

    datasource_references = geminidataanalytics.DatasourceReferences(
        bq=geminidataanalytics.BigQueryTableReferences(
            table_references=[bq_table]
        )
    )

    published_context = geminidataanalytics.Context(
        system_instruction=SYSTEM_INSTRUCTION,
        datasource_references=datasource_references,
    )

    kwargs = dict(
        display_name=DISPLAY_NAME,
        description=DESCRIPTION,
        data_analytics_agent=geminidataanalytics.DataAnalyticsAgent(
            published_context=published_context
        ),
    )
    if name:
        kwargs["name"] = name
    return geminidataanalytics.DataAgent(**kwargs)


def create_or_update_agent():
    client = geminidataanalytics.DataAgentServiceClient()
    parent = f"projects/{PROJECT_ID}/locations/{LOCATION}"
    agent_path = f"{parent}/dataAgents/{DATA_AGENT_ID}"

    # 1. Try to create the agent.
    create_request = geminidataanalytics.CreateDataAgentRequest(
        parent=parent,
        data_agent_id=DATA_AGENT_ID,
        data_agent=build_data_agent(),
    )

    print(f"Creating Data Agent '{DATA_AGENT_ID}' in {parent}...")

    try:
        operation = client.create_data_agent(request=create_request)
        print("Waiting for Data Agent creation to complete...")
        response = operation.result()
        print("\nData Agent created successfully!")
        print(f"Resource Name: {response.name}")
        print(f"Display Name: {response.display_name}")
        return
    except AlreadyExists:
        print(f"Data Agent '{DATA_AGENT_ID}' already exists. Updating it instead...")

    # 2. It already exists, so update it in place with the current instruction
    #    and data source.
    update_request = geminidataanalytics.UpdateDataAgentRequest(
        data_agent=build_data_agent(name=agent_path),
        update_mask=field_mask_pb2.FieldMask(
            paths=[
                "display_name",
                "description",
                "data_analytics_agent.published_context",
            ]
        ),
    )

    operation = client.update_data_agent(request=update_request)
    print("Waiting for Data Agent update to complete...")
    response = operation.result()
    print("\nData Agent updated successfully!")
    print(f"Resource Name: {response.name}")
    print(f"Display Name: {response.display_name}")


if __name__ == "__main__":
    create_or_update_agent()