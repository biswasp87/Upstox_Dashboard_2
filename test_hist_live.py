import requests
from app import get_access_token
from datetime import datetime, timedelta

def test_hist():
    instrument_key = "NSE_FO|50974"
    to_date = datetime.now().strftime('%Y-%m-%d')
    from_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    # Try 'day' or 'days'
    url = f"https://api.upstox.com/v3/historical-candle/{instrument_key}/day/1/{to_date}/{from_date}"
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {get_access_token()}'
    }
    response = requests.get(url, headers=headers)
    print(f"Status day: {response.status_code}")

    url_days = f"https://api.upstox.com/v3/historical-candle/{instrument_key}/days/1/{to_date}/{from_date}"
    response = requests.get(url_days, headers=headers)
    print(f"Status days: {response.status_code}")

if __name__ == "__main__":
    test_hist()
