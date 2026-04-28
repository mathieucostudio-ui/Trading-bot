//+------------------------------------------------------------------+
//|                         KZC_EA.mq5                               |
//|              Kill Zone Confluence Expert Advisor                  |
//|   Stratégie : Dow Theory H4 + BOS H1 + FVG M15 + Kill Zones     |
//|   Paramètres optimaux issus du backtest (2022-2026)              |
//|   EURUSD : Sharpe 1.36 | GBPJPY : 0.80 | USDJPY : 1.03         |
//+------------------------------------------------------------------+
#property copyright "KZC Strategy — v1.0"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//════════════════════════════════════════════════════════════════════
//  PARAMÈTRES D'ENTRÉE
//════════════════════════════════════════════════════════════════════

input group "══ GESTION DU RISQUE ══"
input double InpRiskPct        = 1.0;   // Risque par trade (% du capital)
input double InpTP1_R          = 1.5;   // TP1 en multiple de R (ferme 50%)
input double InpTP2_R          = 2.5;   // TP2 en multiple de R (ferme 50%)
input bool   InpBreakeven      = true;  // Activer breakeven après TP1
input int    InpMaxConcurrent  = 2;     // Nombre de trades max simultanés

input group "══ FILTRES STRATÉGIE ══"
input int    InpMinScore       = 5;     // Score de confluence minimum (sur 6)
input int    InpSL_MinPips     = 8;     // SL minimum en pips
input int    InpSL_MaxPips     = 40;    // SL maximum en pips
input int    InpH4_SwingBars   = 2;     // Bougies de confirmation swing H4
input int    InpFVG_Lookback   = 8;     // Bougies M15 pour chercher FVG
input int    InpZone_H1_Bars   = 16;    // Bougies H1 pour calculer zone S&D
input double InpZone_Threshold = 0.35;  // Seuil zone S&D (35% de la range)
input double InpMarobozu_Ratio = 0.70;  // Ratio corps/range pour marobozu

input group "══ SESSIONS (heure broker) ══"
input int    InpLondonStart    = 7;     // London Kill Zone — début
input int    InpLondonEnd      = 10;    // London Kill Zone — fin
input int    InpNYStart        = 13;    // New York Kill Zone — début
input int    InpNYEnd          = 16;    // New York Kill Zone — fin
input int    InpHardClose      = 16;    // Fermeture forcée (heure broker)
input int    InpNoNewEntry     = 15;    // Pas de nouvelle entrée après cette heure

input group "══ PARAMÈTRES AVANCÉS ══"
input long   InpMagic          = 202401; // Magic number (unique par EA)
input int    InpSlippage       = 10;     // Slippage max (points)
input bool   InpVerbose        = true;   // Afficher les logs détaillés

//════════════════════════════════════════════════════════════════════
//  STRUCTURES & VARIABLES GLOBALES
//════════════════════════════════════════════════════════════════════

struct TradeState
{
    ulong  ticket;
    int    direction;     // +1 long, -1 short
    double entry;
    double sl_original;   // SL initial (pour recalcul TP1 après restart)
    double sl_dist;       // Distance SL en prix
    double tp1;
    double tp2;
    bool   tp1_hit;
    bool   be_active;
    datetime open_time;
};

CTrade        g_trade;
CPositionInfo g_pos;

TradeState    g_states[20];
int           g_state_count = 0;
datetime      g_last_bar    = 0;

//════════════════════════════════════════════════════════════════════
//  INIT / DEINIT
//════════════════════════════════════════════════════════════════════

int OnInit()
{
    g_trade.SetExpertMagicNumber(InpMagic);
    g_trade.SetDeviationInPoints(InpSlippage);
    g_trade.SetTypeFilling(ORDER_FILLING_IOC);

    // Récupérer les positions existantes (si EA redémarré)
    RecoverExistingPositions();

    Print("══ KZC EA v1.0 initialisé ══");
    Print("Paire: ", _Symbol, " | Risque: ", InpRiskPct, "% | TP1: ", InpTP1_R,
          "R | TP2: ", InpTP2_R, "R | Score min: ", InpMinScore, "/6");
    return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
    Print("KZC EA arrêté. Code: ", reason);
}

