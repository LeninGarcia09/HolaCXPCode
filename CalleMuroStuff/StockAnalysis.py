"""
Resilient Stock Scenario Dashboard (Streamlit + CLI fallback)

This module provides:
- DCF and scenario modeling for stocks using Free Cash Flow inputs
- Optional Finnhub integration (if you provide an API key)
- Streamlit UI when streamlit is installed; otherwise a CLI runner and matplotlib plots
- CSV/Excel export capability when run interactively

Notes about the sandbox error you saw:
- If `ModuleNotFoundError: No module named 'streamlit'` appears, this script will now automatically fall back to a CLI mode that does not require Streamlit.
- This file also includes basic unit tests for the DCF and scenario logic.

To run with Streamlit (if installed):
    streamlit run stock_scenario_dashboard.py

To run in CLI mode (no Streamlit required):
    python stock_scenario_dashboard.py --tickers PLTR,NVDA --years 3 --growth 0.20

To run tests:
    python stock_scenario_dashboard.py --test

Requirements (recommended): yfinance, pandas, numpy, requests, plotly, openpyxl, matplotlib
"""

from __future__ import annotations
import sys
import math
import argparse
import json
import os
from io import BytesIO
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Now you can access them like:
# finnhub_key = os.getenv('FINNHUB_API_KEY')
# default_wacc = float(os.getenv('DEFAULT_WACC', 0.10))

# Try to import optional UI libs
try:
    import streamlit as st
    STREAMLIT_AVAILABLE = True
except Exception:
    STREAMLIT_AVAILABLE = False

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except Exception:
    YFINANCE_AVAILABLE = False

import pandas as pd
import numpy as np
import requests

# Visualization libraries
try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except Exception:
    PLOTLY_AVAILABLE = False

try:
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except Exception:
    MATPLOTLIB_AVAILABLE = False

# ---------------------- Core Functions ----------------------

def run_dcf(last_fcf: float, growth_rate, years: int, wacc: float, terminal_growth: float) -> dict | None:
    """Run a simple multi-year DCF projecting FCF and computing a terminal value via Gordon Growth.

    last_fcf: most recent annual Free Cash Flow (positive float)
    growth_rate: scalar (e.g., 0.2) or an iterable of per-year rates
    years: number of projection years (int)
    wacc: discount rate (e.g., 0.10)
    terminal_growth: terminal growth rate (e.g., 0.02)

    Returns a dict with keys: npv, discounted_cashflows, projected_cashflows, terminal_value, discounted_terminal_value
    Returns None if last_fcf is invalid.
    """
    if last_fcf is None or last_fcf <= 0 or years <= 0:
        return None

    # Normalize growth_rate into a list
    if isinstance(growth_rate, (int, float)):
        growth_list = [float(growth_rate)] * years
    else:
        growth_list = list(growth_rate)
        # pad or trim
        if len(growth_list) < years:
            growth_list = growth_list + [growth_list[-1]] * (years - len(growth_list))
        else:
            growth_list = growth_list[:years]

    cashflows = []
    fcf = float(last_fcf)
    for g in growth_list:
        fcf = fcf * (1.0 + float(g))
        cashflows.append(fcf)

    discounted = [cf / ((1.0 + wacc) ** (i + 1)) for i, cf in enumerate(cashflows)]

    # Guard against invalid terminal calculation
    if wacc <= terminal_growth:
        # terminal formula would blow up; return None to signal invalid inputs
        return None

    terminal_value = cashflows[-1] * (1.0 + terminal_growth) / (wacc - terminal_growth)
    discounted_tv = terminal_value / ((1.0 + wacc) ** years)

    npv = sum(discounted) + discounted_tv

    return {
        'npv': float(npv),
        'discounted_cashflows': discounted,
        'projected_cashflows': cashflows,
        'terminal_value': float(terminal_value),
        'discounted_terminal_value': float(discounted_tv)
    }


