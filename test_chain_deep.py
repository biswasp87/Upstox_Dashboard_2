import requests
import json
from app import get_access_token

def test_fetch_chain():
    underlying_key = "NSE_EQ|INE002A01018" # RELIANCE
    expiry = "2026-06-30"
    url = f"https://api.upstox.com/v2/option/chain?instrument_key={underlying_key}&expiry_date={expiry}"
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {get_access_token()}'
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json().get('data', [])
        if data:
            print("Item keys:", data[0].keys())
            print("underlying_key value:", data[0].get('underlying_key'))
            print("underlying_spot_price value:", data[0].get('underlying_spot_price'))
            call_options = data[0].get('call_options')
            if call_options:
                print("call_options keys:", call_options.keys())
                market_data = call_options.get('market_data')
                if market_data:
                    print("market_data keys:", market_data.keys())
    else:
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")

if __name__ == "__main__":
    test_fetch_chain()
