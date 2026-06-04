import requests
token = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiI0ODM0MzYiLCJqdGkiOiI2YTIwZDhmNDBlNDUzMDY4ZTI2OWM1YjciLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc4MDUzNzU4OCwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzgwNjEwNDAwfQ.w_-z7G-16o0XwcfSLawLDtpUz1GOjTO9LxEtwGdrruM"
headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
url = "https://api.upstox.com/v2/user/profile"
response = requests.get(url, headers=headers)
print(response.status_code)
print(response.text)
