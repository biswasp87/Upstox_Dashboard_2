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
        # This is a placeholder as bucket name is not provided
        # In a real scenario, we would use os.environ.get('GCS_BUCKET_NAME')
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

    # 1. Fetch NIFTY 500
    try:
        response = requests.get(NSE_NIFTY_500_URL, headers=headers)
        response.raise_for_status()
        nifty500_df = pd.read_csv(io.StringIO(response.text))
    except Exception as e:
        print(f"Error fetching NIFTY 500: {e}")
        return pd.DataFrame()

    # 2. Get Upstox Instruments
    upstox_df = get_all_instruments()
    if upstox_df.empty:
        return pd.DataFrame()

    # 3. Filter OPTSTK and FUTSTK
    instruments_filtered = upstox_df[upstox_df['instrument_type'].isin(['OPTSTK', 'FUTSTK'])].copy()

    # 4. Merge
    # Normalize names for matching: remove non-alphanumeric and extra spaces
    def clean_name(s):
        if not isinstance(s, str): return ""
        import re
        s = s.upper()
        s = re.sub(r'[^A-Z0-9\s]', '', s) # Remove punctuation
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    instruments_filtered['name_clean'] = instruments_filtered['name'].apply(clean_name)
    nifty500_df['company_name_clean'] = nifty500_df['Company Name'].apply(clean_name)

    # Merge Symbol from NIFTY 500 into filtered instruments
    merged_df = instruments_filtered.merge(
        nifty500_df[['company_name_clean', 'Symbol']],
        left_on='name_clean',
        right_on='company_name_clean',
        how='inner'
    )

    # Remove helper columns
    merged_df = merged_df.drop(columns=['name_clean', 'company_name_clean'])

    return merged_df

# Helper functions
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
            # Extract ISIN from instrument_key (Format: EXCHANGE|ISIN)
            key = info['instrument_key']
            info['isin'] = key.split('|')[1] if '|' in key else None
            return info
    except Exception as e:
        print(f"Error finding underlying info: {e}")
    return None

# API functions
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

def fetch_historical_v3(instrument_key, interval='day', interval_value=1, from_date=None, to_date=None):
    """Fetch Historical Candle Data V3."""
    if to_date is None:
        to_date = datetime.now().strftime('%Y-%m-%d')
    if from_date is None:
        from_date = (datetime.now() - timedelta(days=100)).strftime('%Y-%m-%d')

    url = f"https://api.upstox.com/v3/historical-candle/{instrument_key}/{interval}/{interval_value}/{to_date}/{from_date}"
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
            return df
        else:
            print(f"Error fetching historical V3: {response.status_code} {response.text}")
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
        else:
            print(f"Error fetching option chain: {response.status_code} {response.text}")
    except Exception as e:
        print(f"Exception fetching option chain: {e}")
    return []

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
        dbc.Col(dbc.Card([dbc.CardHeader("CE Chart"), dbc.CardBody(dcc.Graph(id='ce-candle-graph'))]), width=6),
        dbc.Col(dbc.Card([dbc.CardHeader("PE Chart"), dbc.CardBody(dcc.Graph(id='pe-candle-graph'))]), width=6)
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
    [Input('prev-btn', 'n_clicks'),
     Input('next-btn', 'n_clicks')],
    [State('symbol-dropdown', 'value')]
)
def navigate_symbols(prev_clicks, next_clicks, current_symbol):
    ctx = dash.callback_context
    if not ctx.triggered:
        return current_symbol

    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    if current_symbol not in UNIQUE_SYMBOLS:
        return UNIQUE_SYMBOLS[0] if UNIQUE_SYMBOLS else None

    idx = UNIQUE_SYMBOLS.index(current_symbol)
    if button_id == 'next-btn':
        return UNIQUE_SYMBOLS[(idx + 1) % len(UNIQUE_SYMBOLS)]
    elif button_id == 'prev-btn':
        return UNIQUE_SYMBOLS[(idx - 1) % len(UNIQUE_SYMBOLS)]
    return current_symbol

