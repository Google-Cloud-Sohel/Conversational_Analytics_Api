from google.cloud import geminidataanalytics_v1 as geminidataanalytics
from google.api_core.exceptions import AlreadyExists

# Configuration
PROJECT_ID = "keen-berm-506210-a8"
LOCATION = "global"
DATASET_ID = "analytics_dataset"
TABLE_ID = "ecom_orders_large"
DATA_AGENT_ID = "ecom_orders_analytics_agent"

def create_agent():
    client = geminidataanalytics.DataAgentServiceClient()
    parent = f"projects/{PROJECT_ID}/locations/{LOCATION}"

    # 1. Define the BigQuery source table reference
    bq_table = geminidataanalytics.BigQueryTableReference(
        project_id=PROJECT_ID,
        dataset_id=DATASET_ID,
        table_id=TABLE_ID
    )

    datasource_references = geminidataanalytics.DatasourceReferences(
        bq=geminidataanalytics.BigQueryTableReferences(
            table_references=[bq_table]
        )
    )

    # 2. Define instructions and bundle into Context
    system_instruction = """
    You are an expert E-Commerce Data Analytics Assistant.
    When answering questions, follow these business definitions:
    - 'Revenue' or 'Total Sales' refers to the sum of 'total_amount'.
    - 'Customers' refers to unique counts of 'customer_id' or 'customer_email'.
    - 'Active Orders' excludes orders where order_status is 'Cancelled' or 'Refunded'.
    - When analyzing by country, use 'customer_country'.
    """

    published_context = geminidataanalytics.Context(
        system_instruction=system_instruction,
        datasource_references=datasource_references
    )

    # 3. Create the nested DataAgent object
    data_agent = geminidataanalytics.DataAgent(
        display_name="E-Commerce Analytics Agent",
        description="Agent for querying e-commerce orders, customer behavior, and sales revenue.",
        data_analytics_agent=geminidataanalytics.DataAnalyticsAgent(
            published_context=published_context
        )
    )

    request = geminidataanalytics.CreateDataAgentRequest(
        parent=parent,
        data_agent_id=DATA_AGENT_ID,
        data_agent=data_agent
    )

    print(f"Creating Data Agent '{DATA_AGENT_ID}' in {parent}...")

    try:
        operation = client.create_data_agent(request=request)
        print("Waiting for Data Agent creation to complete...")
        response = operation.result()
        print("\nData Agent created successfully!")
        print(f"Resource Name: {response.name}")
        print(f"Display Name: {response.display_name}")
    except AlreadyExists:
        print(f"\nData Agent '{DATA_AGENT_ID}' already exists.")
        agent_path = f"{parent}/dataAgents/{DATA_AGENT_ID}"
        print(f"Resource Name: {agent_path}")

if __name__ == "__main__":
    create_agent()