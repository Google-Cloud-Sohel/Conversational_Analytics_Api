import pandas as pd
from faker import Faker
import random
from google.cloud import bigquery
from google.cloud.exceptions import NotFound

# Configuration
PROJECT_ID = "keen-berm-506210-a8"
DATASET_ID = f"{PROJECT_ID}.analytics_dataset"
TABLE_ID = f"{DATASET_ID}.ecom_orders_large"

fake = Faker()
client = bigquery.Client(project=PROJECT_ID)

def generate_large_ecom_data(num_records=10000) -> pd.DataFrame:
    print(f"Generating {num_records} dummy e-commerce orders (this may take 10-20 seconds)...")
    data = []
    
    categories = ["Electronics", "Apparel", "Home & Kitchen", "Sports", "Beauty", "Toys", "Books"]
    statuses = ["Delivered", "Shipped", "Processing", "Cancelled", "Refunded", "Returned"]
    payment_methods = ["Credit Card", "PayPal", "Apple Pay", "Google Pay", "Gift Card"]
    countries = ["United States", "Canada", "United Kingdom", "Australia", "India", "Germany"]
    
    for _ in range(num_records):
        category = random.choice(categories)
        product_name = f"{fake.word().capitalize()} {category.split()[0]}"
        quantity = random.randint(1, 5)
        unit_price = round(random.uniform(10.0, 500.0), 2)
        
        # 30% chance a discount is applied
        discount = round(random.uniform(5.0, 50.0), 2) if random.random() > 0.7 else 0.0
        total_amount = round((quantity * unit_price) - discount, 2)
        
        data.append({
            "order_id": fake.uuid4(),
            "customer_id": fake.random_int(min=1000, max=9999),
            "customer_name": fake.name(),
            "customer_email": fake.email(),
            "customer_city": fake.city(),
            "customer_country": random.choice(countries),
            "is_premium_member": random.choice([True, False]),
            "product_category": category,
            "product_name": product_name,
            "quantity": quantity,
            "unit_price": unit_price,
            "discount_applied": discount,
            "total_amount": total_amount if total_amount > 0 else 0.0, # Ensure no negative totals
            "order_status": random.choice(statuses),
            "payment_method": random.choice(payment_methods),
            "order_date": fake.date_time_between(start_date='-2y', end_date='now').isoformat()
        })
        
    return pd.DataFrame(data)

def setup_bigquery_and_upload(df: pd.DataFrame):
    # 1. Create dataset if it doesn't exist
    dataset = bigquery.Dataset(DATASET_ID)
    dataset.location = "US"
    
    try:
        client.get_dataset(DATASET_ID)
        print(f"Dataset {DATASET_ID} already exists.")
    except NotFound:
        dataset = client.create_dataset(dataset, timeout=30)
        print(f"Created dataset {dataset.dataset_id}")

    # 2. Upload the DataFrame to the table
    print(f"Uploading {len(df)} rows to {TABLE_ID}...")
    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_TRUNCATE", 
    )
    
    job = client.load_table_from_dataframe(df, TABLE_ID, job_config=job_config)
    job.result() 
    print(f"Upload successful! Table contains {job.output_rows} rows.")

if __name__ == "__main__":
    df = generate_large_ecom_data(10000)
    setup_bigquery_and_upload(df)