@app.callback(
    [Output('expiry-dropdown', 'options'),
     Output('expiry-dropdown', 'value'),
     Output('underlying-info-store', 'data')],
    [Input('symbol-dropdown', 'value')]
)
def update_symbol_expiries(symbol):
    if not symbol:
        return [], None, None

    underlying_info = get_underlying_instrument_info(symbol)
    if not underlying_info:
        return [], None, None

    # Filter FUTSTK for this symbol
    futstk_rows = INSTRUMENTS_DF[
        (INSTRUMENTS_DF['Symbol'] == symbol) &
        (INSTRUMENTS_DF['instrument_type'] == 'FUTSTK')
    ]

    if futstk_rows.empty:
        # Fallback to OPTSTK expiries
        expiries = sorted(INSTRUMENTS_DF[INSTRUMENTS_DF['Symbol'] == symbol]['expiry'].dropna().unique())
    else:
        expiries = sorted(futstk_rows['expiry'].dropna().unique())

    options = [{'label': e, 'value': e} for e in expiries]
    default_expiry = expiries[0] if expiries else None

    underlying_info['symbol'] = symbol

    return options, default_expiry, underlying_info

@app.callback(
    [Output('profile-display', 'children'),
     Output('shareholding-display', 'children'),
     Output('corp-action-display', 'children')],
    [Input('underlying-info-store', 'data')]
)
def update_fundamentals(info):
    if not info or not info.get('isin'):
        return "N/A", "N/A", "N/A"

    isin = info['isin']
    profile = fetch_company_profile(isin)
    shares = fetch_shareholdings(isin)
    actions = fetch_corporate_actions(isin)

    # Profile
    profile_html = html.Div([
        html.P(f"Sector: {profile.get('sector', 'N/A')}", style={'fontWeight': 'bold'}),
        html.P(profile.get('company_profile', 'N/A')[:100] + "...", style={'fontSize': '10px'})
    ])

    # Shareholding
    if shares:
        latest = shares[0] # Assuming first is latest
        shares_html = html.Div([
            html.P(f"Q: {latest.get('quarter', 'N/A')}", style={'fontWeight': 'bold'}),
            html.Ul([
                html.Li(f"Promoter: {latest.get('promoter', 0)}%"),
                html.Li(f"FII: {latest.get('fii', 0)}%"),
                html.Li(f"DII: {latest.get('dii', 0)}%"),
                html.Li(f"Public: {latest.get('public', 0)}%")
            ], style={'fontSize': '10px', 'paddingLeft': '15px'})
        ])
    else:
        shares_html = "No data"

    # Corp Actions
    if actions:
        latest_act = actions[0]
        actions_html = html.Div([
            html.P(f"{latest_act.get('type', 'N/A')}", style={'fontWeight': 'bold'}),
            html.P(f"Date: {latest_act.get('ex_date', 'N/A')}", style={'fontSize': '10px'}),
            html.P(f"{latest_act.get('description', 'N/A')}", style={'fontSize': '10px'})
        ])
    else:
        actions_html = "No data"

    return profile_html, shares_html, actions_html

@app.callback(
    [Output('ce-strike-radio', 'options'),
     Output('ce-strike-radio', 'value'),
     Output('pe-strike-radio', 'options'),
     Output('pe-strike-radio', 'value'),
     Output('option-chain-store', 'data'),
     Output('underlying-info-store', 'data', allow_duplicate=True)],
    [Input('expiry-dropdown', 'value')],
    [State('underlying-info-store', 'data')],
    prevent_initial_call=True
)
def update_option_chain_data(expiry, underlying_info):
    if not expiry or not underlying_info:
        return [], None, [], None, None, underlying_info

    underlying_key = underlying_info['instrument_key']
    chain_data = fetch_option_chain(underlying_key, expiry)

    # Extract strikes
    strikes = sorted(list(set([d['strike_price'] for d in chain_data])))
    ce_options = [{'label': str(s), 'value': s} for s in strikes]
    pe_options = [{'label': str(s), 'value': s} for s in strikes]

    # Default selection: ATM strike
    # We need underlying price to find ATM
    underlying_price = 0
    if chain_data:
        underlying_price = chain_data[0].get('underlying_spot_price', 0)

    atm_strike = min(strikes, key=lambda x: abs(x - underlying_price)) if strikes else None

    updated_info = underlying_info.copy()
    updated_info.update({
        'price': underlying_price,
        'expiry': expiry
    })

    return ce_options, atm_strike, pe_options, atm_strike, chain_data, updated_info

