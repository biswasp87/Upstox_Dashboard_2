from app import fetch_and_prepare_data
df = fetch_and_prepare_data()
ab_capital = df[df['Symbol'] == 'ABCAPITAL']
print(ab_capital['expiry'].unique())
