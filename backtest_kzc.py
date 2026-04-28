#!/usr/bin/env python3
"""KZC Strategy Backtest — Kill Zone Confluence"""

import pandas as pd
import numpy as np
import json
from dataclasses import dataclass, field
from typing import Optional, List
import warnings
warnings.filterwarnings('ignore')

# ── CONFIG ────────────────────────────────────────────────────────────────────
INITIAL_BALANCE = 100.0
RISK_PCT        = 0.01
TP1_R           = 1.5
TP2_R           = 2.5
MIN_SCORE       = 5
MAX_CONCURRENT  = 2

# Kill zones in server time (forex broker ≈ UTC+2 ≈ CET summer)
# London 07-10, NY 13-16 — in server hours
FOREX_KZ        = [(7, 10), (13, 16)]
XAUUSD_KZ       = [(5, 8),  (11, 14)]   # UTC
FOREX_HARD_CLOSE  = 16
XAUUSD_HARD_CLOSE = 14

PIP       = {'EURUSD': 0.0001, 'GBPJPY': 0.01, 'USDJPY': 0.01, 'XAUUSD': 0.1}
SL_MAX_P  = {'EURUSD': 40,    'GBPJPY': 80,    'USDJPY': 40,    'XAUUSD': 500}
SL_MIN_P  = {'EURUSD': 8,     'GBPJPY': 15,    'USDJPY': 8,     'XAUUSD': 150}

BASE = '/root/.claude/uploads/b4287ec5-f155-4aea-90fa-86bd26a4975e'


# ── DATA LOADING ──────────────────────────────────────────────────────────────
def load_forex(pair):
    df = pd.read_csv(f'{BASE}/019dd136-{pair}_M15.csv', encoding='utf-16', sep='\t')
    df.columns = [c.strip() for c in df.columns]
    df['time'] = pd.to_datetime(df['time_server'].str.strip(), format='%Y.%m.%d %H:%M:%S')
    return df[['time','open','high','low','close']].sort_values('time').reset_index(drop=True)

def load_xauusd(tf):
    df = pd.read_csv(f'{BASE}/019dd13d-XAUUSD_{tf}.csv', encoding='utf-8', header=None,
                     names=['t','open','high','low','close','vol'])
    df['time'] = pd.to_datetime(df['t'])
    return df[['time','open','high','low','close']].sort_values('time').reset_index(drop=True)


# ── INDICATORS ────────────────────────────────────────────────────────────────
def swing_points(df, n=2):
    H = df['high'].values
    L = df['low'].values
    N = len(df)
    sh = np.zeros(N)
    sl = np.zeros(N)
    for i in range(n, N - n):
        if all(H[i] > H[i-k] for k in range(1,n+1)) and all(H[i] > H[i+k] for k in range(1,n+1)):
            if i + n < N:
                sh[i + n] = H[i]
        if all(L[i] < L[i-k] for k in range(1,n+1)) and all(L[i] < L[i+k] for k in range(1,n+1)):
            if i + n < N:
                sl[i + n] = L[i]
    out = df[['time']].copy()
    out['sh'] = sh
    out['sl'] = sl
    return out


def h4_trend_series(swings):
    N = len(swings)
    trend = np.zeros(N, dtype=int)
    shs, sls = [], []
    last = 0
    for i in range(N):
        if swings['sh'].iloc[i] > 0: shs.append(swings['sh'].iloc[i])
        if swings['sl'].iloc[i] > 0: sls.append(swings['sl'].iloc[i])
        if len(shs) >= 2 and len(sls) >= 2:
            hh = shs[-1] > shs[-2]; hl = sls[-1] > sls[-2]
            lh = shs[-1] < shs[-2]; ll = sls[-1] < sls[-2]
            if hh and hl:   last = 1
            elif lh and ll: last = -1
        trend[i] = last
    return trend