//════════════════════════════════════════════════════════════════════
//  TICK PRINCIPAL
//════════════════════════════════════════════════════════════════════

void OnTick()
{
    // Gérer les positions à chaque tick (BE, hard close)
    ManagePositions();

    // Limiter la logique d'entrée à une fois par bougie M15 fermée
    datetime current_bar = iTime(_Symbol, PERIOD_M15, 0);
    if(current_bar == g_last_bar) return;
    g_last_bar = current_bar;

    // ── Vérifications temporelles ─────────────────────────────────
    MqlDateTime dt;
    TimeToStruct(TimeCurrent(), dt);
    int hour = dt.hour;

    if(!IsKillZone(hour))          return;
    if(hour >= InpNoNewEntry)      return;
    if(CountMyTrades() >= InpMaxConcurrent) return;

    // ── Calcul du score de confluence ─────────────────────────────
    int trend = GetH4Trend();
    if(trend == 0) return;

    int  bos       = GetH1BOS();
    bool at_zone   = IsAtZone(trend);
    bool has_fvg   = HasFVG(trend);
    bool entry_cnd = IsEntryCandle(trend);

    // Score : trend(1) + KillZone(1) + BOS(1) + Zone(1) + FVG(1) + Candle(1)
    int score = 2;                        // trend + KZ toujours actifs
    if(bos == trend)  score++;
    if(at_zone)       score++;
    if(has_fvg)       score++;
    if(entry_cnd)     score++;

    if(InpVerbose)
        Print("Analyse | Trend:", trend, " BOS:", bos, " Zone:", at_zone,
              " FVG:", has_fvg, " Candle:", entry_cnd, " → Score:", score, "/6");

    if(score < InpMinScore) return;

    // ── Calcul SL / TP ────────────────────────────────────────────
    double bar_high  = iHigh (_Symbol, PERIOD_M15, 1);
    double bar_low   = iLow  (_Symbol, PERIOD_M15, 1);
    double bar_close = iClose(_Symbol, PERIOD_M15, 1);
    double buffer    = (bar_high - bar_low) * 0.10;
    double pip       = GetPipSize();

    double sl_price_raw, sl_dist;
    if(trend == 1) {
        sl_price_raw = bar_low - buffer;
        sl_dist      = bar_close - sl_price_raw;
    } else {
        sl_price_raw = bar_high + buffer;
        sl_dist      = sl_price_raw - bar_close;
    }

    double sl_pips = sl_dist / pip;
    if(sl_pips < InpSL_MinPips || sl_pips > InpSL_MaxPips) {
        if(InpVerbose)
            Print("Signal rejeté — SL hors limites: ", DoubleToString(sl_pips, 1),
                  " pips (min:", InpSL_MinPips, " max:", InpSL_MaxPips, ")");
        return;
    }

    // Prix d'entrée réel (bid/ask courant)
    double entry = (trend == 1) ? SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                                : SymbolInfoDouble(_Symbol, SYMBOL_BID);

    // SL/TP ajustés par rapport au prix d'entrée réel
    double sl_adj  = NormalizeDouble(trend == 1 ? entry - sl_dist : entry + sl_dist, _Digits);
    double tp1_adj = NormalizeDouble(trend == 1 ? entry + InpTP1_R * sl_dist
                                                : entry - InpTP1_R * sl_dist, _Digits);
    double tp2_adj = NormalizeDouble(trend == 1 ? entry + InpTP2_R * sl_dist
                                                : entry - InpTP2_R * sl_dist, _Digits);

    // Validation finale des niveaux
    if(!ValidateLevels(trend, entry, sl_adj, tp2_adj)) return;

    // Taille de position
    double lot = CalcLotSize(sl_dist);
    if(lot <= 0) { Print("Erreur calcul lot"); return; }

    // Commentaire : encode direction + SL original pour récupération
    string comment = StringFormat("KZC_%s_%.5f_%d",
                                  trend == 1 ? "L" : "S",
                                  sl_adj,
                                  score);

    // ── Ouverture du trade ────────────────────────────────────────
    bool ok = (trend == 1) ? g_trade.Buy (lot, _Symbol, 0, sl_adj, tp2_adj, comment)
                           : g_trade.Sell(lot, _Symbol, 0, sl_adj, tp2_adj, comment);

    if(ok) {
        ulong ticket = g_trade.ResultOrder();
        AddState(ticket, trend, entry, sl_adj, sl_dist, tp1_adj, tp2_adj);
        Print("✅ Trade ouvert | ", comment, " | Lot:", lot,
              " | Entry:", entry, " | SL:", sl_adj,
              " | TP1:", tp1_adj, " | TP2:", tp2_adj,
              " | SL:", DoubleToString(sl_pips, 1), "pips");
    } else {
        Print("❌ Erreur ouverture: ", g_trade.ResultRetcodeDescription(),
              " (", g_trade.ResultRetcode(), ")");
    }
}