@app.callback(
    Output('ce-candle-graph', 'figure'),
    [Input('ce-strike-radio', 'value')],
    [State('underlying-info-store', 'data')]
)
def update_ce_graph(strike, underlying_info):
    if not strike or not underlying_info:
        return go.Figure()

    symbol = underlying_info['symbol']
    expiry = underlying_info['expiry']

    # Find instrument key for CE
    match = INSTRUMENTS_DF[
        (INSTRUMENTS_DF['Symbol'] == symbol) &
        (INSTRUMENTS_DF['strike'] == strike) &
        (INSTRUMENTS_DF['option_type'] == 'CE') &
        (INSTRUMENTS_DF['expiry'] == expiry)
    ]
    if match.empty:
        return go.Figure()

    instrument_key = match.iloc[0]['instrument_key']
    df = fetch_historical_v3(instrument_key)
    if df.empty:
        return go.Figure()

    fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                        vertical_spacing=0.02, row_heights=[0.5, 0.25, 0.25])

    fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'],
                                 low=df['low'], close=df['close'], name='OHLC'), row=1, col=1)
    fig.add_trace(go.Bar(x=df['timestamp'], y=df['volume'], name='Volume'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['oi'], name='OI'), row=3, col=1)

    fig.update_layout(
        title=f"CE Chart - {symbol} {strike} {expiry}",
        plot_bgcolor='white',
        paper_bgcolor='white',
        xaxis_rangeslider_visible=False,
        showlegend=False
    )
    fig.update_xaxes(showline=True, linewidth=1, linecolor='black', mirror=True)
    fig.update_yaxes(showline=True, linewidth=1, linecolor='black', mirror=True)

    return fig

@app.callback(
    Output('pe-candle-graph', 'figure'),
    [Input('pe-strike-radio', 'value')],
    [State('underlying-info-store', 'data')]
)
def update_pe_graph(strike, underlying_info):
    if not strike or not underlying_info:
        return go.Figure()

    symbol = underlying_info['symbol']
    expiry = underlying_info['expiry']

    match = INSTRUMENTS_DF[
        (INSTRUMENTS_DF['Symbol'] == symbol) &
        (INSTRUMENTS_DF['strike'] == strike) &
        (INSTRUMENTS_DF['option_type'] == 'PE') &
        (INSTRUMENTS_DF['expiry'] == expiry)
    ]
    if match.empty:
        return go.Figure()

    instrument_key = match.iloc[0]['instrument_key']
    df = fetch_historical_v3(instrument_key)
    if df.empty:
        return go.Figure()

    fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                        vertical_spacing=0.02, row_heights=[0.5, 0.25, 0.25])

    fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'],
                                 low=df['low'], close=df['close'], name='OHLC'), row=1, col=1)
    fig.add_trace(go.Bar(x=df['timestamp'], y=df['volume'], name='Volume'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['oi'], name='OI'), row=3, col=1)

    fig.update_layout(
        title=f"PE Chart - {symbol} {strike} {expiry}",
        plot_bgcolor='white',
        paper_bgcolor='white',
        xaxis_rangeslider_visible=False,
        showlegend=False
    )
    fig.update_xaxes(showline=True, linewidth=1, linecolor='black', mirror=True)
    fig.update_yaxes(showline=True, linewidth=1, linecolor='black', mirror=True)

    return fig