def h1_bos_series(h1):
    sw = swing_points(h1, n=2)
    bos = np.zeros(len(h1), dtype=int)
    last_sh, last_sl = 0.0, np.inf
    last_bos = 0
    for i in range(len(h1)):
        if sw['sh'].iloc[i] > 0: last_sh = sw['sh'].iloc[i]
        if sw['sl'].iloc[i] > 0: last_sl = sw['sl'].iloc[i]
        c = h1['close'].iloc[i]
        if last_sh > 0 and c > last_sh: last_bos = 1
        elif last_sl < np.inf and c < last_sl: last_bos = -1
        bos[i] = last_bos
    return bos


def compute_signals(m15, h1):
    N = len(m15)
    # Zone: bottom/top 35% of rolling 16-H1 range
    h1c = h1.copy()
    h1c['rh'] = h1['high'].rolling(16, min_periods=4).max()
    h1c['rl'] = h1['low'].rolling(16, min_periods=4).min()
    h1c['rr'] = h1c['rh'] - h1c['rl']
    merged = pd.merge_asof(m15[['time','close']].sort_values('time'),
                           h1c[['time','rh','rl','rr']].sort_values('time'),
                           on='time', direction='backward')
    at_dem = (merged['close'] <= merged['rl'] + 0.35 * merged['rr']).values
    at_sup = (merged['close'] >= merged['rh'] - 0.35 * merged['rr']).values

    # FVG rolling 8 bars
    H = m15['high'].values; L = m15['low'].values
    bfvg = np.zeros(N, dtype=bool); sfvg = np.zeros(N, dtype=bool)
    for i in range(2, N):
        if L[i] > H[i-2]: bfvg[i] = True
        if H[i] < L[i-2]: sfvg[i] = True
    bfvg = pd.Series(bfvg).rolling(8).max().fillna(0).astype(bool).values
    sfvg = pd.Series(sfvg).rolling(8).max().fillna(0).astype(bool).values

    # Entry candle
    O = m15['open'].values; C = m15['close'].values
    bcnd = np.zeros(N, dtype=bool); scnd = np.zeros(N, dtype=bool)
    for i in range(1, N):
        body = abs(C[i]-O[i]); rng = H[i]-L[i]; pbody = abs(C[i-1]-O[i-1])
        if rng > 0:
            if C[i]>O[i] and (C[i]>O[i-1] and O[i]<C[i-1] and body>pbody): bcnd[i]=True
            if C[i]>O[i] and body/rng >= 0.70: bcnd[i]=True
            if C[i]<O[i] and (C[i]<O[i-1] and O[i]>C[i-1] and body>pbody): scnd[i]=True
            if C[i]<O[i] and body/rng >= 0.70: scnd[i]=True

    return at_dem, at_sup, bfvg, sfvg, bcnd, scnd


# ── TRADE ─────────────────────────────────────────────────────────────────────
@dataclass
class Trade:
    pair: str; direction: int; entry_time: object; entry_price: float
    sl_price: float; tp1_price: float; tp2_price: float
    sl_dist: float; risk_amount: float; score: int
    exit_time: object = None; exit_price: float = 0.0
    pnl: float = 0.0; r_multiple: float = 0.0
    exit_reason: str = ''; tp1_hit: bool = False


def in_kz(hour, pair):
    kzs = XAUUSD_KZ if pair == 'XAUUSD' else FOREX_KZ
    return any(s <= hour < e for s, e in kzs)


