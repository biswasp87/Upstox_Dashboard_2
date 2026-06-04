import requests
import pandas as pd

def test_nse_fetch():
    url = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        print("Successfully fetched NSE list")
        df = pd.read_csv(url)
        print(df.head())
    else:
        print(f"Failed to fetch NSE list: {response.status_code}")

if __name__ == "__main__":
    test_nse_fetch()