@app.callback(
    Output('iv-graph', 'figure'),
    [Input('option-chain-store', 'data')],
    [State('underlying-info-store', 'data')]
)
def update_iv_graph(chain_data, underlying_info):
    if not chain_data or not underlying_info:
        return go.Figure()

    underlying_price = underlying_info['price']

    # Extract data
    iv_data = []
    for item in chain_data:
        strike = item['strike_price']

        # Filter far OTM (e.g. within 20% range)
        if strike < underlying_price * 0.8 or strike > underlying_price * 1.2:
            continue

        call_iv = item.get('call_options', {}).get('option_greeks', {}).get('iv', 0)
        put_iv = item.get('put_options', {}).get('option_greeks', {}).get('iv', 0)

        iv_data.append({
            'strike': strike,
            'call_iv': call_iv if call_iv > 0 else None,
            'put_iv': put_iv if put_iv > 0 else None
        })

    df_iv = pd.DataFrame(iv_data).sort_values('strike')

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_iv['strike'], y=df_iv['call_iv'], mode='lines+markers',
                             name='Call IV', line=dict(color='red'), marker=dict(size=8)))
    fig.add_trace(go.Scatter(x=df_iv['strike'], y=df_iv['put_iv'], mode='lines+markers',
                             name='Put IV', line=dict(color='green'), marker=dict(size=8)))

    fig.update_layout(
        title="IV of Put and Call",
        xaxis_title="Strike Price",
        yaxis_title="IV",
        plot_bgcolor='white',
        paper_bgcolor='white'
    )
    fig.update_xaxes(showline=True, linewidth=1, linecolor='black', gridcolor='lightgrey')
    fig.update_yaxes(showline=True, linewidth=1, linecolor='black', gridcolor='lightgrey')

    return fig

@app.callback(
    [Output('pcr-graph', 'figure'),
     Output('oi-graph', 'figure'),
     Output('oi-change-graph', 'figure'),
     Output('volume-graph', 'figure')],
    [Input('option-chain-store', 'data')],
    [State('underlying-info-store', 'data')]
)
def update_metric_graphs(chain_data, underlying_info):
    if not chain_data or not underlying_info:
        return [go.Figure()]*4

    underlying_price = underlying_info['price']
    metrics = []
    for item in chain_data:
        strike = item['strike_price']
        ce_md = item.get('call_options', {}).get('market_data', {})
        pe_md = item.get('put_options', {}).get('market_data', {})

        ce_oi = ce_md.get('oi', 0)
        pe_oi = pe_md.get('oi', 0)
        ce_prev_oi = ce_md.get('prev_oi', 0)
        pe_prev_oi = pe_md.get('prev_oi', 0)
        ce_vol = ce_md.get('volume', 0)
        pe_vol = pe_md.get('volume', 0)

        pcr = pe_oi / ce_oi if ce_oi > 0 else 0

        metrics.append({
            'strike': strike,
            'pcr': pcr,
            'ce_oi': ce_oi,
            'pe_oi': pe_oi,
            'ce_oi_change': ce_oi - ce_prev_oi,
            'pe_oi_change': pe_oi - pe_prev_oi,
            'ce_vol': ce_vol,
            'pe_vol': pe_vol,
            'total_vol': ce_vol + pe_vol
        })

    df = pd.DataFrame(metrics).sort_values('strike')

    # PCR Graph
    fig_pcr = go.Figure()
    fig_pcr.add_trace(go.Scatter(x=df['strike'], y=df['pcr'], mode='lines+markers', name='PCR'))
    fig_pcr.add_vline(x=underlying_price, line_dash="dash", line_color="black", annotation_text="Underlying")
    fig_pcr.update_layout(title="PCR by Strike", plot_bgcolor='white', paper_bgcolor='white')

    # OI Graph
    fig_oi = go.Figure()
    fig_oi.add_trace(go.Bar(x=df['strike'], y=df['ce_oi'], name='CE OI', marker_color='red'))
    fig_oi.add_trace(go.Bar(x=df['strike'], y=df['pe_oi'], name='PE OI', marker_color='green'))
    fig_oi.add_vline(x=underlying_price, line_dash="dash", line_color="black")
    fig_oi.update_layout(title="Open Interest", barmode='group', plot_bgcolor='white', paper_bgcolor='white')

    # OI Change Graph
    fig_oi_chg = go.Figure()
    fig_oi_chg.add_trace(go.Bar(x=df['strike'], y=df['ce_oi_change'], name='CE OI Chg', marker_color='red'))
    fig_oi_chg.add_trace(go.Bar(x=df['strike'], y=df['pe_oi_change'], name='PE OI Chg', marker_color='green'))
    fig_oi_chg.add_vline(x=underlying_price, line_dash="dash", line_color="black")
    fig_oi_chg.update_layout(title="Change in Open Interest", barmode='group', plot_bgcolor='white', paper_bgcolor='white')

    # Volume Graph
    fig_vol = go.Figure()
    fig_vol.add_trace(go.Bar(x=df['strike'], y=df['total_vol'], name='Total Volume', marker_color='blue'))
    fig_vol.add_vline(x=underlying_price, line_dash="dash", line_color="black")
    fig_vol.update_layout(title="Volume", plot_bgcolor='white', paper_bgcolor='white')

    for f in [fig_pcr, fig_oi, fig_oi_chg, fig_vol]:
        f.update_xaxes(showline=True, linewidth=1, linecolor='black', gridcolor='lightgrey')
        f.update_yaxes(showline=True, linewidth=1, linecolor='black', gridcolor='lightgrey')

    return fig_pcr, fig_oi, fig_oi_chg, fig_vol