//════════════════════════════════════════════════════════════════════
//  GESTION DES POSITIONS OUVERTES
//════════════════════════════════════════════════════════════════════

void ManagePositions()
{
    MqlDateTime dt;
    TimeToStruct(TimeCurrent(), dt);
    bool hard_close = (dt.hour >= InpHardClose);

    for(int i = g_state_count - 1; i >= 0; i--)
    {
        TradeState &s = g_states[i];

        if(!PositionSelectByTicket(s.ticket)) {
            RemoveState(i);
            continue;
        }

        double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
        double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
        double price = (s.direction == 1) ? bid : ask;

        // ── Fermeture forcée fin de journée ──────────────────────
        if(hard_close) {
            if(g_trade.PositionClose(s.ticket, InpSlippage))
                Print("⏰ Hard close | ticket:", s.ticket, " | heure:", dt.hour, "h");
            RemoveState(i);
            continue;
        }

        // ── Gestion TP1 → ferme 50% + breakeven ──────────────────
        if(!s.tp1_hit) {
            bool tp1_reached = (s.direction == 1) ? (bid >= s.tp1) : (ask <= s.tp1);

            if(tp1_reached) {
                double vol = PositionGetDouble(POSITION_VOLUME);
                double close_vol = NormalizeVolume(vol / 2.0);

                if(close_vol > 0 && g_trade.PositionClosePartial(s.ticket, close_vol)) {
                    s.tp1_hit = true;
                    Print("🎯 TP1 atteint | 50% fermé @ ", s.tp1,
                          " | ticket:", s.ticket);

                    // Breakeven : SL → prix d'entrée
                    if(InpBreakeven && PositionSelectByTicket(s.ticket)) {
                        double be_sl = NormalizeDouble(s.entry, _Digits);
                        if(g_trade.PositionModify(s.ticket, be_sl, s.tp2)) {
                            s.be_active = true;
                            s.sl_original = be_sl;
                            Print("🔒 Breakeven activé | SL → ", be_sl);
                        }
                    }
                }
            }
        }
    }
}

//════════════════════════════════════════════════════════════════════
//  INDICATEURS — LOGIQUE STRATÉGIE
//════════════════════════════════════════════════════════════════════

