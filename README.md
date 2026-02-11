# Envolées — Backtest Engine

Moteur de backtest pour stratégie de breakout Donchian avec filtre EMA et volatilité, conçu pour les prop firms (FTMO, Goat Funded Trader).

---

## Architecture générale

```
Données Yahoo (1H) → Resample (4H) → Indicateurs → Stratégie → Moteur de backtest → Résultats
```

Le système se décompose en trois couches :

1. **Stratégie** (`strategy/donchian_breakout.py`) — Décide *quand* et *où* placer un ordre stop.
2. **Moteur** (`backtest/engine.py`) — Simule l'exécution : déclenchement des stops, ouverture/fermeture des positions, gestion du P&L.
3. **Positions** (`backtest/position.py`) — Logique de chaque position individuelle : calcul du P&L, vérification des sorties SL/TP.


---

## Logique de signal : le stop proactif

### Le problème de l'ancienne approche

L'ancienne version détectait un breakout *après coup* :

```
Bar N : close = 105, canal haut = 103
→ Le prix a DÉJÀ traversé le canal
→ On place un "stop" à 103... mais le prix est à 105
→ Le backtest simule un fill à 103, ce qui est fictif
```

En live, on aurait obtenu un fill à ~105 (le prix courant), pas à 103.

### La correction : stop pré-placé

Le signal est maintenant émis *avant* le breakout. À chaque barre, on vérifie :

```
LONG : close > EMA                         (tendance OK)
       close < D_high + buffer              (PAS encore cassé)
       (D_high + buffer) - close < 1.5×ATR  (assez proche)
       → Buy-stop placé à D_high + buffer
```

Si le prix casse le canal sur la barre suivante, le stop est déclenché au bon prix. Si le prix s'éloigne ou que les conditions changent, l'ordre est annulé et recalculé.

### Recalcul continu

Le canal Donchian bouge à chaque barre (le plus haut des 20 dernières barres change). L'ordre stop doit suivre. À chaque barre, le moteur :

1. Demande à la stratégie un signal (peut être le même niveau, un niveau différent, ou rien)
2. Si signal → place ou **remplace** le pending order
3. Si pas de signal → **annule** le pending order existant

Il n'y a plus de notion d'expiration — l'ordre vit tant que les conditions sont remplies.


---

## Positions multiples (empilage momentum)