@app.callback(
    [Output('max-pain-display', 'children'),
     Output('underlying-price-display', 'children')],
    [Input('option-chain-store', 'data')],
    [State('underlying-info-store', 'data')]
)
def update_max_pain(chain_data, underlying_info):
    if not chain_data or not underlying_info:
        return "N/A", "Underlying: N/A"

    strikes = sorted([d['strike_price'] for d in chain_data])
    min_pain = float('inf')
    max_pain_strike = strikes[0]

    for s in strikes:
        total_pain = 0
        for item in chain_data:
            strike = item['strike_price']
            ce_oi = item.get('call_options', {}).get('market_data', {}).get('oi', 0)
            pe_oi = item.get('put_options', {}).get('market_data', {}).get('oi', 0)

            # Pain for CE: Writers lose if strike < s
            if strike < s:
                total_pain += ce_oi * (s - strike)
            # Pain for PE: Writers lose if strike > s
            if strike > s:
                total_pain += pe_oi * (strike - s)

        if total_pain < min_pain:
            min_pain = total_pain
            max_pain_strike = s

    underlying_price = underlying_info['price']
    diff = underlying_price - max_pain_strike
    color = "green" if diff >= 0 else "red"
    arrow = "▲" if diff >= 0 else "▼"

    max_pain_html = html.Span(f"{max_pain_strike}")
    price_html = html.Div([
        html.Span(f"Underlying: {underlying_price:.2f} "),
        html.Span(f"({arrow} {abs(diff):.2f})", style={'color': color})
    ])

    return max_pain_html, price_html

