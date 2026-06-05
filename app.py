import os
from datetime import datetime, timedelta
import pandas as pd
import requests
import io
import gzip
from google.cloud import storage
import dash
from dash import dcc, html, Input, Output, State, dash_table
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Constants
DEFAULT_TOKEN = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiI0ODM0MzYiLCJqdGkiOiI2YTIwZDhmNDBlNDUzMDY4ZTI2OWM1YjciLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc4MDUzNzU4OCwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzgwNjEwNDAwfQ.w_-z7G-16o0XwcfSLawLDtpUz1GOjTO9LxEtwGdrruM"
NSE_NIFTY_500_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
UPSTOX_INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"

def get_access_token():
    """Fetch Upstox Access Token from GCS or use default."""
    try:
        bucket_name = os.environ.get('UPSTOX_TOKEN_BUCKET')
        if bucket_name:
            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob('access_token.txt')
            return blob.download_as_text().strip()
    except Exception as e:
        print(f"Error fetching token from GCS: {e}")

    return DEFAULT_TOKEN

# Global cache for instruments
_ALL_INSTRUMENTS = None

def get_all_instruments():
    """Download and cache all instruments from Upstox."""
    global _ALL_INSTRUMENTS
    if _ALL_INSTRUMENTS is None:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        try:
            print("Downloading all instruments...")
            response = requests.get(UPSTOX_INSTRUMENTS_URL, headers=headers)
            response.raise_for_status()
            with gzip.open(io.BytesIO(response.content), 'rt') as f:
                _ALL_INSTRUMENTS = pd.read_csv(f)
            print("Instruments downloaded successfully.")
        except Exception as e:
            print(f"Error fetching Upstox instruments: {e}")
            return pd.DataFrame()
    return _ALL_INSTRUMENTS

