# _bq_data.py
import pandas as pd
from faker import Faker
import random
from google.cloud import bigquery
from google.api_core.exceptions import NotFound

def generate_ecommerce_data(num_records=10000):
    fake = Faker()
    categories = ['Electronics', 'Apparel', 'Home & Garden', 'Sports', 'Toys', 'Books', 'Beauty']
    statuses = ['Pending', 'Processing', 'Shipped', 'Delivered', 'Cancelled', 'Refunded']

    data = []
    for _ in range(num_records):
        data.append({
           "order_id": fake.uuid4(),
            "customer_id": random.randint(1000, 99999),          
            "customer_name": fake.name(),
            "product_category": random.choice(categories),
            "quantity": random.randint(1, 15),                   
            "order_amount": round(random.uniform(10.0, 2500.0), 2),
            "discount_percent": random.randint(0, 40),           
            "order_date": fake.date_time_this_year(),
            "status": random.choice(statuses)
        })

    return pd.DataFrame(data)

def upload_to_bigquery(df, dataset_id, table_id):
    # Initializes client using default credentials from the environment
    client = bigquery.Client()
    
    # Construct full references
    dataset_ref = f"{client.project}.{dataset_id}"
    table_ref = f"{dataset_ref}.{table_id}"

    # Create dataset if it does not exist
    try:
        client.get_dataset(dataset_ref)
    except NotFound:
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = "US" 
        client.create_dataset(dataset)
        print(f"Created dataset: {dataset_ref}")

    # Job config ensures table is overwritten on consecutive runs
    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_TRUNCATE",
    )

    print(f"Uploading {len(df)} rows to {table_ref}...")
    job = client.load_table_from_dataframe(
        df, table_ref, job_config=job_config
    )
    
    job.result() # Wait for job to complete
    
    table = client.get_table(table_ref)
    print(f"Successfully loaded {table.num_rows} rows into {table_ref}.")

if __name__ == "__main__":
    DATASET_ID = "analytics_dataset"
    TABLE_ID = "ecom_orders_large"

    print("Generating 10,000 mock orders...")
    df_orders = generate_ecommerce_data(10000)
    
    upload_to_bigquery(df_orders, DATASET_ID, TABLE_ID)