Le moteur autorise plusieurs positions ouvertes simultanément sur le même instrument. La contrainte est uniquement sur les ordres : **un seul pending order à la fois** (pas d'ordres contradictoires).

Scénario typique lors d'un fort mouvement haussier :

```
Bar 1 : stop placé à 103.0 → déclenché → Position A ouverte
Bar 2 : canal monte à 103.5 → nouveau stop à 103.6
Bar 3 : stop déclenché → Position B ouverte (A toujours active)
Bar 4 : canal monte encore → nouveau stop → Position C
...
```

Cela permet de profiter du momentum avec un risque fractionné (`risk_per_trade` par position).

Le paramètre `MAX_CONCURRENT_TRADES` (défaut 0 = illimité) plafonne le nombre de positions ouvertes. Quand le plafond est atteint, aucun nouvel ordre n'est placé jusqu'à ce qu'une position se ferme.


---

## Heuristique de résolution same-bar (chemin de prix)

Le moteur applique une heuristique de plausibilité du chemin dans deux situations où une bougie 4H est ambiguë. Le principe est identique : on calcule le parcours minimum d'un scénario, et si ce parcours dépasse 1.5× le range réel de la bougie, on le considère physiquement impossible.

### Situation 1 : Entry + SL sur la barre d'entrée

Quand le pending order est déclenché (le prix touche le niveau d'entry), il arrive que le Low de la même bougie soit aussi sous le SL. Question : le SL a-t-il été touché *après* l'entry (= perte immédiate) ou *avant* (= l'entry n'était pas encore active, la position survit) ?

**Scénario A — SL après entry (perte)** :

```
         entry (103) ← prix monte ici, stop déclenché
        /            \
Open (101)            SL (101.5) ← pullback, position perdue
```

Chemin : `|Open → entry| + |entry → SL|` = 2 + 1.5 = **3.5 points**

**Scénario B — SL avant entry (survit)** :

```
                      entry (103) ← prix monte ici, stop déclenché
                     /
Low (100.5) ← dip AVANT le breakout
   \       /
    Open (101)
```

Le dip à 100.5 se produit quand le stop n'est pas encore actif. Le prix remonte ensuite et déclenche l'entry. La position survit.

**La règle** :

```python
chemin_entry_puis_sl = |Open → entry| + |entry → SL|

if chemin_entry_puis_sl > 1.5 × range_bar:
    → Position survit (le SL a été touché AVANT l'entry)
else:
    → Perte immédiate (le scénario entry→SL est plausible)
```

Si la position survit, les barres suivantes sont sans ambiguïté :
- TP touché sans SL préalable → clairement un TP
- SL touché sans TP préalable → clairement un SL

### Situation 2 : SL + TP sur une barre ultérieure

Sur une bougie 4H, on dispose de 4 valeurs : Open, High, Low, Close. Quand le High touche le TP et le Low touche le SL, on ne sait pas lequel a été touché en premier. L'ancienne approche attribuait systématiquement un SL (conservateur).

Mais cette attribution est souvent fausse, surtout sur les bougies de forte amplitude.

### L'intuition

Prenons un LONG avec entry à 100, SL à 98.5, TP à 103.

Pour que le résultat soit un SL *suivi* d'un TP (le scénario où le mode conservateur se trompe), il faudrait que le prix fasse :

```
Open (102.5) → descend jusqu'au SL (98.5) → remonte jusqu'au TP (103)
```

Calculons le chemin minimum de ce scénario :

```
Descente : 102.5 → 98.5 = 4.0 points
Remontée : 98.5  → 103   = 4.5 points
Total    :                  8.5 points
```

Or la bougie a un range de `High - Low = 103.1 - 98.4 = 4.7 points`.

Le prix aurait dû parcourir 8.5 points de chemin dans une bougie qui n'a que 4.7 points d'amplitude. C'est physiquement impossible : le chemin minimum dépasse largement le range réel.

### La règle

```python
chemin_SL_first = |Open → SL| + |SL → TP|

if chemin_SL_first > 1.5 × range_bar:
    → TP  (le scénario SL-first ne tient pas dans cette bougie)
else:
    → SL  (le scénario est plausible, on reste conservateur)
```

Le facteur 1.5 (plutôt que 1.0) donne une marge : même si le chemin est légèrement supérieur au range, on ne bascule pas immédiatement en TP. Il faut que l'implausibilité soit franche.

### Exemples visuels

**Cas 1 — TP attribué** (open haut, range serré)

```
TP  ─────── 103.0   ···· High = 103.1
            102.5   ← Open
Entry ───── 100.0
SL  ─────── 98.5    ···· Low = 98.4

Range = 4.7 | Chemin SL-first = 8.5 | 8.5 > 7.05 (1.5×4.7) → TP ✓
```

Le prix a probablement ouvert à 102.5, fait une mèche basse à 98.4 (touchant le SL sur le papier) puis monté à 103.1 (TP). Mais pour atteindre le SL en premier il aurait fallu un aller-retour de 8.5 points dans un range de 4.7. Impossible. Le plus probable : la mèche basse s'est produite *avant* ou indépendamment de la montée vers le TP.

**Cas 2 — SL attribué** (open bas, gros range)

```
TP  ─────── 103.0   ···· High = 104
            
Entry ───── 100.0
            99.5    ← Open
SL  ─────── 98.5    ···· Low = 98.0

Range = 6.0 | Chemin SL-first = 5.5 | 5.5 < 9.0 (1.5×6.0) → SL (conservateur)
```

Ici le range est large (6 points) et l'open est près de l'entry. Le scénario open → SL → TP ne demande que 5.5 points de chemin, ce qui tient dans le range. On ne peut pas exclure un SL → on reste conservateur.


---

## Paramètres clés

| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| `PROXIMITY_ATR` | 1.5 | Distance max au canal pour placer un stop (en multiples ATR). Plus haut = plus de signaux mais plus de faux départs. |
| `BUFFER_ATR` | 0.10 | Buffer ajouté au bord du canal pour éviter le bruit. Entry LONG = D_high + 0.10×ATR. |
| `SL_ATR` | 1.00 | Distance du SL par rapport à l'entry (en multiples ATR). |
| `TP_R` | 1.00 | Ratio risque/récompense. TP = entry + TP_R × (entry − SL). |
| `RISK_PER_TRADE` | 0.0025 | Risque par position (0.25% du capital). |
| `MAX_CONCURRENT_TRADES` | 0 | Plafond de positions simultanées (0 = illimité). |
| `EXEC_PENALTY_ATR` | variable | Slippage modélisé sur l'entry (décale l'entry contre nous). |
| `DONCHIAN_N` | 20 | Période du canal Donchian (plus haut/bas des N dernières barres). |
| `EMA_PERIOD` | 200 | Période EMA pour le filtre de tendance. |
| `VOL_QUANTILE` | 0.90 | Filtre volatilité : ATR relatif doit être sous le quantile 90%. |
| `NO_TRADE_START/END` | 22:30 / 06:30 | Fenêtre sans nouvelles décisions (heure Paris). |


---

## Flux d'une barre dans le moteur

```
Pour chaque barre (4H) :
│
├── 1. Calcul equity mark-to-market (toutes positions)
├── 2. Gestion changement de jour (reset daily DD)
├── 3. Mise à jour equity tracking + prop sim
│
├── 4. Pour chaque position ouverte :
│      └── SL ou TP touché ? → clôture, P&L, enregistrement
│         (avec heuristique de chemin si les deux sont touchés)
│
├── 5. Pending order existe ?
│      └── Stop déclenché (High/Low traverse le niveau) ?
│          └── Oui → nouvelle position ouverte
│
└── 6. Recalcul du signal :
       ├── Conditions remplies → place/remplace le pending order
       ├── Conditions non remplies → annule le pending order
       └── Plafond positions atteint → pas de nouvel ordre
```


---

## Structure des fichiers

```
envolees/
├── strategy/
│   ├── base.py                 # Classes abstraites (Signal, Strategy)
│   └── donchian_breakout.py    # Stratégie Donchian + EMA + volatilité
├── backtest/
│   ├── engine.py               # Moteur principal (boucle bar-by-bar)
│   ├── position.py             # OpenPosition, PendingOrder, TradeRecord
│   └── prop_sim.py             # Simulation règles prop firm (DD limits)
├── indicators/
│   ├── atr.py, donchian.py, ema.py
├── data/
│   ├── yahoo.py                # Téléchargement Yahoo Finance
│   ├── cache.py                # Cache local des données
│   └── calendar.py, aliases.py, ftmo_instruments.py
├── output/
│   ├── scoring.py              # Métriques de performance
│   ├── compare.py              # Comparaison multi-ticker/multi-penalty
│   └── export.py               # Export résultats
├── config.py                   # Configuration (.env → dataclass)
├── cli.py                      # Interface ligne de commande
├── prefilter.py                # Pré-sélection instruments
├── alerts.py                   # Alertes TradingView / webhook
└── profiles.py                 # Profils de risque (challenge/funded)
```
