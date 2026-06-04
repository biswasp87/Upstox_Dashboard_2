import requests
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
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json().get('data', [])
        print(f"Items in chain: {len(data)}")
        if data:
            print("First item keys:", data[0].keys())
    else:
        print(f"Response: {response.text}")

if __name__ == "__main__":
    test_fetch_chain()