//──────────────────────────────────────────────────────────────────
// H4 Trend : Théorie de Dow (HH+HL = haussier, LH+LL = baissier)
//──────────────────────────────────────────────────────────────────
int GetH4Trend()
{
    int  n     = InpH4_SwingBars;
    int  bars  = 80;
    bool enough_sh = false, enough_sl = false;
    double sh[4]; int sh_n = 0;
    double sl_arr[4]; int sl_n = 0;

    for(int i = n + 2; i < bars && (sh_n < 4 || sl_n < 4); i++)
    {
        // Swing High confirmé (n bougies de chaque côté)
        if(sh_n < 4) {
            double h = iHigh(_Symbol, PERIOD_H4, i);
            bool is_sh = true;
            for(int k = 1; k <= n && is_sh; k++) {
                if(iHigh(_Symbol, PERIOD_H4, i - k) >= h) is_sh = false;
                if(iHigh(_Symbol, PERIOD_H4, i + k) >= h) is_sh = false;
            }
            if(is_sh) sh[sh_n++] = h;
        }

        // Swing Low confirmé
        if(sl_n < 4) {
            double l = iLow(_Symbol, PERIOD_H4, i);
            bool is_sl = true;
            for(int k = 1; k <= n && is_sl; k++) {
                if(iLow(_Symbol, PERIOD_H4, i - k) <= l) is_sl = false;
                if(iLow(_Symbol, PERIOD_H4, i + k) <= l) is_sl = false;
            }
            if(is_sl) sl_arr[sl_n++] = l;
        }
    }

    if(sh_n < 2 || sl_n < 2) return 0;

    // sh[0] = swing high le plus récent (shift le plus petit)
    bool hh = sh[0]     > sh[1];      // Higher High
    bool hl = sl_arr[0] > sl_arr[1];  // Higher Low
    bool lh = sh[0]     < sh[1];      // Lower High
    bool ll = sl_arr[0] < sl_arr[1];  // Lower Low

    if(hh && hl) return  1;   // Tendance haussière
    if(lh && ll) return -1;   // Tendance baissière
    return 0;                  // Range / indécis
}

//──────────────────────────────────────────────────────────────────
// H1 BOS : Break of Structure
//──────────────────────────────────────────────────────────────────
int GetH1BOS()
{
    double last_sh = 0, last_sl = DBL_MAX;

    for(int i = 4; i < 50; i++)
    {
        if(last_sh == 0) {
            double h = iHigh(_Symbol, PERIOD_H1, i);
            if(iHigh(_Symbol, PERIOD_H1, i-1) < h && iHigh(_Symbol, PERIOD_H1, i-2) < h &&
               iHigh(_Symbol, PERIOD_H1, i+1) < h && iHigh(_Symbol, PERIOD_H1, i+2) < h)
                last_sh = h;
        }
        if(last_sl == DBL_MAX) {
            double l = iLow(_Symbol, PERIOD_H1, i);
            if(iLow(_Symbol, PERIOD_H1, i-1) > l && iLow(_Symbol, PERIOD_H1, i-2) > l &&
               iLow(_Symbol, PERIOD_H1, i+1) > l && iLow(_Symbol, PERIOD_H1, i+2) > l)
                last_sl = l;
        }
        if(last_sh > 0 && last_sl < DBL_MAX) break;
    }

    double close = iClose(_Symbol, PERIOD_H1, 1);
    if(last_sh > 0 && close > last_sh) return  1;
    if(last_sl < DBL_MAX && close < last_sl) return -1;
    return 0;
}

//──────────────────────────────────────────────────────────────────
// Zone S&D : prix dans bas/haut 35% de la range des 16 dernières H1
//──────────────────────────────────────────────────────────────────
bool IsAtZone(int direction)
{
    int idx_h = iHighest(_Symbol, PERIOD_H1, MODE_HIGH, InpZone_H1_Bars, 1);
    int idx_l = iLowest (_Symbol, PERIOD_H1, MODE_LOW,  InpZone_H1_Bars, 1);
    double rh = iHigh(_Symbol, PERIOD_H1, idx_h);
    double rl = iLow (_Symbol, PERIOD_H1, idx_l);
    double rr = rh - rl;
    if(rr <= 0) return false;

    double price = iClose(_Symbol, PERIOD_M15, 1);
    double threshold = InpZone_Threshold;

    if(direction ==  1) return (price <= rl + threshold * rr);  // Demand zone (bas)
    if(direction == -1) return (price >= rh - threshold * rr);  // Supply zone (haut)
    return false;
}