def scenario_prices_from_dcf(npv: float | None, shares_outstanding: int | None, current_price: float | None, pe_target: float = 25.0) -> dict:
    """Turn DCF npv (equity value) into per-share intrinsic and simple Down/Base/Up scenarios.

    If npv or shares_outstanding are missing, falls back to using current_price and PE multiple.
    """
    intrinsic_per_share = None
    if npv and shares_outstanding and shares_outstanding > 0:
        intrinsic_per_share = float(npv) / float(shares_outstanding)

    if intrinsic_per_share:
        downside = intrinsic_per_share * 0.8
        base = intrinsic_per_share
        upside = intrinsic_per_share * 1.25
    else:
        # fallback: use current price and PE target multiplier
        base = (current_price or 0.0) * 1.0 * (pe_target / 25.0)
        downside = base * 0.8
        upside = base * 1.25

    return {'Downside': downside, 'Base': base, 'Upside': upside, 'IntrinsicPerShare': intrinsic_per_share}


# ---------------------- Data Fetching (yfinance / finnhub) ----------------------

def fetch_with_yfinance(ticker: str) -> dict:
    """Get basic data from yfinance. If yfinance isn't available, raise a clear error.
    Returns: dict with keys: ticker, company, price, fcf, info
    """
    if not YFINANCE_AVAILABLE:
        raise RuntimeError('yfinance package is not available in this environment. Install yfinance to fetch live data.')

    t = yf.Ticker(ticker)
    info = t.info or {}

    # Try to compute last annual FCF from cashflow statement
    last_fcf = None
    try:
        cashflow = t.cashflow
        if cashflow is not None and not cashflow.empty:
            # yfinance cashflow is a DataFrame with rows like 'Total Cash From Operating Activities' and columns for years
            # We'll try a few common row labels and pick the first column (most recent)
            candidates = ['Total Cash From Operating Activities', 'Net Cash Provided by Operating Activities', 'Operating Cash Flow']
            ocf = None
            for r in candidates:
                if r in cashflow.index:
                    ocf = float(cashflow.loc[r].iloc[0])
                    break
            capex = None
            if 'Capital Expenditures' in cashflow.index:
                capex = float(cashflow.loc['Capital Expenditures'].iloc[0])
            if ocf is not None and capex is not None:
                last_fcf = ocf + capex  # capex is negative
    except Exception:
        last_fcf = None

    # Also try info fields
    try:
        if not last_fcf and info.get('freeCashflow'):
            last_fcf = info.get('freeCashflow')
    except Exception:
        pass

    return {
        'ticker': ticker.upper(),
        'company': info.get('shortName') if info else None,
        'price': info.get('currentPrice') if info else None,
        'market_cap': info.get('marketCap') if info else None,
        'forward_pe': info.get('forwardPE') if info else None,
        'trailing_pe': info.get('trailingPE') if info else None,
        'peg': info.get('pegRatio') if info else None,
        'fcf': last_fcf,
        'info': info
    }


