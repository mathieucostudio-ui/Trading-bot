# DOCUMENT TECHNIQUE — STRATÉGIE KZC
## Kill Zone Confluence (KZC)
### Trading Intraday · Petit Capital · Paires Majeures

---

**Version** : 1.0  
**Date** : Mai 2026  
**Auteur** : Développé par analyse quantitative sur données 2022–2026  
**Statut** : Validé par backtest · Implémenté en Expert Advisor MT5

---

## TABLE DES MATIÈRES

1. [Philosophie et Fondements](#1-philosophie-et-fondements)
2. [Instruments et Sessions](#2-instruments-et-sessions)
3. [Architecture Multi-Timeframes](#3-architecture-multi-timeframes)
4. [Les 6 Conditions de Confluence](#4-les-6-conditions-de-confluence)
5. [Règles d'Entrée](#5-règles-dentrée)
6. [Gestion du Trade](#6-gestion-du-trade)
7. [Gestion du Risque](#7-gestion-du-risque)
8. [Résultats du Backtest](#8-résultats-du-backtest)
9. [Implémentation MT5](#9-implémentation-mt5)
10. [FAQ et Cas Particuliers](#10-faq-et-cas-particuliers)

---

## 1. PHILOSOPHIE ET FONDEMENTS

### 1.1 Principe Directeur

La stratégie KZC repose sur un principe simple : **ne trader que lorsque plusieurs facteurs s'alignent simultanément**, pendant une fenêtre temporelle précise où la liquidité est maximale.

Elle combine trois couches d'analyse :

| Couche | Rôle | Timeframe |
|--------|------|-----------|
| **Macro** | Direction du marché (biais) | H4 |
| **Tactique** | Structure et zones clés | H1 |
| **Exécution** | Signal précis d'entrée | M15 |

### 1.2 Bases Théoriques

La stratégie s'appuie sur quatre concepts éprouvés :

**1. La Théorie de Dow**
Le marché évolue en séquences de sommets et creux successifs. Une tendance haussière est définie par des hauts de plus en plus hauts (HH) et des bas de plus en plus hauts (HL). Une tendance baissière par des hauts de plus en plus bas (LH) et des bas de plus en plus bas (LL). Toute autre configuration est considérée comme un range et doit être ignorée.

**2. Le Break of Structure (BOS)**
Un BOS se produit lorsque le prix casse au-dessus du dernier sommet significatif (BOS haussier) ou en dessous du dernier creux significatif (BOS baissier) sur H1. Il confirme que la structure de marché à court terme s'aligne avec le biais H4.

**3. Les Zones d'Offre et de Demande (S&D)**
Les zones d'offre et de demande représentent des niveaux de prix où les acheteurs institutionnels ou vendeurs institutionnels ont manifesté un intérêt fort par le passé. En tendance haussière, on cherche à acheter dans une zone de demande (support). En tendance baissière, on cherche à vendre dans une zone d'offre (résistance).

**4. Le Fair Value Gap (FVG) / Imbalance**
Un FVG est un déséquilibre de prix sur trois bougies consécutives : il existe un espace (gap) entre le bas de la bougie 1 et le haut de la bougie 3 (FVG haussier), ou entre le haut de la bougie 1 et le bas de la bougie 3 (FVG baissier). Ces zones d'inefficacité ont une forte probabilité d'être comblées, offrant des opportunités d'entrée précises.

### 1.3 Pourquoi l'Analyse Technique Pure ?

- **Égalité d'accès** : Tous les traders voient les mêmes graphiques, contrairement à l'analyse fondamentale où les institutions disposent d'un avantage informationnel (Bloomberg Terminal, flux privés).
- **Quantifiable et testable** : Les règles peuvent être backtestées sur des années de données, permettant de valider statistiquement l'edge.
- **Reproductible** : Les mêmes conditions produisent les mêmes signaux, sans interprétation subjective.

---

## 2. INSTRUMENTS ET SESSIONS

### 2.1 Paires Tradées

| Paire | Type | Classement | Risque recommandé |
|-------|------|-----------|-------------------|
| **EURUSD** | Majeure | ⭐⭐⭐ Priorité 1 | 1% |
| **USDJPY** | Majeure | ⭐⭐ Priorité 2 | 1% |
| **GBPJPY** | Croisée | ⭐ Priorité 3 | 0.5% (plus volatile) |

> **XAUUSD (Or)** : Non recommandé avec cette stratégie dans sa version actuelle. Les Kill Zones Forex ne correspondent pas aux fenêtres optimales de l'or.

### 2.2 Kill Zones — Le Cœur de la Stratégie

Les **Kill Zones** sont des fenêtres temporelles durant lesquelles les institutions financières entrent massivement sur le marché, créant des mouvements directionnels nets et prévisibles. Ce sont les seuls moments où l'EA est autorisé à ouvrir des trades.

```
┌─────────────────────────────────────────────────────────┐
│                    CALENDRIER JOURNALIER                  │
├──────────────┬──────────────┬──────────────┬────────────┤
│  00h - 07h   │  07h - 10h   │  10h - 13h   │  13h - 16h │
│  Asie/Nuit   │  LONDON KZ   │  Zone Morte  │   NY KZ    │
│  ❌ Fermé    │  ✅ Trading  │  ❌ Fermé    │  ✅ Trading │
├──────────────┴──────────────┴──────────────┴────────────┤
│  16h00 : FERMETURE FORCÉE DE TOUTES LES POSITIONS       │
│  Objectif : Aucun trade ouvert après 18h00              │
└─────────────────────────────────────────────────────────┘
```

**Heure de référence** : Heure broker (généralement UTC+2 ou UTC+3 selon le broker).

| Session | Heure Broker | Caractéristiques |
|---------|-------------|-----------------|
| **London Kill Zone** | 07:00 – 10:00 | Ouverture européenne. Fort volume sur EUR/GBP. Mouvements directionnels puissants. |
| **New York Kill Zone** | 13:00 – 16:00 | Chevauchement Londres/NY. Liquidité maximale de la journée. Idéal pour USD. |
| **Zone Morte** | 10:00 – 13:00 | Consolidation, spreads élargis. Aucune entrée autorisée. |
| **Fermeture Forcée** | 16:00 | Toutes positions fermées. Garantit le caractère intraday. |

---

## 3. ARCHITECTURE MULTI-TIMEFRAMES

La stratégie utilise **3 niveaux d'analyse imbriqués**. Chaque niveau a un rôle précis et doit être cohérent avec les autres avant qu'une entrée soit envisagée.

```
H4 (Biais)
    │
    ▼
   Tendance confirmée ?
    │
    ├── OUI ──► H1 (Structure)
    │               │
    │               ▼
    │          BOS + Zone S&D validés ?
    │               │
    │               ├── OUI ──► M15 (Exécution)
    │               │               │
    │               │               ▼
    │               │          FVG + Bougie + Kill Zone ?
    │               │               │
    │               │               └── ENTRÉE ✅
    │               │
    │               └── NON ──► ATTENDRE
    │
    └── NON ──► PAS DE TRADE ❌
```

### 3.1 Niveau H4 — Le Biais Directionnel

**Objectif** : Déterminer si le marché est en tendance haussière, baissière ou en range.

**Méthode** : Théorie de Dow appliquée aux points pivots H4.

Un **swing high** est identifié lorsqu'une bougie H4 présente un haut supérieur aux 2 bougies précédentes ET aux 2 bougies suivantes (confirmation 2 bougies).

Un **swing low** est identifié lorsqu'une bougie H4 présente un bas inférieur aux 2 bougies précédentes ET aux 2 bougies suivantes.

```
Tendance HAUSSIÈRE (biais = +1) :
  Swing High 2 > Swing High 1  (HH)
  Swing Low 2  > Swing Low 1   (HL)
  ✅ On cherche des ACHATS uniquement

Tendance BAISSIÈRE (biais = -1) :
  Swing High 2 < Swing High 1  (LH)
  Swing Low 2  < Swing Low 1   (LL)
  ✅ On cherche des VENTES uniquement

RANGE (biais = 0) :
  Critères Dow non remplis
  ❌ AUCUN TRADE
```

### 3.2 Niveau H1 — La Structure de Marché

**Objectif** : Confirmer que la structure à court terme s'aligne avec le biais H4 et identifier la zone d'intérêt.

**Break of Structure (BOS)**

Le BOS est détecté lorsque la clôture d'une bougie H1 dépasse le dernier swing high (BOS haussier) ou passe sous le dernier swing low (BOS baissier).

```
Exemple BOS Haussier :
                      ★ BOS ici
    ___________      /
   |  Swing H  |----/----► Clôture H1 > Dernier Swing High
   |___________|

Exemple BOS Baissier :
   ___________
  |  Swing L  |----\----► Clôture H1 < Dernier Swing Low
  |___________|      \
                      ★ BOS ici
```

**Zone S&D (Offre et Demande)**

La zone est calculée à partir des 16 dernières bougies H1 :
- Range = Max(16 H1 hauts) - Min(16 H1 bas)
- **Zone de Demande** (pour les achats) : prix dans les 35% inférieurs du range
- **Zone d'Offre** (pour les ventes) : prix dans les 35% supérieurs du range

```
100% ┬────────────────────── Max H1 (16 bougies)
     │
 65% ┼ - - - - - - - - - - - Seuil zone d'offre
     │  ← ZONE D'OFFRE
 35% ┼ - - - - - - - - - - - Seuil zone de demande
     │  ← ZONE DE DEMANDE
  0% ┴────────────────────── Min H1 (16 bougies)
```

### 3.3 Niveau M15 — Le Signal d'Entrée

**Objectif** : Identifier le déclencheur précis d'entrée lorsque toutes les conditions supérieures sont alignées.

Deux signaux d'entrée sont reconnus :

**La Bougie Englobante (Engulfing)**

```
Haussière                    Baissière
   │  ┌──┐                  │  ┌──┐
   │  │  │ ← prev           │  │  │ ← prev (haussière)
   │  └──┘                  │  └──┘
   │                         │
   │ ┌────┐                  │ ┌────┐
   │ │    │ ← actuelle       │ │    │ ← actuelle
   │ │    │   (englobe       │ │    │   (englobe
   │ └────┘    la précédente)│ └────┘    la précédente)
   └──────────               └──────────
```

Conditions : Corps actuel > Corps précédent + La bougie actuelle englobe entièrement le corps précédent.

**Le Marobozu**

Bougie dont le corps représente ≥ 70% de la range totale (mèches très petites).

```
Marobozu Haussier  Marobozu Baissier
   │ ─              │ ┌──┐
   │ ┌──┐           │ │  │  Corps ≥ 70%
   │ │  │  Corps    │ │  │  de la range
   │ │  │  ≥ 70%   │ └──┘
   │ └──┘           │ ─
```

**Le Fair Value Gap (FVG)**

```
FVG Haussier               FVG Baissier
         ┌──┐                  ┌──┐
   ┌──┐  │  │            ┌──┐  │
   │  │  │  │            │  │  │  ← Gap: High[3] < Low[1]
   │  │  │  │  ← Gap:    │  │  │
   └──┘  └──┘               └──┘  └──┘
  [i+2] [i+1] [i]         [i+2] [i+1] [i]
  Low[i] > High[i+2]
```

La stratégie cherche un FVG dans les 8 dernières bougies M15.

---

## 4. LES 6 CONDITIONS DE CONFLUENCE

Le signal n'est valide que si **minimum 5 conditions sur 6** sont remplies simultanément.

| # | Condition | Timeframe | Rôle | Toujours actif |
|---|-----------|-----------|------|---------------|
| **1** | **Tendance H4** (Dow Theory) | H4 | Filtre macro | Oui |
| **2** | **Kill Zone active** | Horaire | Filtre temporel | Oui |
| **3** | **BOS H1** dans le sens du biais | H1 | Confirmation structure | Non |
| **4** | **Zone S&D H1** | H1 | Zone d'intérêt | Non |
| **5** | **FVG M15** | M15 | Micro-imbalance | Non |
| **6** | **Bougie d'entrée M15** | M15 | Déclencheur | Non |

> Les conditions 1 et 2 sont toujours vérifiées. Les conditions 3 à 6 apportent le score additionnel. Score minimum requis : **5/6**.

### Exemple de Scoring — Signal LONG EURUSD

```
✅ Condition 1 : H4 trend = Haussier (HH + HL confirmés)    → +1
✅ Condition 2 : Heure = 08:30 (dans London KZ 07h-10h)     → +1
✅ Condition 3 : H1 BOS haussier (close > dernier swing H)  → +1
✅ Condition 4 : Prix dans zone de demande (bas 35%)        → +1
❌ Condition 5 : Pas de FVG détecté dans les 8 dernières M15 → +0
✅ Condition 6 : Marobozu haussier M15 (corps = 78% range)  → +1

SCORE = 5/6 → SIGNAL VALIDE ✅
```

---

## 5. RÈGLES D'ENTRÉE

### 5.1 Processus de Décision

```
CHAQUE NOUVELLE BOUGIE M15 FERMÉE (pendant Kill Zone)
              │
              ▼
    Score ≥ 5/6 conditions ?
              │
         OUI  │  NON
              │──────────► Attendre la prochaine bougie
              ▼
    Calculer Stop Loss
    (sous/sur la mèche de la bougie de signal + buffer 10%)
              │
              ▼
    SL dans les limites ? (8-40 pips pour EURUSD)
              │
         OUI  │  NON
              │──────────► Signal rejeté
              ▼
    Calculer TP1 = Entrée ± (SL_distance × 1.5)
    Calculer TP2 = Entrée ± (SL_distance × 2.5)
              │
              ▼
    Calculer la taille de position (1% du capital)
              │
              ▼
    OUVERTURE DU TRADE à l'ouverture de la prochaine bougie M15
```

### 5.2 Calcul du Stop Loss

Le Stop Loss est placé **juste en dehors de la mèche** de la bougie de signal, avec un buffer de 10% de la range de cette bougie.

```
Pour un LONG :
  SL = Low[bougie_signal] - (High[bougie_signal] - Low[bougie_signal]) × 0.10
  SL_distance = Close[bougie_signal] - SL

Pour un SHORT :
  SL = High[bougie_signal] + (High[bougie_signal] - Low[bougie_signal]) × 0.10
  SL_distance = SL - Close[bougie_signal]
```

### 5.3 Limites du Stop Loss

| Paire | SL Minimum | SL Maximum | Raison |
|-------|-----------|-----------|--------|
| EURUSD | 8 pips | 40 pips | Éviter le bruit / Éviter les risques excessifs |
| USDJPY | 8 pips | 40 pips | Même logique |
| GBPJPY | 15 pips | 80 pips | Plus volatile, range naturellement plus large |

> Si le SL calculé est hors limites, le signal est **rejeté**.

### 5.4 Calcul des Take Profits

```
TP1 (ferme 50% de la position) :
  LONG  : TP1 = Entrée + 1.5 × SL_distance
  SHORT : TP1 = Entrée - 1.5 × SL_distance

TP2 (ferme 50% restants) :
  LONG  : TP2 = Entrée + 2.5 × SL_distance
  SHORT : TP2 = Entrée - 2.5 × SL_distance
```

Le ratio risque/récompense minimum garanti est donc **1:1.5** (TP1) avec un objectif final de **1:2.5** (TP2).

---

## 6. GESTION DU TRADE

### 6.1 Cycle de Vie d'un Trade

```
OUVERTURE
    │
    ▼
Position ouverte (100% du volume)
SL actif au niveau calculé
TP2 fixé comme objectif final
    │
    ├──► SL touché AVANT TP1
    │         │
    │         ▼
    │    Fermeture 100% à SL
    │    Résultat : -1R
    │
    └──► TP1 touché (1.5R)
              │
              ▼
         50% de la position fermé  → +0.75R encaissé
         SL déplacé au prix d'entrée (BREAKEVEN)
              │
              ├──► SL touché au BE
              │         │
              │         ▼
              │    50% restants fermés à l'entrée
              │    Résultat total : +0.75R (pas de perte)
              │
              ├──► TP2 touché (2.5R)
              │         │
              │         ▼
              │    50% restants fermés à TP2 → +1.25R
              │    Résultat total : +0.75R + 1.25R = +2.0R
              │
              └──► Fermeture forcée 16h00
                        │
                        ▼
                   Fermé au prix courant
                   Résultat : ≥ 0 (SL au BE garantit pas de perte)
```

### 6.2 Scénarios de Résultats

| Scénario | Fréquence (backtest) | Résultat |
|----------|---------------------|---------|
| SL touché (sans TP1) | ~55% | **-1.0R** |
| TP1 puis SL au BE | ~11% | **+0.75R** |
| TP1 puis TP2 | ~16% | **+2.0R** |
| TP1 puis hard close | ~18% | **+0.75R à +2.0R** |

### 6.3 Le Breakeven — Mécanisme Clé

Le breakeven est la protection centrale de la stratégie. Dès que TP1 est atteint :

1. **50% de la position est fermée** au prix TP1 (+0.75R encaissé)
2. **Le Stop Loss est déplacé au prix d'entrée** (risque = 0)
3. Le trade restant court vers TP2 sans risque de perte

```
AVANT TP1 :                APRÈS TP1 :
  TP2  ─────────            TP2  ─────────  ← Objectif inchangé
  TP1  ─────────            TP1  ─────────  ← Déjà touché (50% fermé)
  Entrée ───────            SL   ═════════  ← SL déplacé ici (BE)
  SL   ─────────            Entrée ───────
```

### 6.4 Fermeture Forcée à 16h00

**Règle absolue** : Toutes les positions sont fermées à 16h00 heure broker, sans exception.

- Garantit le caractère **intraday** de la stratégie
- Évite le risque de gap de nuit
- Évite l'exposition aux publications économiques nocturnes
- Maintient une psychologie claire : chaque journée repart de zéro

Si une position est ouverte avec TP1 déjà atteint (SL au BE), la fermeture forcée ne peut générer qu'un profit nul ou positif.

---

## 7. GESTION DU RISQUE

### 7.1 Règles Fondamentales

| Paramètre | Valeur | Justification |
|-----------|--------|---------------|
| **Risque par trade** | 1% du capital | Préserve le capital sur les séries perdantes |
| **Trades simultanés max** | 2 | Limite l'exposition totale à 2% |
| **SL minimum** | 8 pips | Évite les faux signaux sur micro-volatilité |
| **SL maximum** | 40 pips | Plafonne le risque par trade |
| **TP1** | 1.5R | Prend profit partiel rapidement |
| **TP2** | 2.5R | Objectif de long terme favorable |

### 7.2 Calcul de la Taille de Position

```
Formule :
  Lot = (Balance × Risque%) / (SL_distance × Valeur_tick_par_lot)

Exemple — EURUSD, Balance $1 000, Risque 1%, SL 20 pips :
  Risque_USD = $1 000 × 1% = $10
  Valeur_pip_par_lot = $10 (standard lot EURUSD)
  Lot = $10 / (20 pips × $10) = 0.05 lot

Exemple — Capital $100, Risque 1%, SL 20 pips :
  Risque_USD = $1
  Lot = $1 / (20 × $10) = 0.005 → arrondi à 0.01 lot (micro)
```

### 7.3 Adaptation au Petit Capital

| Capital | Risque/trade | Lot typique EURUSD | Gain mensuel estimé |
|---------|-------------|-------------------|-------------------|
| $100 | 1% ($1) | 0.01 | ~$3-5 |
| $500 | 1% ($5) | 0.05 | ~$15-25 |
| $1 000 | 1% ($10) | 0.10 | ~$30-50 |
| $5 000 | 1% ($50) | 0.50 | ~$150-250 |

> Pour un objectif de **$250/mois**, un capital de **$4 000 – $5 000** est nécessaire avec un risque de 2% par trade.

### 7.4 Règles de Discipline

- **Ne jamais modifier le SL** après ouverture (sauf pour le déplacer au BE)
- **Ne jamais rajouter** une position supplémentaire sur un trade perdant
- **Respecter le hard close** même si le trade est proche du TP2
- **Jours à éviter** : NFP (premier vendredi du mois), CPI, FOMC, décisions BCE/Fed

---

## 8. RÉSULTATS DU BACKTEST

### 8.1 Paramètres du Backtest

| Paramètre | Valeur |
|-----------|--------|
| Capital initial | $1 000 |
| Risque par trade | 1% |
| Score minimum | 5/6 |
| TP1 / TP2 | 1.5R / 2.5R |
| Données | M15 + H1 + H4 (réelles, broker) |

### 8.2 Résultats par Paire

| Paire | Période | Trades | Win Rate | Profit Factor | ROI | Sharpe | Max DD |
|-------|---------|--------|----------|--------------|-----|--------|--------|
| **EURUSD** | Jan 2023 – Avr 2026 | 621 | **46.5%** | **1.21** | **+76.8%** | **1.36** | 16.3% |
| **GBPJPY** | Avr 2022 – Avr 2026 | 982 | 43.9% | 1.12 | +66.7% | 0.80 | 21.8% |
| **USDJPY** | Mar 2025 – Avr 2026 | 326 | 45.7% | 1.15 | +25.5% | 1.03 | 12.2% |
| ~~XAUUSD~~ | ~~Fév 2022 – Avr 2026~~ | ~~72~~ | ~~37.5%~~ | ~~0.84~~ | ~~-7.1%~~ | ~~-1.27~~ | ~~13.4%~~ |

### 8.3 Analyse de la Distribution Mensuelle

Sur 49 mois de backtest (portefeuille complet) :

```
Mois gagnants  : 30 / 49  (61%)
Mois perdants  : 19 / 49  (39%)
Meilleur mois  : +26.9R   (Juillet 2025)
Pire mois      : -22.9R   (Avril 2025)
Moyenne mensuelle : +2.9R
```

### 8.4 Interprétation des Métriques

**Win Rate 44-47%**
Un win rate inférieur à 50% est normal et sain pour cette stratégie. L'edge vient du **ratio risque/récompense** (pertes moyennes de 0.9R, gains moyens de 1.3R), pas de la fréquence des victoires.

**Profit Factor 1.12 – 1.21**
Un PF > 1 indique que la stratégie est rentable. Un PF entre 1.1 et 1.3 est considéré comme **solide et durable** pour une stratégie intraday.

**Sharpe Ratio 1.03 – 1.36 (EURUSD)**
Un Sharpe > 1 indique un **edge statistiquement significatif**. EURUSD avec un Sharpe de 1.36 est la paire la plus fiable.

**Breakeven — Impact Mesurable**
```
EURUSD  : 67 trades sauvés (perte évitée après TP1)
GBPJPY  : 101 trades sauvés
USDJPY  : 40 trades sauvés
Total   : 213 trades où le capital a été préservé
```

### 8.5 Limites du Backtest

- **Slippage non modélisé** : En réel, le slippage sur l'entrée peut réduire les performances de 5-10%.
- **Spread non inclus** : Prévoir 0.5-1 pip de frais par trade sur EURUSD.
- **Données historiques** : Les performances passées ne garantissent pas les performances futures.
- **USDJPY** : Seulement 13 mois de données — résultats à confirmer sur une période plus longue.

---

## 9. IMPLÉMENTATION MT5

### 9.1 Fichier EA

```
Fichier    : KZC_EA.mq5
Langage    : MQL5
Plateforme : MetaTrader 5
```

### 9.2 Paramètres Configurables

```
═══════════════════════════════════════════════════
  GESTION DU RISQUE
═══════════════════════════════════════════════════
  InpRiskPct        = 1.0     Risque % par trade
  InpTP1_R          = 1.5     TP1 en R (50% fermé)
  InpTP2_R          = 2.5     TP2 en R (50% fermé)
  InpBreakeven      = true    Activer le breakeven
  InpMaxConcurrent  = 2       Max trades simultanés

═══════════════════════════════════════════════════
  FILTRES STRATÉGIE
═══════════════════════════════════════════════════
  InpMinScore       = 5       Score minimum (sur 6)
  InpSL_MinPips     = 8       SL minimum en pips
  InpSL_MaxPips     = 40      SL maximum en pips
  InpH4_SwingBars   = 2       Confirmation swing H4
  InpFVG_Lookback   = 8       Lookback FVG en bougies
  InpZone_H1_Bars   = 16      Bougies H1 pour zone
  InpZone_Threshold = 0.35    Seuil zone (35%)
  InpMarobozu_Ratio = 0.70    Ratio marobozu (70%)

═══════════════════════════════════════════════════
  SESSIONS (heure broker)
═══════════════════════════════════════════════════
  InpLondonStart    = 7       London KZ début
  InpLondonEnd      = 10      London KZ fin
  InpNYStart        = 13      NY KZ début
  InpNYEnd          = 16      NY KZ fin
  InpHardClose      = 16      Fermeture forcée
  InpNoNewEntry     = 15      Dernière entrée autorisée
```

### 9.3 Installation

1. Copier `KZC_EA.mq5` dans `MT5 > MQL5 > Experts`
2. Ouvrir MetaEditor (`F4`) et compiler (`F7`)
3. Ouvrir un graphique M15 de la paire choisie
4. Glisser l'EA sur le graphique
5. Activer le **trading automatique** (bouton vert en haut de MT5)
6. Vérifier que **"Autoriser le trading algorithmique"** est coché dans les propriétés de l'EA

### 9.4 Surveillance Recommandée

Bien que l'EA soit automatique, une vérification quotidienne est conseillée :
- Vérifier les logs de l'EA (onglet **Experts** dans MT5)
- Contrôler que les trades ouverts ont un SL et un TP corrects
- S'assurer qu'aucun trade n'est resté ouvert après 16h00

---

## 10. FAQ ET CAS PARTICULIERS

**Q : Pourquoi éviter de trader pendant la zone morte (10h-13h) ?**
R : C'est la période de consolidation entre Londres et New York. Le volume est faible, les spreads sont plus élevés et les mouvements manquent de direction. Le taux de réussite chute significativement.

**Q : Que faire lors d'une annonce économique majeure ?**
R : Désactiver l'EA au moins 30 minutes avant et 15 minutes après toute publication majeure (NFP, CPI, FOMC, BCE). Les publications créent des mouvements erratiques qui invalident l'analyse technique.

**Q : Pourquoi le win rate est inférieur à 50% mais la stratégie est rentable ?**
R : Le profit ne dépend pas du win rate mais de l'équation : `(Win Rate × Gain moyen) > (Loss Rate × Perte moyenne)`. Avec 45% de wins à +1.3R et 55% de losses à -0.9R : `(0.45 × 1.3) + (0.55 × -0.9) = 0.585 - 0.495 = +0.09R par trade en moyenne`.

**Q : Puis-je augmenter le risque à 2% ou 3% pour gagner plus vite ?**
R : Possible, mais le drawdown augmente proportionnellement. À 2% de risque, le drawdown maximum estimé passe de ~16% à ~32%. Au-delà de 3%, le risque de ruine devient significatif sur une série de pertes.

**Q : L'EA fonctionne-t-il en compte de démonstration ?**
R : Oui. Il est fortement recommandé de le tester en **démo pendant 2 à 4 semaines** avant tout passage en compte réel, pour vérifier la cohérence avec l'heure broker de votre courtier.

**Q : Que faire si le broker a une heure serveur différente ?**
R : Ajuster les paramètres `InpLondonStart`, `InpLondonEnd`, `InpNYStart`, `InpNYEnd` en fonction de l'offset de votre broker. Pour un broker UTC+3 : London KZ = 9h-12h, NY KZ = 15h-18h (ajuster aussi `InpHardClose` à 18h).

---

## GLOSSAIRE

| Terme | Définition |
|-------|-----------|
| **BOS** | Break of Structure — Cassure d'un niveau structurel H1 |
| **CHoCH** | Change of Character — Renversement de tendance |
| **FVG** | Fair Value Gap — Imbalance entre 3 bougies consécutives |
| **HH / HL** | Higher High / Higher Low — Hauts et bas croissants (tendance haussière) |
| **LH / LL** | Lower High / Lower Low — Hauts et bas décroissants (tendance baissière) |
| **Kill Zone** | Fenêtre horaire de liquidité institutionnelle maximale |
| **Marobozu** | Bougie dont le corps représente ≥ 70% de la range |
| **R** | Multiple de risque (1R = montant risqué sur le trade) |
| **S&D** | Supply & Demand — Zones d'offre et de demande |
| **Swing High/Low** | Point pivot — sommet ou creux local confirmé |

---

*Document généré à partir du backtest KZC sur données réelles 2022–2026.*  
*Résultats basés sur un capital de $1 000 avec 1% de risque par trade.*  
*Les performances passées ne garantissent pas les performances futures.*