//──────────────────────────────────────────────────────────────────
// FVG (Fair Value Gap / Imbalance) sur M15
// Bullish FVG : low[i] > high[i+2]  |  Bearish FVG : high[i] < low[i+2]
//──────────────────────────────────────────────────────────────────
bool HasFVG(int direction)
{
    for(int i = 1; i <= InpFVG_Lookback; i++)
    {
        double h_i   = iHigh(_Symbol, PERIOD_M15, i);
        double l_i   = iLow (_Symbol, PERIOD_M15, i);
        double h_i2  = iHigh(_Symbol, PERIOD_M15, i + 2);
        double l_i2  = iLow (_Symbol, PERIOD_M15, i + 2);

        if(direction ==  1 && l_i > h_i2) return true;  // Bullish FVG
        if(direction == -1 && h_i < l_i2) return true;  // Bearish FVG
    }
    return false;
}

//──────────────────────────────────────────────────────────────────
// Bougie d'entrée : Englobante haussière/baissière OU Marobozu
//──────────────────────────────────────────────────────────────────
bool IsEntryCandle(int direction)
{
    double o1 = iOpen (_Symbol, PERIOD_M15, 1);
    double h1 = iHigh (_Symbol, PERIOD_M15, 1);
    double l1 = iLow  (_Symbol, PERIOD_M15, 1);
    double c1 = iClose(_Symbol, PERIOD_M15, 1);
    double o2 = iOpen (_Symbol, PERIOD_M15, 2);
    double c2 = iClose(_Symbol, PERIOD_M15, 2);

    double body  = MathAbs(c1 - o1);
    double range = h1 - l1;
    double pbody = MathAbs(c2 - o2);
    if(range <= 0) return false;

    if(direction == 1) {
        bool engulf   = c1 > o1 && c1 > o2 && o1 < c2 && body > pbody;
        bool marobozu = c1 > o1 && body / range >= InpMarobozu_Ratio;
        return engulf || marobozu;
    } else {
        bool engulf   = c1 < o1 && c1 < o2 && o1 > c2 && body > pbody;
        bool marobozu = c1 < o1 && body / range >= InpMarobozu_Ratio;
        return engulf || marobozu;
    }
}

//──────────────────────────────────────────────────────────────────
// Kill Zone actif ?
//──────────────────────────────────────────────────────────────────
bool IsKillZone(int hour)
{
    return (hour >= InpLondonStart && hour < InpLondonEnd) ||
           (hour >= InpNYStart     && hour < InpNYEnd);
}

//════════════════════════════════════════════════════════════════════
//  UTILITAIRES
//════════════════════════════════════════════════════════════════════

//── Taille de position (1% du capital risqué sur sl_dist) ──────────
double CalcLotSize(double sl_dist)
{
    if(sl_dist <= 0) return 0;
    double balance       = AccountInfoDouble(ACCOUNT_BALANCE);
    double risk_usd      = balance * InpRiskPct / 100.0;
    double tick_val      = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
    double tick_size     = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
    if(tick_val <= 0 || tick_size <= 0) return 0;
    double val_per_lot   = (sl_dist / tick_size) * tick_val;
    if(val_per_lot <= 0) return 0;
    double lot = risk_usd / val_per_lot;
    return NormalizeVolume(lot);
}

//── Normaliser un volume aux contraintes du broker ─────────────────
double NormalizeVolume(double vol)
{
    double lot_min  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
    double lot_max  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
    double lot_step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
    if(lot_step <= 0) lot_step = 0.01;
    vol = MathFloor(vol / lot_step) * lot_step;
    return MathMax(lot_min, MathMin(lot_max, vol));
}

//── Taille d'un pip (gère les 3, 4, 5 décimales) ───────────────────
double GetPipSize()
{
    int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
    if(digits == 3 || digits == 5) return _Point * 10.0;
    return _Point;
}