@app.callback(
    Output('option-chain-table-container', 'children'),
    [Input('option-chain-store', 'data')],
    [State('underlying-info-store', 'data')]
)
def update_table(chain_data, underlying_info):
    if not chain_data:
        return "No data"

    underlying_price = 0
    if underlying_info:
        underlying_price = underlying_info.get('price', 0)

    rows = []
    for item in chain_data:
        strike = item['strike_price']
        ce_md = item.get('call_options', {}).get('market_data', {})
        ce_g = item.get('call_options', {}).get('option_greeks', {})
        pe_md = item.get('put_options', {}).get('market_data', {})
        pe_g = item.get('put_options', {}).get('option_greeks', {})

        def calc_oi_chg_pct(md):
            oi = md.get('oi', 0)
            prev_oi = md.get('prev_oi', 0)
            if prev_oi and prev_oi != 0:
                return round(((oi - prev_oi) / prev_oi) * 100, 2)
            return 0

        rows.append({
            'CE_OI': ce_md.get('oi'),
            'CE_OI_Chg%': calc_oi_chg_pct(ce_md),
            'CE_Delta': ce_g.get('delta'),
            'CE_POP': ce_g.get('pop'),
            'CE_LTP': ce_md.get('ltp'),
            'Strike': strike,
            'PE_LTP': pe_md.get('ltp'),
            'PE_POP': pe_g.get('pop'),
            'PE_Delta': pe_g.get('delta'),
            'PE_OI_Chg%': calc_oi_chg_pct(pe_md),
            'PE_OI': pe_md.get('oi')
        })

    df = pd.DataFrame(rows).sort_values('Strike', ascending=False)

    # Calculate Max OI for highlighting
    max_ce_oi = df['CE_OI'].max() if not df['CE_OI'].empty else 0
    max_pe_oi = df['PE_OI'].max() if not df['PE_OI'].empty else 0

    # Find ATM boundary rows for the black border
    # Since it's sorted High to Low:
    # Top rows are High strikes (OTM CE / ITM PE)
    # Bottom rows are Low strikes (ITM CE / OTM PE)
    # Boundary is where Strike >= price and next Strike < price

    atm_style = []
    if underlying_price > 0:
        for i in range(len(df) - 1):
            s1 = df.iloc[i]['Strike']
            s2 = df.iloc[i+1]['Strike']
            if s1 >= underlying_price and s2 < underlying_price:
                # Add border to bottom of row i
                atm_style.append({
                    'if': {'row_index': i},
                    'borderBottom': '5px solid black'
                })
                # Add border to top of row i+1
                atm_style.append({
                    'if': {'row_index': i + 1},
                    'borderTop': '5px solid black'
                })
                break

    return dash_table.DataTable(
        data=df.to_dict('records'),
        columns=[{'name': i, 'id': i} for i in df.columns],
        style_cell={'textAlign': 'center', 'border': '1px solid grey'},
        style_header={'fontWeight': 'bold', 'backgroundColor': 'lightgrey'},
        style_data_conditional=[
            # Max CE OI Highlight (Light Red)
            {
                'if': {
                    'filter_query': f'{{CE_OI}} = {max_ce_oi}',
                    'column_id': ['CE_OI', 'CE_OI_Chg%', 'CE_Delta', 'CE_POP', 'CE_LTP']
                },
                'backgroundColor': '#FFCCCB'
            },
            # Max PE OI Highlight (Light Green)
            {
                'if': {
                    'filter_query': f'{{PE_OI}} = {max_pe_oi}',
                    'column_id': ['PE_OI', 'PE_OI_Chg%', 'PE_Delta', 'PE_POP', 'PE_LTP']
                },
                'backgroundColor': '#90EE90'
            },
            # Change % coloring
            {
                'if': {'filter_query': '{CE_OI_Chg%} > 0', 'column_id': 'CE_OI_Chg%'},
                'color': 'green'
            },
            {
                'if': {'filter_query': '{CE_OI_Chg%} < 0', 'column_id': 'CE_OI_Chg%'},
                'color': 'red'
            },
            {
                'if': {'filter_query': '{PE_OI_Chg%} > 0', 'column_id': 'PE_OI_Chg%'},
                'color': 'green'
            },
            {
                'if': {'filter_query': '{PE_OI_Chg%} < 0', 'column_id': 'PE_OI_Chg%'},
                'color': 'red'
            }
        ] + atm_style,
        page_size=100 # Show more rows as requested
    )

if __name__ == "__main__":
    app.run(debug=True)