def fetch_from_finnhub(ticker: str, finnhub_key: str) -> dict:
    base = 'https://finnhub.io/api/v1'
    params = {'token': finnhub_key}
    out = {'ticker': ticker.upper()}
    try:
        resp = requests.get(f'{base}/stock/metric', params={**params, 'symbol': ticker, 'metric': 'all'}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            out['fcf'] = data.get('metric', {}).get('freeCashFlowTTM')
            out['pe'] = data.get('metric', {}).get('peNormalizedAnnual')
            out['info_raw'] = data
        else:
            out['error'] = f'HTTP {resp.status_code}'
    except Exception as e:
        out['error'] = str(e)
    return out


# ---------------------- Visualization Helpers ----------------------

def plot_scenarios_cli(ticker: str, company: str | None, scenarios: dict, current_price: float | None, dcf_projected: list | None = None, outpath: str | None = None):
    """Create and save a matplotlib plot with scenario bars and projected FCF (if available). Returns filepath if saved."""
    if not MATPLOTLIB_AVAILABLE:
        print('matplotlib not available; skipping plot generation for', ticker)
        return None

    labels = ['Downside', 'Base', 'Upside']
    values = [scenarios['Downside'], scenarios['Base'], scenarios['Upside']]

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(labels, values, alpha=0.6)
    if current_price is not None:
        ax.plot(labels, [current_price] * 3, marker='o', linestyle='--', label='Current Price')
    ax.set_title(f"{company or ticker} - Scenario Prices")
    ax.set_ylabel('Price ($)')
    ax.grid(axis='y', linestyle='--', alpha=0.5)
    if dcf_projected:
        # add projected FCF on secondary axis
        ax2 = ax.twinx()
        years = list(range(1, len(dcf_projected) + 1))
        ax2.plot([f'Year {y}' for y in years], dcf_projected, marker='x', label='Projected FCF')
        ax2.set_ylabel('Projected FCF')

    if outpath is None:
        outpath = f'{ticker}_scenarios.png'
    fig.tight_layout()
    fig.savefig(outpath)
    plt.close(fig)
    print('Saved plot to', outpath)
    return outpath


def plotly_scenarios_streamlit(scenarios: dict, current_price: float | None, dcf_projected: list | None = None):
    """Return a Plotly figure object for Streamlit consumption."""
    fig = go.Figure()
    fig.add_trace(go.Bar(x=['Downside', 'Base', 'Upside'], y=[scenarios['Downside'], scenarios['Base'], scenarios['Upside']], name='Scenarios'))
    if current_price is not None:
        fig.add_trace(go.Scatter(x=['Downside', 'Base', 'Upside'], y=[current_price] * 3, mode='lines+markers', name='Current Price'))
    if dcf_projected:
        fig.add_trace(go.Scatter(x=[f'Year {i+1}' for i in range(len(dcf_projected))], y=dcf_projected, mode='lines+markers', name='Projected FCF', yaxis='y2'))
        fig.update_layout(yaxis=dict(title='Price ($)'), yaxis2=dict(title='FCF', overlaying='y', side='right'))
    fig.update_layout(template='plotly_white')
    return fig


# ---------------------- CLI Runner ----------------------

def run_cli(args):
    tickers = [t.strip().upper() for t in args.tickers.split(',') if t.strip()]
    rows = []

    for ticker in tickers:
        print('\n====', ticker, '====')
        yf_data = None
        if YFINANCE_AVAILABLE:
            try:
                yf_data = fetch_with_yfinance(ticker)
            except Exception as e:
                print('yfinance fetch error for', ticker, '-', e)
                yf_data = {'ticker': ticker, 'company': None, 'price': None, 'fcf': None, 'info': {}}
        else:
            print('yfinance not available; skipping live fetch for', ticker)
            yf_data = {'ticker': ticker, 'company': None, 'price': None, 'fcf': None, 'info': {}}

        last_fcf = yf_data.get('fcf')
        if args.use_finnhub and args.finnhub_key:
            try:
                fb = fetch_from_finnhub(ticker, args.finnhub_key)
                if fb.get('fcf'):
                    last_fcf = fb.get('fcf')
            except Exception as e:
                print('Finnhub fetch error:', e)

        shares_outstanding = None
        try:
            shares_outstanding = yf_data.get('info', {}).get('sharesOutstanding')
        except Exception:
            shares_outstanding = None

        dcf_result = None
        if last_fcf and last_fcf > 0:
            dcf_result = run_dcf(last_fcf=last_fcf, growth_rate=args.growth, years=args.years, wacc=args.wacc, terminal_growth=args.terminal)
            if dcf_result is None:
                print('Invalid DCF inputs for', ticker, '(check WACC > terminal growth)')
        else:
            print('No valid FCF for', ticker, '- DCF not run')

        npv = dcf_result['npv'] if dcf_result else None
        intrinsic = (npv / shares_outstanding) if npv and shares_outstanding else None
        scenarios = scenario_prices_from_dcf(npv=npv, shares_outstanding=shares_outstanding, current_price=yf_data.get('price'), pe_target=args.pe)

        print('Company:', yf_data.get('company'))
        print('Current Price:', yf_data.get('price'))
        print('Last FCF:', last_fcf)
        print('Intrinsic per share (DCF):', intrinsic)
        print('Scenarios:', json.dumps(scenarios, indent=2))

        # Visualization
        if not STREAMLIT_AVAILABLE:
            plot_scenarios_cli(ticker, yf_data.get('company'), scenarios, yf_data.get('price'), dcf_result['projected_cashflows'] if dcf_result else None)

        rows.append({
            'Ticker': ticker,
            'Company': yf_data.get('company'),
            'CurrentPrice': yf_data.get('price'),
            'LastFCF': last_fcf,
            'SharesOutstanding': shares_outstanding,
            'DCF_NPV': npv,
            'IntrinsicPerShare': intrinsic,
            'Downside': scenarios['Downside'],
            'Base': scenarios['Base'],
            'Upside': scenarios['Upside']
        })

    df = pd.DataFrame(rows)
    out_csv = args.output or 'stock_scenarios_cli.csv'
    df.to_csv(out_csv, index=False)
    print('\nSaved results to', out_csv)


# ---------------------- Streamlit App ----------------------

def run_streamlit_app():
    st.set_page_config(page_title='Stock Scenario Dashboard', layout='wide')
    st.title('📈 Stock Valuation Scenario Analyzer — Interactive')

    st.sidebar.header('Data Sources & API Keys')
    use_finnhub = st.sidebar.checkbox('Use Finnhub (optional)', value=False)
    finnhub_key = st.sidebar.text_input('Finnhub API Key (if checked)') if use_finnhub else ''

    st.sidebar.header('Analysis Inputs')
    input_tickers = st.sidebar.text_input('Tickers (comma-separated)', 'PLTR, NVDA, QCOM')
    projection_years = st.sidebar.slider('Projection horizon (years)', 1, 10, 3)
    user_growth = st.sidebar.number_input('Base annual growth assumption for DCF (decimal)', min_value=0.0, max_value=1.0, value=0.20, step=0.01)
    user_wacc = st.sidebar.number_input('WACC / discount rate (decimal)', min_value=0.0, max_value=1.0, value=0.10, step=0.005)
    user_terminal = st.sidebar.number_input('Terminal growth rate (decimal)', min_value=0.0, max_value=0.1, value=0.02, step=0.005)
    user_pe_target = st.sidebar.number_input('PE multiple for scenario fallback', min_value=1, max_value=200, value=25)

    st.sidebar.header('Output & Export')
    export_excel = st.sidebar.checkbox('Enable Excel export', value=True)

    if st.button('Analyze'):
        tickers = [t.strip().upper() for t in input_tickers.split(',') if t.strip()]
        rows = []
        per_ticker_dcf = {}

        for ticker in tickers:
            with st.spinner(f'Fetching {ticker}...'):
                finnhub_data = None
                if use_finnhub and finnhub_key:
                    finnhub_data = fetch_from_finnhub(ticker, finnhub_key)

                yf_data = fetch_with_yfinance(ticker) if YFINANCE_AVAILABLE else {'ticker': ticker, 'company': None, 'price': None, 'fcf': None, 'info': {}}

            last_fcf = None
            if finnhub_data and finnhub_data.get('fcf'):
                last_fcf = finnhub_data['fcf']
            elif yf_data.get('fcf'):
                last_fcf = yf_data.get('fcf')

            shares_outstanding = None
            try:
                shares_outstanding = yf_data['info'].get('sharesOutstanding')
            except Exception:
                shares_outstanding = None

            dcf = None
            npv = None
            intrinsic = None
            if last_fcf and last_fcf > 0:
                dcf = run_dcf(last_fcf=last_fcf, growth_rate=user_growth, years=projection_years, wacc=user_wacc, terminal_growth=user_terminal)
                if dcf:
                    npv = dcf['npv']
                    intrinsic = npv / shares_outstanding if shares_outstanding else None
                    per_ticker_dcf[ticker] = dcf
                else:
                    st.warning(f'DCF could not be computed for {ticker} (check WACC > terminal growth)')

            scenarios = scenario_prices_from_dcf(npv=npv if npv else None, shares_outstanding=shares_outstanding, current_price=yf_data.get('price'), pe_target=user_pe_target)

            row = {
                'Ticker': ticker,
                'Company': yf_data.get('company'),
                'CurrentPrice': yf_data.get('price'),
                'LastFCF': last_fcf,
                'SharesOutstanding': shares_outstanding,
                'DCF_NPV': npv,
                'IntrinsicPerShare': intrinsic,
                'Downside': scenarios['Downside'],
                'Base': scenarios['Base'],
                'Upside': scenarios['Upside']
            }
            rows.append(row)

        df = pd.DataFrame(rows)
        st.success('Analysis complete')
        st.dataframe(df, use_container_width=True)

        st.subheader('Visualizations')
        for _, r in df.iterrows():
            ticker = r['Ticker']
            fig = plotly_scenarios_streamlit({'Downside': r['Downside'], 'Base': r['Base'], 'Upside': r['Upside']}, r['CurrentPrice'], per_ticker_dcf.get(ticker, {}).get('projected_cashflows') if per_ticker_dcf.get(ticker) else None)
            st.plotly_chart(fig, use_container_width=True)

        # Export
        if export_excel and not df.empty:
            towrite = BytesIO()
            with pd.ExcelWriter(towrite, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='scenarios')
                for tk, dcfd in per_ticker_dcf.items():
                    df_dcf = pd.DataFrame({'Year': list(range(1, len(dcfd['projected_cashflows']) + 1)), 'ProjectedFCF': dcfd['projected_cashflows'], 'DiscountedFCF': dcfd['discounted_cashflows']})
                    df_dcf.to_excel(writer, sheet_name=f'{tk}_dcf', index=False)
            towrite.seek(0)
            st.download_button(label='Download Excel', data=towrite, file_name='stock_scenarios.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(label='Download CSV', data=csv, file_name='stock_scenarios.csv', mime='text/csv')


# ---------------------- Unit Tests ----------------------

def _approx(a, b, rel=1e-6):
    return abs(a - b) <= max(rel * max(abs(a), abs(b)), 1e-9)


def run_unit_tests():
    print('Running unit tests...')

    # Test 1: run_dcf simple
    last_fcf = 100.0
    d = run_dcf(last_fcf=last_fcf, growth_rate=0.10, years=3, wacc=0.10, terminal_growth=0.02)
    assert d is not None, 'DCF returned None for valid inputs'
    # manual check: project FCF: 110,121,133.1 -> discounted
    projected = d['projected_cashflows']
    assert len(projected) == 3
    assert _approx(projected[0], 110.0)

    # Test 2: invalid terminal (wacc <= terminal)
    d2 = run_dcf(last_fcf=100.0, growth_rate=0.05, years=3, wacc=0.03, terminal_growth=0.04)
    assert d2 is None, 'Expected None when WACC <= terminal growth'

    # Test 3: scenario_prices_from_dcf fallback
    s = scenario_prices_from_dcf(None, None, current_price=50.0, pe_target=25)
    assert s['Base'] > 0

    print('All tests passed.')


# ---------------------- Entrypoint ----------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description='Stock Scenario Dashboard (CLI)')
    parser.add_argument('--tickers', type=str, default='PLTR', help='Comma-separated tickers')
    parser.add_argument('--years', type=int, default=3, help='Projection years')
    parser.add_argument('--growth', type=float, default=0.20, help='Base growth rate (decimal)')
    parser.add_argument('--wacc', type=float, default=0.10, help='WACC / discount rate')
    parser.add_argument('--terminal', type=float, default=0.02, help='Terminal growth rate')
    parser.add_argument('--pe', type=float, default=25.0, help='PE target for fallback')
    parser.add_argument('--use-finnhub', dest='use_finnhub', action='store_true')
    parser.add_argument('--finnhub-key', type=str, default='', help='Finnhub API key')
    parser.add_argument('--output', type=str, default='stock_scenarios_cli.csv', help='Output CSV path')
    parser.add_argument('--test', dest='test', action='store_true', help='Run unit tests and exit')

    args = parser.parse_args(argv)

    if args.test:
        run_unit_tests()
        return 0

    if STREAMLIT_AVAILABLE:
        # If streamlit is available, instruct the user to run via streamlit instead
        print('Streamlit detected. To use the interactive app, run: streamlit run', sys.argv[0])
        print('Falling back to CLI runner for this invocation...')

    run_cli(args)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