# ── SIMULATION ────────────────────────────────────────────────────────────────
def simulate(pair, m15, h1, h4):
    print(f'  [{pair}] Computing indicators...')

    # H4 trend
    sw4 = swing_points(h4, n=2)
    tr4 = h4_trend_series(sw4)
    h4df = pd.DataFrame({'time': h4['time'], 'trend': tr4})

    # H1 BOS
    bos1 = h1_bos_series(h1)
    h1df = pd.DataFrame({'time': h1['time'], 'bos': bos1})

    # Align to M15
    m15s = m15[['time']].sort_values('time')
    tr_aligned = pd.merge_asof(m15s, h4df.sort_values('time'),
                                on='time', direction='backward')['trend'].fillna(0).astype(int).values
    bos_aligned = pd.merge_asof(m15s, h1df.sort_values('time'),
                                 on='time', direction='backward')['bos'].fillna(0).astype(int).values

    at_dem, at_sup, bfvg, sfvg, bcnd, scnd = compute_signals(m15, h1)

    T = m15['time'].values
    O = m15['open'].values; H = m15['high'].values
    L = m15['low'].values;  C = m15['close'].values
    N = len(m15)

    pip  = PIP[pair]
    slmx = SL_MAX_P[pair]; slmn = SL_MIN_P[pair]
    hc   = XAUUSD_HARD_CLOSE if pair == 'XAUUSD' else FOREX_HARD_CLOSE

    balance = INITIAL_BALANCE
    open_trades: List[Trade] = []
    closed: List[Trade] = []

    print(f'  [{pair}] Simulating {N} bars...')

    for i in range(20, N - 1):
        hour = pd.Timestamp(T[i]).hour

        # ── Manage open trades ─────────────────────────────────────────────
        for t in list(open_trades):
            bh = H[i]; bl = L[i]; bo = O[i]; bc = C[i]
            is_long = t.direction == 1
            eff_sl = t.entry_price if t.tp1_hit else t.sl_price

            # Hard close
            if hour >= hc:
                ep = bo
                if is_long:
                    r = (ep - t.entry_price) / t.sl_dist
                else:
                    r = (t.entry_price - ep) / t.sl_dist
                if t.tp1_hit:
                    t.r_multiple = TP1_R * 0.5 + max(0.0, r * 0.5)
                else:
                    t.r_multiple = r
                t.pnl = t.r_multiple * t.risk_amount
                t.exit_price = ep; t.exit_time = pd.Timestamp(T[i])
                t.exit_reason = 'hard_close'
                balance += t.pnl
                closed.append(t); open_trades.remove(t)
                continue

            if is_long:
                # Same-bar: if both SL and TP hit, use bar direction heuristic
                sl_hit  = bl <= eff_sl
                tp1_hit = (not t.tp1_hit) and bh >= t.tp1_price
                tp2_hit = t.tp1_hit and bh >= t.tp2_price

                if sl_hit and tp1_hit:
                    # Use bar direction: bullish bar → TP first
                    if bc > bo: sl_hit = False
                    else:       tp1_hit = False

                if sl_hit:
                    if t.tp1_hit:
                        t.r_multiple = TP1_R * 0.5; t.exit_reason = 'sl_be'
                    else:
                        t.r_multiple = -1.0; t.exit_reason = 'sl'
                    t.pnl = t.r_multiple * t.risk_amount
                    t.exit_price = eff_sl; t.exit_time = pd.Timestamp(T[i])
                    balance += t.pnl
                    closed.append(t); open_trades.remove(t); continue

                if tp1_hit: t.tp1_hit = True

                if tp2_hit:
                    t.r_multiple = TP1_R * 0.5 + TP2_R * 0.5
                    t.pnl = t.r_multiple * t.risk_amount
                    t.exit_price = t.tp2_price; t.exit_time = pd.Timestamp(T[i])
                    t.exit_reason = 'tp2'
                    balance += t.pnl
                    closed.append(t); open_trades.remove(t); continue

            else:  # short
                sl_hit  = bh >= eff_sl
                tp1_hit = (not t.tp1_hit) and bl <= t.tp1_price
                tp2_hit = t.tp1_hit and bl <= t.tp2_price

                if sl_hit and tp1_hit:
                    if bc < bo: sl_hit = False
                    else:       tp1_hit = False

                if sl_hit:
                    if t.tp1_hit:
                        t.r_multiple = TP1_R * 0.5; t.exit_reason = 'sl_be'
                    else:
                        t.r_multiple = -1.0; t.exit_reason = 'sl'
                    t.pnl = t.r_multiple * t.risk_amount
                    t.exit_price = eff_sl; t.exit_time = pd.Timestamp(T[i])
                    balance += t.pnl
                    closed.append(t); open_trades.remove(t); continue

                if tp1_hit: t.tp1_hit = True

                if tp2_hit:
                    t.r_multiple = TP1_R * 0.5 + TP2_R * 0.5
                    t.pnl = t.r_multiple * t.risk_amount
                    t.exit_price = t.tp2_price; t.exit_time = pd.Timestamp(T[i])
                    t.exit_reason = 'tp2'
                    balance += t.pnl
                    closed.append(t); open_trades.remove(t); continue

        # ── New entry ──────────────────────────────────────────────────────
        if len(open_trades) >= MAX_CONCURRENT: continue
        if not in_kz(hour, pair): continue
        if hour >= hc - 1: continue

        trend = tr_aligned[i]
        if trend == 0: continue
        bos = bos_aligned[i]

        if trend == 1:
            cond = [bos == 1, at_dem[i], bfvg[i], bcnd[i]]
            direction = 1
        else:
            cond = [bos == -1, at_sup[i], sfvg[i], scnd[i]]
            direction = -1

        score = 2 + sum(cond)  # trend(1) + KZ(1) always
        if score < MIN_SCORE: continue

        buf = (H[i] - L[i]) * 0.1
        if direction == 1:
            sl_p = L[i] - buf
            sl_d = C[i] - sl_p
        else:
            sl_p = H[i] + buf
            sl_d = sl_p - C[i]

        sl_pips = sl_d / pip
        if sl_pips < slmn or sl_pips > slmx: continue

        entry = O[i + 1]
        if direction == 1:
            sl_adj  = entry - sl_d
            tp1_adj = entry + TP1_R * sl_d
            tp2_adj = entry + TP2_R * sl_d
        else:
            sl_adj  = entry + sl_d
            tp1_adj = entry - TP1_R * sl_d
            tp2_adj = entry - TP2_R * sl_d

        t = Trade(pair=pair, direction=direction,
                  entry_time=pd.Timestamp(T[i+1]), entry_price=entry,
                  sl_price=sl_adj, tp1_price=tp1_adj, tp2_price=tp2_adj,
                  sl_dist=sl_d, risk_amount=balance * RISK_PCT, score=score)
        open_trades.append(t)

    # Close remaining at end
    for t in open_trades:
        lc = C[-1]; lt = pd.Timestamp(T[-1])
        r = (lc - t.entry_price) / t.sl_dist if t.direction == 1 else (t.entry_price - lc) / t.sl_dist
        t.r_multiple = TP1_R * 0.5 + max(0, r * 0.5) if t.tp1_hit else r
        t.pnl = t.r_multiple * t.risk_amount
        t.exit_price = lc; t.exit_time = lt; t.exit_reason = 'end_of_data'
        balance += t.pnl
        closed.append(t)

    return closed, balance