def fetch_and_prepare_data():
    """Fetch NIFTY 500 and Upstox instruments, then merge."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    try:
        response = requests.get(NSE_NIFTY_500_URL, headers=headers)
        response.raise_for_status()
        nifty500_df = pd.read_csv(io.StringIO(response.text))
    except Exception as e:
        print(f"Error fetching NIFTY 500: {e}")
        return pd.DataFrame()

    upstox_df = get_all_instruments()
    if upstox_df.empty:
        return pd.DataFrame()

    instruments_filtered = upstox_df[upstox_df['instrument_type'] == 'OPTSTK'].copy()

    def clean_name(s):
        if not isinstance(s, str): return ""
        import re
        s = s.upper()
        s = re.sub(r'[^A-Z0-9\s]', '', s)
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    instruments_filtered['name_clean'] = instruments_filtered['name'].apply(clean_name)
    nifty500_df['company_name_clean'] = nifty500_df['Company Name'].apply(clean_name)

    merged_df = instruments_filtered.merge(
        nifty500_df[['company_name_clean', 'Symbol']],
        left_on='name_clean',
        right_on='company_name_clean',
        how='inner'
    )

    merged_df = merged_df.drop(columns=['name_clean', 'company_name_clean'])
    return merged_df

def get_underlying_instrument_info(symbol):
    """Find the NSE_EQ instrument info for a symbol."""
    try:
        upstox_df = get_all_instruments()
        if upstox_df.empty:
            return None

        match = upstox_df[
            (upstox_df['instrument_type'] == 'EQUITY') &
            (upstox_df['tradingsymbol'] == symbol) &
            (upstox_df['exchange'] == 'NSE_EQ')
        ]
        if not match.empty:
            info = match.iloc[0].to_dict()
            key = info['instrument_key']
            info['isin'] = key.split('|')[1] if '|' in key else None
            return info
    except Exception as e:
        print(f"Error finding underlying info: {e}")
    return None

def fetch_company_profile(isin):
    """Fetch Company Profile from Upstox API."""
    url = f"https://api.upstox.com/v2/fundamentals/{isin}/profile"
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {get_access_token()}'}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get('data', {})
    except Exception as e:
        print(f"Error fetching profile: {e}")
    return {}

def fetch_shareholdings(isin):
    """Fetch Shareholding data from Upstox API."""
    url = f"https://api.upstox.com/v2/fundamentals/{isin}/shareholding"
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {get_access_token()}'}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get('data', [])
    except Exception as e:
        print(f"Error fetching shareholdings: {e}")
    return []

def fetch_corporate_actions(isin):
    """Fetch Corporate actions from Upstox API."""
    url = f"https://api.upstox.com/v2/fundamentals/{isin}/corporate-actions"
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {get_access_token()}'}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get('data', [])
    except Exception as e:
        print(f"Error fetching corporate actions: {e}")
    return []

def fetch_historical_v3(instrument_key, interval='day', from_date=None, to_date=None):
    """Fetch Historical Candle Data V3."""
    if to_date is None:
        to_date = datetime.now().strftime('%Y-%m-%d')
    if from_date is None:
        from_date = (datetime.now() - timedelta(days=100)).strftime('%Y-%m-%d')

    url = f"https://api.upstox.com/v3/historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}"
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {get_access_token()}'
    }
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json().get('data', {}).get('candles', [])
            cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi']
            df = pd.DataFrame(data, columns=cols)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('timestamp', ascending=True)
            return df
    except Exception as e:
        print(f"Exception fetching historical V3: {e}")
    return pd.DataFrame()

def fetch_option_chain(underlying_key, expiry):
    """Fetch Option Chain from Upstox API."""
    url = f"https://api.upstox.com/v2/option/chain?instrument_key={underlying_key}&expiry_date={expiry}"
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {get_access_token()}'
    }
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get('data', [])
    except Exception as e:
        print(f"Exception fetching option chain: {e}")
    return []

def fetch_market_quotes(instrument_keys):
    """Fetch Full Market Quote for multiple instruments."""
    if not instrument_keys:
        return {}
    # Upstox V2 quotes uses comma separated instrument keys
    keys_str = ",".join(instrument_keys)
    url = f"https://api.upstox.com/v2/market-quote/quotes?symbol={keys_str}"
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {get_access_token()}'
    }
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get('data', {})
        else:
            print(f"Error fetching market quotes: {response.status_code} {response.text}")
    except Exception as e:
        print(f"Exception fetching market quotes: {e}")
    return {}

# Initialize Data
INSTRUMENTS_DF = fetch_and_prepare_data()
UNIQUE_SYMBOLS = sorted(INSTRUMENTS_DF['Symbol'].unique()) if not INSTRUMENTS_DF.empty else []

# Dash App
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

app.layout = dbc.Container([
    dbc.Row([
        dbc.Col(html.H1("Upstox Options Dashboard", className="text-center mb-4"), width=12)
    ]),

    dbc.Row([
        dbc.Col([
            dbc.Label("Symbol"),
            dbc.InputGroup([
                dbc.Button("Prev", id="prev-btn", n_clicks=0),
                dcc.Dropdown(
                    id='symbol-dropdown',
                    options=[{'label': s, 'value': s} for s in UNIQUE_SYMBOLS],
                    value=UNIQUE_SYMBOLS[0] if UNIQUE_SYMBOLS else None,
                    style={'width': '150px'}
                ),
                dbc.Button("Next", id="next-btn", n_clicks=0),
            ])
        ], width=3),
        dbc.Col([
            dbc.Label("Expiry"),
            dcc.Dropdown(id='expiry-dropdown')
        ], width=2),
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H6("Max Pain", className="card-title"),
                    html.Div(id="max-pain-display", style={'fontSize': '18px', 'fontWeight': 'bold'}),
                    html.Div(id="underlying-price-display", style={'fontSize': '12px'})
                ], style={'padding': '10px'})
            ])
        ], width=1),
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H6("Profile & Sector", className="card-title"),
                    html.Div(id="profile-display", style={'fontSize': '12px'})
                ], style={'padding': '10px'})
            ])
        ], width=2),
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H6("Shareholding", className="card-title"),
                    html.Div(id="shareholding-display", style={'fontSize': '12px'})
                ], style={'padding': '10px'})
            ])
        ], width=2),
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H6("Corp Actions", className="card-title"),
                    html.Div(id="corp-action-display", style={'fontSize': '12px'})
                ], style={'padding': '10px'})
            ])
        ], width=2)
    ], className="mb-4 align-items-end"),

    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("CE Strike Price"),
                dbc.CardBody(dcc.RadioItems(id='ce-strike-radio', inline=True, labelStyle={'margin-right': '10px'}))
            ])
        ], width=6),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("PE Strike Price"),
                dbc.CardBody(dcc.RadioItems(id='pe-strike-radio', inline=True, labelStyle={'margin-right': '10px'}))
            ])
        ], width=6)
    ], className="mb-4"),

    dbc.Row([
        dbc.Col(dbc.Card([dbc.CardHeader("CE Chart"), dbc.CardBody(dcc.Graph(id='ce-candle-graph'))]), width=4),
        dbc.Col(dbc.Card([dbc.CardHeader("PE Chart"), dbc.CardBody(dcc.Graph(id='pe-candle-graph'))]), width=4),
        dbc.Col(dbc.Card([
            dbc.CardHeader([
                "Streaming Buy/Sell Qty",
                dbc.Button("Start Stream", id="start-stream-btn", size="sm", className="ms-2", color="success"),
                dbc.Button("Stop Stream", id="stop-stream-btn", size="sm", className="ms-2", color="danger"),
            ], className="d-flex align-items-center"),
            dbc.CardBody([
                html.Div(id='streaming-table-container'),
                dcc.Interval(id='stream-interval', interval=3000, n_intervals=0, disabled=True)
            ])
        ]), width=4)
    ], className="mb-4"),

    dbc.Row([
        dbc.Col(dcc.Graph(id='iv-graph'), width=6),
        dbc.Col(dcc.Graph(id='pcr-graph'), width=6)
    ], className="mb-4"),

    dbc.Row([
        dbc.Col(dcc.Graph(id='oi-graph'), width=4),
        dbc.Col(dcc.Graph(id='oi-change-graph'), width=4),
        dbc.Col(dcc.Graph(id='volume-graph'), width=4)
    ], className="mb-4"),

    dbc.Row([
        dbc.Col([
            html.H3("Option Chain Table"),
            html.Div(id='option-chain-table-container')
        ], width=12)
    ]),
    dcc.Store(id='option-chain-store'),
    dcc.Store(id='underlying-info-store')
], fluid=True)

# Callbacks
@app.callback(
    Output('symbol-dropdown', 'value'),
    [Input('prev-btn', 'n_clicks'), Input('next-btn', 'n_clicks')],
    [State('symbol-dropdown', 'value')]
)
def navigate_symbols(prev_clicks, next_clicks, current_symbol):
    ctx = dash.callback_context
    if not ctx.triggered: return current_symbol
    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    if current_symbol not in UNIQUE_SYMBOLS: return UNIQUE_SYMBOLS[0] if UNIQUE_SYMBOLS else None
    idx = UNIQUE_SYMBOLS.index(current_symbol)
    if button_id == 'next-btn': return UNIQUE_SYMBOLS[(idx + 1) % len(UNIQUE_SYMBOLS)]
    elif button_id == 'prev-btn': return UNIQUE_SYMBOLS[(idx - 1) % len(UNIQUE_SYMBOLS)]
    return current_symbol

@app.callback(
    [Output('expiry-dropdown', 'options'), Output('expiry-dropdown', 'value'), Output('underlying-info-store', 'data')],
    [Input('symbol-dropdown', 'value')]
)
def update_symbol_expiries(symbol):
    if not symbol: return [], None, None
    underlying_info = get_underlying_instrument_info(symbol)
    if not underlying_info: return [], None, None
    expiries = sorted(INSTRUMENTS_DF[INSTRUMENTS_DF['Symbol'] == symbol]['expiry'].dropna().unique())
    options = [{'label': e, 'value': e} for e in expiries]
    default_expiry = expiries[0] if expiries else None
    underlying_info['symbol'] = symbol
    return options, default_expiry, underlying_info

@app.callback(
    [Output('profile-display', 'children'), Output('shareholding-display', 'children'), Output('corp-action-display', 'children')],
    [Input('underlying-info-store', 'data')]
)
def update_fundamentals(info):
    if not info or not info.get('isin'): return "N/A", "N/A", "N/A"
    isin = info['isin']
    profile = fetch_company_profile(isin)
    shares = fetch_shareholdings(isin)
    actions = fetch_corporate_actions(isin)
    profile_html = html.Div([html.P(f"Sector: {profile.get('sector', 'N/A')}", style={'fontWeight': 'bold'}), html.P(profile.get('company_profile', 'N/A')[:100] + "...", style={'fontSize': '10px'})])
    if shares:
        latest = shares[0]
        shares_html = html.Div([html.P(f"Q: {latest.get('quarter', 'N/A')}", style={'fontWeight': 'bold'}), html.Ul([html.Li(f"Promoter: {latest.get('promoter', 0)}%"), html.Li(f"FII: {latest.get('fii', 0)}%"), html.Li(f"DII: {latest.get('dii', 0)}%"), html.Li(f"Public: {latest.get('public', 0)}%")], style={'fontSize': '10px', 'paddingLeft': '15px'})])
    else: shares_html = "No data"
    if actions:
        latest_act = actions[0]
        actions_html = html.Div([html.P(f"{latest_act.get('type', 'N/A')}", style={'fontWeight': 'bold'}), html.P(f"Date: {latest_act.get('ex_date', 'N/A')}", style={'fontSize': '10px'}), html.P(f"{latest_act.get('description', 'N/A')}", style={'fontSize': '10px'})])
    else: actions_html = "No data"
    return profile_html, shares_html, actions_html

@app.callback(
    [Output('ce-strike-radio', 'options'), Output('ce-strike-radio', 'value'), Output('pe-strike-radio', 'options'), Output('pe-strike-radio', 'value'), Output('option-chain-store', 'data'), Output('underlying-info-store', 'data', allow_duplicate=True)],
    [Input('expiry-dropdown', 'value')],
    [State('underlying-info-store', 'data')],
    prevent_initial_call=True
)
def update_option_chain_data(expiry, underlying_info):
    if not expiry or not underlying_info: return [], None, [], None, None, underlying_info
    underlying_key = underlying_info['instrument_key']
    chain_data = fetch_option_chain(underlying_key, expiry)
    strikes = sorted(list(set([d['strike_price'] for d in chain_data])))
    ce_options = [{'label': str(s), 'value': s} for s in strikes]
    pe_options = [{'label': str(s), 'value': s} for s in strikes]
    underlying_price = chain_data[0].get('underlying_spot_price', 0) if chain_data else 0
    atm_strike = min(strikes, key=lambda x: abs(x - underlying_price)) if strikes else None
    updated_info = underlying_info.copy()
    updated_info.update({'price': underlying_price, 'expiry': expiry})
    return ce_options, atm_strike, pe_options, atm_strike, chain_data, updated_info

@app.callback(
    Output('ce-candle-graph', 'figure'),
    [Input('ce-strike-radio', 'value')],
    [State('underlying-info-store', 'data')]
)
def update_ce_graph(strike, underlying_info):
    if not strike or not underlying_info: return go.Figure()
    symbol = underlying_info['symbol']
    expiry = underlying_info['expiry']
    match = INSTRUMENTS_DF[(INSTRUMENTS_DF['Symbol'] == symbol) & (INSTRUMENTS_DF['strike'] == strike) & (INSTRUMENTS_DF['option_type'] == 'CE') & (INSTRUMENTS_DF['expiry'] == expiry)]
    if match.empty: return go.Figure()

    instrument_key = match.iloc[0]['instrument_key']
    df = fetch_historical_v3(instrument_key)

    # Append current day data from Full Market Quotes
    quotes = fetch_market_quotes([instrument_key])
    if instrument_key in quotes:
        q = quotes[instrument_key]
        ohlc = q.get('ohlc', {})
        new_row = {
            'timestamp': datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
            'open': ohlc.get('open'),
            'high': ohlc.get('high'),
            'low': ohlc.get('low'),
            'close': q.get('last_price'),
            'volume': q.get('volume'),
            'oi': q.get('oi')
        }
        # Check if today's candle is already in df
        today_ts = pd.to_datetime(new_row['timestamp'])
        if not df.empty:
            if df.iloc[-1]['timestamp'].date() == today_ts.date():
                # Update last row with latest data
                for k, v in new_row.items():
                    df.iloc[-1, df.columns.get_loc(k)] = v
            else:
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        else:
            df = pd.DataFrame([new_row])

    if df.empty: return go.Figure()

    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0, row_heights=[0.5, 0.25, 0.25])
    fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close']), row=1, col=1)
    fig.add_trace(go.Bar(x=df['timestamp'], y=df['volume']), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['oi']), row=3, col=1)
    fig.update_layout(title=f"CE - {symbol} {strike} {expiry}", plot_bgcolor='white', paper_bgcolor='white', xaxis_rangeslider_visible=False, showlegend=False)
    fig.update_xaxes(showline=True, linewidth=1, linecolor='black', mirror=True)
    fig.update_yaxes(showline=True, linewidth=1, linecolor='black', mirror=True)
    return fig

@app.callback(
    Output('pe-candle-graph', 'figure'),
    [Input('pe-strike-radio', 'value')],
    [State('underlying-info-store', 'data')]
)
def update_pe_graph(strike, underlying_info):
    if not strike or not underlying_info: return go.Figure()
    symbol = underlying_info['symbol']
    expiry = underlying_info['expiry']
    match = INSTRUMENTS_DF[(INSTRUMENTS_DF['Symbol'] == symbol) & (INSTRUMENTS_DF['strike'] == strike) & (INSTRUMENTS_DF['option_type'] == 'PE') & (INSTRUMENTS_DF['expiry'] == expiry)]
    if match.empty: return go.Figure()

    instrument_key = match.iloc[0]['instrument_key']
    df = fetch_historical_v3(instrument_key)

    # Append current day data from Full Market Quotes
    quotes = fetch_market_quotes([instrument_key])
    if instrument_key in quotes:
        q = quotes[instrument_key]
        ohlc = q.get('ohlc', {})
        new_row = {
            'timestamp': datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
            'open': ohlc.get('open'),
            'high': ohlc.get('high'),
            'low': ohlc.get('low'),
            'close': q.get('last_price'),
            'volume': q.get('volume'),
            'oi': q.get('oi')
        }
        today_ts = pd.to_datetime(new_row['timestamp'])
        if not df.empty:
            if df.iloc[-1]['timestamp'].date() == today_ts.date():
                for k, v in new_row.items():
                    df.iloc[-1, df.columns.get_loc(k)] = v
            else:
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        else:
            df = pd.DataFrame([new_row])

    if df.empty: return go.Figure()

    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0, row_heights=[0.5, 0.25, 0.25])
    fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close']), row=1, col=1)
    fig.add_trace(go.Bar(x=df['timestamp'], y=df['volume']), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['oi']), row=3, col=1)
    fig.update_layout(title=f"PE - {symbol} {strike} {expiry}", plot_bgcolor='white', paper_bgcolor='white', xaxis_rangeslider_visible=False, showlegend=False)
    fig.update_xaxes(showline=True, linewidth=1, linecolor='black', mirror=True)
    fig.update_yaxes(showline=True, linewidth=1, linecolor='black', mirror=True)
    return fig

@app.callback(
    Output('iv-graph', 'figure'),
    [Input('option-chain-store', 'data')],
    [State('underlying-info-store', 'data')]
)
def update_iv_graph(chain_data, underlying_info):
    if not chain_data or not underlying_info: return go.Figure()
    price = underlying_info.get('price', 0)
    iv_data = []
    for item in chain_data:
        strike = item['strike_price']
        # Relax OTM filter to see more data
        if price > 0 and (strike < price * 0.5 or strike > price * 1.5): continue

        call_greeks = item.get('call_options', {}).get('option_greeks')
        put_greeks = item.get('put_options', {}).get('option_greeks')

        call_iv = call_greeks.get('iv') if call_greeks else 0
        put_iv = put_greeks.get('iv') if put_greeks else 0

        # Only add if at least one IV is non-zero
        if (call_iv and call_iv > 0) or (put_iv and put_iv > 0):
            iv_data.append({
                'strike': strike,
                'call_iv': call_iv if (call_iv and call_iv > 0) else None,
                'put_iv': put_iv if (put_iv and put_iv > 0) else None
            })

    if not iv_data: return go.Figure(layout={'title': 'No IV data available'})

    df = pd.DataFrame(iv_data).sort_values('strike')
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['strike'], y=df['call_iv'], mode='lines+markers', name='Call IV', line=dict(color='red'), connectgaps=True))
    fig.add_trace(go.Scatter(x=df['strike'], y=df['put_iv'], mode='lines+markers', name='Put IV', line=dict(color='green'), connectgaps=True))
    fig.update_layout(title="IV of Put and Call", plot_bgcolor='white', paper_bgcolor='white')
    fig.update_xaxes(showline=True, linewidth=1, linecolor='black', gridcolor='lightgrey')
    fig.update_yaxes(showline=True, linewidth=1, linecolor='black', gridcolor='lightgrey')
    return fig

@app.callback(
    [Output('pcr-graph', 'figure'), Output('oi-graph', 'figure'), Output('oi-change-graph', 'figure'), Output('volume-graph', 'figure')],
    [Input('option-chain-store', 'data')],
    [State('underlying-info-store', 'data')]
)
def update_metric_graphs(chain_data, underlying_info):
    if not chain_data or not underlying_info: return [go.Figure()]*4
    price = underlying_info['price']
    metrics = []
    for item in chain_data:
        strike = item['strike_price']
        ce_md = item.get('call_options', {}).get('market_data', {})
        pe_md = item.get('put_options', {}).get('market_data', {})
        ce_oi, pe_oi = ce_md.get('oi', 0), pe_md.get('oi', 0)
        metrics.append({'strike': strike, 'pcr': pe_oi / ce_oi if ce_oi > 0 else 0, 'ce_oi': ce_oi, 'pe_oi': pe_oi, 'ce_oi_change': ce_oi - ce_md.get('prev_oi', 0), 'pe_oi_change': pe_oi - pe_md.get('prev_oi', 0), 'total_vol': ce_md.get('volume', 0) + pe_md.get('volume', 0)})
    df = pd.DataFrame(metrics).sort_values('strike')
    fig_pcr = go.Figure(go.Scatter(x=df['strike'], y=df['pcr'], mode='lines+markers'))
    fig_oi = go.Figure([go.Bar(x=df['strike'], y=df['ce_oi'], name='CE OI', marker_color='red'), go.Bar(x=df['strike'], y=df['pe_oi'], name='PE OI', marker_color='green')])
    fig_oi_chg = go.Figure([go.Bar(x=df['strike'], y=df['ce_oi_change'], name='CE OI Chg', marker_color='red'), go.Bar(x=df['strike'], y=df['pe_oi_change'], name='PE OI Chg', marker_color='green')])
    fig_vol = go.Figure(go.Bar(x=df['strike'], y=df['total_vol'], marker_color='blue'))
    for f, t in zip([fig_pcr, fig_oi, fig_oi_chg, fig_vol], ["PCR", "OI", "OI Change", "Volume"]):
        f.add_vline(x=price, line_dash="dash", line_color="black")
        f.update_layout(title=t, plot_bgcolor='white', paper_bgcolor='white', barmode='group' if t in ["OI", "OI Change"] else None)
        f.update_xaxes(showline=True, linewidth=1, linecolor='black', gridcolor='lightgrey')
        f.update_yaxes(showline=True, linewidth=1, linecolor='black', gridcolor='lightgrey')
    return fig_pcr, fig_oi, fig_oi_chg, fig_vol

@app.callback(
    [Output('max-pain-display', 'children'), Output('underlying-price-display', 'children')],
    [Input('option-chain-store', 'data')],
    [State('underlying-info-store', 'data')]
)
def update_max_pain(chain_data, underlying_info):
    if not chain_data or not underlying_info: return "N/A", "Underlying: N/A"
    strikes = sorted([d['strike_price'] for d in chain_data])
    min_pain, max_pain_strike = float('inf'), strikes[0]
    for s in strikes:
        tp = sum(item.get('call_options', {}).get('market_data', {}).get('oi', 0) * (s - item['strike_price']) for item in chain_data if item['strike_price'] < s) + \
             sum(item.get('put_options', {}).get('market_data', {}).get('oi', 0) * (item['strike_price'] - s) for item in chain_data if item['strike_price'] > s)
        if tp < min_pain: min_pain, max_pain_strike = tp, s
    price = underlying_info['price']
    diff = price - max_pain_strike
    arrow = "▲" if diff >= 0 else "▼"
    return html.Span(f"{max_pain_strike}"), html.Div([html.Span(f"Underlying: {price:.2f} "), html.Span(f"({arrow} {abs(diff):.2f})", style={'color': "green" if diff >= 0 else "red"})])

@app.callback(
    Output('option-chain-table-container', 'children'),
    [Input('option-chain-store', 'data')],
    [State('underlying-info-store', 'data')]
)
def update_table(chain_data, underlying_info):
    if not chain_data: return "No data"
    price = underlying_info.get('price', 0) if underlying_info else 0
    rows = []
    for item in chain_data:
        ce_md, ce_g, pe_md, pe_g = item.get('call_options', {}).get('market_data', {}), item.get('call_options', {}).get('option_greeks', {}), item.get('put_options', {}).get('market_data', {}), item.get('put_options', {}).get('option_greeks', {})
        def oi_chg(md): return round(((md.get('oi', 0) - md.get('prev_oi', 0)) / md.get('prev_oi', 1)) * 100, 2) if md.get('prev_oi', 0) else 0
        rows.append({'CE_OI': ce_md.get('oi'), 'CE_OI_Chg%': oi_chg(ce_md), 'CE_Delta': ce_g.get('delta'), 'CE_POP': ce_g.get('pop'), 'CE_LTP': ce_md.get('ltp'), 'Strike': item['strike_price'], 'PE_LTP': pe_md.get('ltp'), 'PE_POP': pe_g.get('pop'), 'PE_Delta': pe_g.get('delta'), 'PE_OI_Chg%': oi_chg(pe_md), 'PE_OI': pe_md.get('oi')})
    df = pd.DataFrame(rows).sort_values('Strike', ascending=False)
    max_ce_oi, max_pe_oi = df['CE_OI'].max(), df['PE_OI'].max()
    atm_style = []
    if price > 0:
        for i in range(len(df) - 1):
            if df.iloc[i]['Strike'] >= price and df.iloc[i+1]['Strike'] < price:
                atm_style = [{'if': {'row_index': i}, 'borderBottom': '5px solid black'}, {'if': {'row_index': i + 1}, 'borderTop': '5px solid black'}]
                break
    return dash_table.DataTable(data=df.to_dict('records'), columns=[{'name': i, 'id': i} for i in df.columns], style_cell={'textAlign': 'center', 'border': '1px solid grey'}, style_header={'fontWeight': 'bold', 'backgroundColor': 'lightgrey'}, style_data_conditional=[{'if': {'filter_query': f'{{CE_OI}} = {max_ce_oi}', 'column_id': ['CE_OI', 'CE_OI_Chg%', 'CE_Delta', 'CE_POP', 'CE_LTP']}, 'backgroundColor': '#FFCCCB'}, {'if': {'filter_query': f'{{PE_OI}} = {max_pe_oi}', 'column_id': ['PE_OI', 'PE_OI_Chg%', 'PE_Delta', 'PE_POP', 'PE_LTP']}, 'backgroundColor': '#90EE90'}, {'if': {'filter_query': '{CE_OI_Chg%} > 0', 'column_id': 'CE_OI_Chg%'}, 'color': 'green'}, {'if': {'filter_query': '{CE_OI_Chg%} < 0', 'column_id': 'CE_OI_Chg%'}, 'color': 'red'}, {'if': {'filter_query': '{PE_OI_Chg%} > 0', 'column_id': 'PE_OI_Chg%'}, 'color': 'green'}, {'if': {'filter_query': '{PE_OI_Chg%} < 0', 'column_id': 'PE_OI_Chg%'}, 'color': 'red'}] + atm_style, page_size=100)

@app.callback(
    Output('stream-interval', 'disabled'),
    [Input('start-stream-btn', 'n_clicks'),
     Input('stop-stream-btn', 'n_clicks')],
    [State('stream-interval', 'disabled')],
    prevent_initial_call=True
)
def toggle_streaming(start_clicks, stop_clicks, currently_disabled):
    ctx = dash.callback_context
    if not ctx.triggered:
        return currently_disabled

    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    if button_id == 'start-stream-btn':
        return False
    else:
        return True

@app.callback(
    Output('streaming-table-container', 'children'),
    [Input('stream-interval', 'n_intervals')],
    [State('option-chain-store', 'data'),
     State('underlying-info-store', 'data')]
)
def update_streaming_data(n, chain_data, underlying_info):
    if not chain_data or not underlying_info:
        return "Waiting for data..."

    # Map instrument keys
    keys_to_fetch = [underlying_info['instrument_key']]
    strike_map = {} # key -> (strike, type)

    strikes = sorted(list(set([d['strike_price'] for d in chain_data])))

    for item in chain_data:
        ckey = item.get('call_options', {}).get('instrument_key')
        pkey = item.get('put_options', {}).get('instrument_key')
        if ckey:
            keys_to_fetch.append(ckey)
            strike_map[ckey] = (item['strike_price'], 'CE')
        if pkey:
            keys_to_fetch.append(pkey)
            strike_map[pkey] = (item['strike_price'], 'PE')

    quotes = fetch_market_quotes(keys_to_fetch)

    # Build table rows
    stream_rows = []

    # Add Equity row
    eq_key = underlying_info['instrument_key']
    if eq_key in quotes:
        q = quotes[eq_key]
        stream_rows.append({
            'Call Buy Qty': q.get('total_buy_quantity'),
            'Call Sell Qty': q.get('total_sell_quantity'),
            'Strike': f"EQ: {underlying_info['symbol']}",
            'Put Buy Qty': '-',
            'Put Sell Qty': '-'
        })

    for s in strikes:
        row = {'Strike': s}
        # Find keys for this strike
        ckey = next((k for k, v in strike_map.items() if v[0] == s and v[1] == 'CE'), None)
        pkey = next((k for k, v in strike_map.items() if v[0] == s and v[1] == 'PE'), None)

        if ckey and ckey in quotes:
            q = quotes[ckey]
            row['Call Buy Qty'] = q.get('total_buy_quantity')
            row['Call Sell Qty'] = q.get('total_sell_quantity')
        else:
            row['Call Buy Qty'] = 0
            row['Call Sell Qty'] = 0

        if pkey and pkey in quotes:
            q = quotes[pkey]
            row['Put Buy Qty'] = q.get('total_buy_quantity')
            row['Put Sell Qty'] = q.get('total_sell_quantity')
        else:
            row['Put Buy Qty'] = 0
            row['Put Sell Qty'] = 0

        stream_rows.append(row)

    # Sort options high to low, keep equity at top
    options_rows = [r for r in stream_rows if not str(r['Strike']).startswith('EQ:')]
    eq_rows = [r for r in stream_rows if str(r['Strike']).startswith('EQ:')]

    df_options = pd.DataFrame(options_rows).sort_values('Strike', ascending=False)
    df_eq = pd.DataFrame(eq_rows)

    df_stream = pd.concat([df_eq, df_options], ignore_index=True)

    return dash_table.DataTable(
        data=df_stream.to_dict('records'),
        columns=[
            {'name': 'Call Buy Qty', 'id': 'Call Buy Qty'},
            {'name': 'Call Sell Qty', 'id': 'Call Sell Qty'},
            {'name': 'Strike', 'id': 'Strike'},
            {'name': 'Put Buy Qty', 'id': 'Put Buy Qty'},
            {'name': 'Put Sell Qty', 'id': 'Put Sell Qty'}
        ],
        style_cell={'textAlign': 'center', 'fontSize': '11px', 'padding': '2px'},
        style_header={'fontWeight': 'bold', 'backgroundColor': '#f8f9fa'},
        style_data_conditional=[
            {'if': {'column_id': 'Strike'}, 'fontWeight': 'bold', 'backgroundColor': '#eee'}
        ]
    )

if __name__ == "__main__":
    app.run(debug=True)