//── Validation des niveaux SL/TP ───────────────────────────────────
bool ValidateLevels(int direction, double entry, double sl, double tp)
{
    double stops_level = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
    if(direction == 1) {
        if(entry - sl < stops_level || tp - entry < stops_level) {
            if(InpVerbose) Print("Niveaux SL/TP trop proches du prix courant");
            return false;
        }
    } else {
        if(sl - entry < stops_level || entry - tp < stops_level) {
            if(InpVerbose) Print("Niveaux SL/TP trop proches du prix courant");
            return false;
        }
    }
    return true;
}

//── Compter nos trades ouverts ──────────────────────────────────────
int CountMyTrades()
{
    int count = 0;
    for(int i = 0; i < PositionsTotal(); i++) {
        if(PositionGetTicket(i) > 0 &&
           (long)PositionGetInteger(POSITION_MAGIC) == InpMagic &&
           PositionGetString(POSITION_SYMBOL) == _Symbol)
            count++;
    }
    return count;
}

//── Ajouter un état ─────────────────────────────────────────────────
void AddState(ulong ticket, int dir, double entry, double sl,
              double sl_dist, double tp1, double tp2)
{
    if(g_state_count >= 20) return;
    TradeState &s = g_states[g_state_count];
    s.ticket      = ticket;
    s.direction   = dir;
    s.entry       = entry;
    s.sl_original = sl;
    s.sl_dist     = sl_dist;
    s.tp1         = tp1;
    s.tp2         = tp2;
    s.tp1_hit     = false;
    s.be_active   = false;
    s.open_time   = TimeCurrent();
    g_state_count++;
}

//── Supprimer un état ───────────────────────────────────────────────
void RemoveState(int idx)
{
    for(int i = idx; i < g_state_count - 1; i++)
        g_states[i] = g_states[i + 1];
    g_state_count--;
}

//── Récupérer les positions existantes au démarrage de l'EA ─────────
void RecoverExistingPositions()
{
    g_state_count = 0;
    for(int i = 0; i < PositionsTotal(); i++)
    {
        ulong ticket = PositionGetTicket(i);
        if(ticket == 0) continue;
        if((long)PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
        if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;

        // Parser le commentaire : "KZC_L_1.08500_5" ou "KZC_S_1.08020_5"
        string comment = PositionGetString(POSITION_COMMENT);
        int    dir     = StringFind(comment, "KZC_L") >= 0 ? 1 : -1;
        double entry   = PositionGetDouble(POSITION_PRICE_OPEN);
        double current_sl = PositionGetDouble(POSITION_SL);
        double tp2     = PositionGetDouble(POSITION_TP);

        // Retrouver le SL original depuis le commentaire ("KZC_L_1.08500_5")
        double sl_orig = current_sl;
        string parts[];
        StringSplit(comment, '_', parts);
        if(ArraySize(parts) >= 3)
            sl_orig = StringToDouble(parts[2]);

        double sl_dist = (dir == 1) ? entry - sl_orig : sl_orig - entry;
        if(sl_dist <= 0) sl_dist = GetPipSize() * InpSL_MinPips;

        double tp1 = (dir == 1) ? entry + InpTP1_R * sl_dist
                                : entry - InpTP1_R * sl_dist;

        // TP1 déjà touché si SL ≈ entry (breakeven actif)
        bool tp1_hit = (MathAbs(current_sl - entry) < GetPipSize() * 2);

        AddState(ticket, dir, entry, sl_orig, sl_dist, tp1, tp2);
        g_states[g_state_count - 1].tp1_hit  = tp1_hit;
        g_states[g_state_count - 1].be_active = tp1_hit;

        Print("Position récupérée | ticket:", ticket, " dir:", dir,
              " tp1_hit:", tp1_hit, " entry:", entry);
    }
    if(g_state_count > 0)
        Print(g_state_count, " position(s) KZC récupérée(s)");
}

//+------------------------------------------------------------------+