# ── METRICS ───────────────────────────────────────────────────────────────────
def metrics(trades, bal0, bal1):
    if not trades:
        return None
    rs = np.array([t.r_multiple for t in trades])
    wins = rs[rs > 0]; losses = rs[rs <= 0]
    pf_denom = abs(losses.sum()) if len(losses) > 0 and losses.sum() < 0 else 1
    pf = wins.sum() / pf_denom if len(wins) > 0 else 0

    eq = [bal0]
    b = bal0
    for t in sorted(trades, key=lambda x: x.entry_time):
        b += t.pnl; eq.append(b)
    eq = np.array(eq)
    peak = np.maximum.accumulate(eq)
    dd_pct = ((peak - eq) / peak * 100)
    dd_usd = peak - eq

    sharpe  = (rs.mean() / rs.std() * np.sqrt(252)) if rs.std() > 0 else 0
    neg     = rs[rs < 0]
    sortino = (rs.mean() / neg.std() * np.sqrt(252)) if len(neg) > 1 else 0

    reasons = {}
    for t in trades:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1

    # Monthly breakdown
    monthly = {}
    for t in trades:
        k = t.entry_time.strftime('%Y-%m')
        if k not in monthly: monthly[k] = []
        monthly[k].append(t.r_multiple)

    return {
        'n': len(trades), 'wr': len(wins)/len(trades)*100,
        'avg_win': wins.mean() if len(wins) else 0,
        'avg_loss': abs(losses.mean()) if len(losses) else 0,
        'pf': pf, 'total_r': rs.sum(),
        'max_dd_pct': dd_pct.max(), 'max_dd_usd': dd_usd.max(),
        'sharpe': sharpe, 'sortino': sortino,
        'roi': (bal1 - bal0) / bal0 * 100,
        'net_pnl': bal1 - bal0, 'final': bal1,
        'reasons': reasons, 'monthly': monthly,
        'trades': trades
    }


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    results = {}

    for pair in ['EURUSD', 'GBPJPY', 'USDJPY']:
        print(f'\nLoading {pair}...')
        m15 = load_forex(pair)
        idx = m15.set_index('time')
        h1 = idx.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna().reset_index()
        h4 = idx.resample('4h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna().reset_index()
        print(f'  {len(m15)} M15 | {len(h1)} H1 | {len(h4)} H4 bars')
        print(f'  {m15.time.iloc[0].date()} → {m15.time.iloc[-1].date()}')
        trades, bal = simulate(pair, m15, h1, h4)
        results[pair] = metrics(trades, INITIAL_BALANCE, bal)

    print('\nLoading XAUUSD...')
    xm15 = load_xauusd('M15')
    xh1  = load_xauusd('H1')
    xh4  = load_xauusd('H4')
    print(f'  {len(xm15)} M15 | {len(xh1)} H1 | {len(xh4)} H4 bars')
    print(f'  {xm15.time.iloc[0].date()} → {xm15.time.iloc[-1].date()}')
    trades_x, bal_x = simulate('XAUUSD', xm15, xh1, xh4)
    results['XAUUSD'] = metrics(trades_x, INITIAL_BALANCE, bal_x)

    # Save to JSON
    save = {}
    for pair, m in results.items():
        if m is None: continue
        save[pair] = {k: v for k, v in m.items() if k != 'trades'}
    with open('/home/user/Trading-bot/kzc_results_100.json', 'w') as f:
        json.dump(save, f, indent=2, default=str)

    # ── Collect all trades ────────────────────────────────────────────────────
    all_trades = []
    for m in results.values():
        if m: all_trades.extend(m['trades'])
    all_trades.sort(key=lambda t: t.entry_time)

    # ── Monthly breakdown (all pairs combined) ────────────────────────────────
    monthly_data = {}
    for t in all_trades:
        k = t.entry_time.strftime('%Y-%m')
        if k not in monthly_data: monthly_data[k] = {'trades': 0, 'wins': 0, 'r': 0.0}
        monthly_data[k]['trades'] += 1
        monthly_data[k]['wins']   += 1 if t.r_multiple > 0 else 0
        monthly_data[k]['r']      += t.r_multiple

    # Monthly PnL in $ (using 1% of $100 = $1/R at start, but compounded)
    # Recompute with actual compounded balance per month
    monthly_pnl = {}
    running = INITIAL_BALANCE
    for t in all_trades:
        k = t.entry_time.strftime('%Y-%m')
        if k not in monthly_pnl: monthly_pnl[k] = 0.0
        monthly_pnl[k] += t.pnl

    # ── PRINT RESULTS ─────────────────────────────────────────────────────────
    print('\n' + '='*65)
    print(f'  KZC BACKTEST — Capital $100 | Risque 1%/trade')
    print(f'  Breakeven activé : OUI (SL → entrée après TP1)')
    print('='*65)

    for pair, m in results.items():
        if not m:
            print(f'\n  {pair}: aucun trade généré')
            continue
        n_months = len(set(t.entry_time.strftime('%Y-%m') for t in m['trades']))
        avg_monthly_r   = m['total_r'] / max(n_months, 1)
        avg_monthly_pnl = m['net_pnl'] / max(n_months, 1)
        print(f'\n  ── {pair} ──')
        print(f'  Trades          : {m["n"]} ({m["n"]//max(n_months,1):.0f}/mois)')
        print(f'  Win Rate        : {m["wr"]:.1f}%')
        print(f'  Profit Factor   : {m["pf"]:.2f}')
        print(f'  Total R         : {m["total_r"]:+.1f}R  ({avg_monthly_r:+.1f}R/mois)')
        print(f'  ROI             : {m["roi"]:+.1f}%')
        print(f'  PnL net         : ${m["net_pnl"]:+.2f}  (~${avg_monthly_pnl:+.2f}/mois)')
        print(f'  Balance finale  : ${m["final"]:.2f}')
        print(f'  Max Drawdown    : {m["max_dd_pct"]:.1f}% (${m["max_dd_usd"]:.2f})')
        print(f'  Sharpe / Sortino: {m["sharpe"]:.2f} / {m["sortino"]:.2f}')
        print(f'  Sorties BE      : {m["reasons"].get("sl_be", 0)} trades sauvés par breakeven')

    # ── Portfolio mensuel ──────────────────────────────────────────────────────
    print(f'\n{"="*65}')
    print('  DÉCOMPOSITION MENSUELLE — PORTEFEUILLE COMPLET')
    print(f'  {"Mois":<10} {"Trades":>7} {"WR":>7} {"R":>8} {"PnL $":>10} {"Cumul $":>10}')
    print(f'  {"─"*58}')
    cumul = INITIAL_BALANCE
    monthly_rs = []
    for k in sorted(monthly_data.keys()):
        d = monthly_data[k]
        wr = d['wins'] / d['trades'] * 100 if d['trades'] else 0
        pnl = monthly_pnl.get(k, 0)
        cumul += pnl
        monthly_rs.append(d['r'])
        flag = '✅' if pnl >= 0 else '❌'
        print(f'  {k:<10} {d["trades"]:>7} {wr:>6.0f}% {d["r"]:>+8.1f}R {pnl:>+9.2f}$ {cumul:>9.2f}$ {flag}')

    avg_r   = np.mean(monthly_rs)
    pos_m   = sum(1 for r in monthly_rs if r > 0)
    neg_m   = sum(1 for r in monthly_rs if r <= 0)
    best_m  = max(monthly_rs)
    worst_m = min(monthly_rs)

    print(f'\n  Mois gagnants   : {pos_m} / {len(monthly_rs)}')
    print(f'  Mois perdants   : {neg_m} / {len(monthly_rs)}')
    print(f'  Meilleur mois   : +{best_m:.1f}R')
    print(f'  Pire mois       : {worst_m:.1f}R')
    print(f'  Moy. R/mois     : {avg_r:+.1f}R')

    # ── Objectif $250/mois ─────────────────────────────────────────────────────
    print(f'\n{"="*65}')
    print('  ANALYSE : OBJECTIF $250/MOIS')
    print(f'{"="*65}')
    avg_monthly_pnl_total = sum(monthly_pnl.values()) / max(len(monthly_pnl), 1)
    print(f'\n  Avec $100 et 1% risque :')
    print(f'  → Gain moyen réel/mois  : ${avg_monthly_pnl_total:+.2f}')
    print(f'  → Pour atteindre $250/mois avec cette stratégie :')

    for risk in [0.01, 0.02, 0.05, 0.10, 0.15, 0.20]:
        factor = risk / 0.01
        proj   = avg_monthly_pnl_total * factor
        note   = ''
        if risk <= 0.02: note = '✅ Sûr'
        elif risk <= 0.05: note = '⚠️  Risqué'
        else: note = '❌ Dangereux'
        print(f'  Risque {risk*100:.0f}%/trade → ~${proj:+.2f}/mois  {note}')

    # Capital minimum nécessaire pour $250/mois à 1-2% risque
    cap_1pct = 250 / (avg_r * 0.01) if avg_r > 0 else float('inf')
    cap_2pct = 250 / (avg_r * 0.02) if avg_r > 0 else float('inf')
    print(f'\n  Capital minimum pour $250/mois en toute sécurité :')
    print(f'  → À 1% risque/trade : ${cap_1pct:,.0f}')
    print(f'  → À 2% risque/trade : ${cap_2pct:,.0f}')
    print(f'\n  ⚠️  Avec $100, la stratégie rapporte ~${avg_monthly_pnl_total:.2f}/mois.')
    print(f'  Pour $250/mois il faut soit augmenter le capital,')
    print(f'  soit accepter un risque élevé (compte grillé probable).')
    print('='*65)

if __name__ == '__main__':
    main()
