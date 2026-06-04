from app import fetch_and_prepare_data
df = fetch_and_prepare_data()
if not df.empty:
    print(f"Total Rows: {len(df)}")
    print(f"Unique Symbols: {df['Symbol'].nunique()}")
    print(f"Sample Symbols: {df['Symbol'].unique()[:10]}")
    print("Columns:", df.columns.tolist())
    # Check if we have both CE and PE
    print("Option types:", df['option_type'].unique())
else:
    print("DataFrame is empty")
