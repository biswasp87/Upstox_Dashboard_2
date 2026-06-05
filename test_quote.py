import requests

TOKEN = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiI0ODM0MzYiLCJqdGkiOiI2YTIwZDhmNDBlNDUzMDY4ZTI2OWM1YjciLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc4MDUzNzU4OCwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzgwNjEwNDAwfQ.w_-z7G-16o0XwcfSLawLDtpUz1GOjTO9LxEtwGdrruM"
INSTRUMENT = "NSE_EQ|INE002A01018" # Reliance

url = f"https://api.upstox.com/v2/market-quote/quotes?instrument_key={INSTRUMENT}"
headers = {
    'Accept': 'application/json',
    'Authorization': f'Bearer {TOKEN}'
}

print(f"Testing {url}...")
r = requests.get(url, headers=headers)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    print(f"Success! Response: {r.text[:1000]}...")
else:
    print(f"Failed: {r.text}")
