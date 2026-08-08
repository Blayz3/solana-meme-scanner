# solana-meme-scanner

Te avisa por Telegram cuando **≥3 de los 30 mejores traders** entran a un token
limpio con mcap entre **$120k y $5M**.

```bash
python3 scanner.py --rank        # traer los 30 mejores traders (necesita key)
python3 scanner.py --add WALLET  # sumar los tuyos (o un .txt, o URLs)
python3 scanner.py --wallets     # ver a quién vigila
python3 scanner.py               # vigilar (loop)
python3 scanner.py --test        # self-check
```

## 1. La key (2 min, gratis)

Sacá una en [solanatracker.io/data-api](https://www.solanatracker.io/data-api) —
plan Free, sin tarjeta, 1 request/segundo.

```bash
export SOLANATRACKER_KEY=...
export TELEGRAM_TOKEN=...  TELEGRAM_CHAT_ID=...
```

El chat id lo sacás escribiéndole a tu bot y abriendo
`https://api.telegram.org/bot<TOKEN>/getUpdates`.

## 2. Los 30 mejores traders

```bash
python3 scanner.py --rank
```

Busca los tokens que **ya hicieron el recorrido** (mcap ≥$10M hoy) y le pide a Solana
Tracker todos sus traders. Una wallet puntúa solo si en ese token cumple las dos cosas:

- **ROI ≥500%** — entró abajo de verdad. Ordenar por ganancia trae ballenas que
  movieron $6M para sacar 20%: esos no te sirven, entran arriba.
- **ganancia ≥$10.000** — y no es polvo. Ordenar por ROI trae wallets con
  185.000.000.000% sobre tres centavos.

Hay techo además (ROI ≤1.000.000%, ganancia ≤$50M por token): arriba de eso no hay
humano, hay un router mal etiquetado. Sin ese corte el ranking lo encabezaba una
wallet con $186.000 millones.

Suma la ganancia de cada token donde lo logró, tiene que aparecer en **≥2 tokens
distintos** (uno es suerte) y quedan los **30 con más ganancia**. Los resultados se
**acumulan entre corridas**: cada vez analiza solo los tokens nuevos, así que la
lista crece y mejora sola.

Descarta lo que Solana Tracker marca como `bot`, `pool`, `developer`, `exchange`,
`hacker`, `spam_dusting` y `arbitrage` — esos ganan por infraestructura, no por criterio.

Volvé a correrlo cada tanto; en Actions ya corre solo una vez por día. Hoy quedaron
17 traders — el umbral de ≥2 tokens es exigente y hay ~38 tokens grandes por corrida;
llega a 30 en unos días de cron.

## 3. Tus wallets

Van aparte del top 30: **nunca se caen de la lista**, sin importar el ranking.

```bash
python3 scanner.py --add 62qc2CNXwrYqQScmEdiZFFAnJR262PxWEuNQtxfafNgV
python3 scanner.py --add mis-traders.txt
```

Acepta direcciones sueltas, un `.txt` (una por línea, `#` para comentar), y URLs
pegadas del navegador (gmgn, solscan, axiom, birdeye). Para sacar una, borrala de
`smart.json`.

## 4. Vigilar

Cada ciclo (~60s) junta ~200 tokens de DexScreener + GeckoTerminal, se queda con los
de tu rango y les pide el reporte de RugCheck. Manda alerta a Telegram si hay
**≥3 wallets vigiladas** en el top-20 de holders **y** pasa todo el anti-rug.
Vuelve a avisar si la cuenta sube (3 → 5).

### Anti-rug (todo tiene que dar OK)

mint y freeze authority quemadas · no marcado `rugged` · sin riesgos `danger` ·
score RugCheck ≤35 · LP bloqueada ≥90% · holder #1 ≤15% · top10 ≤45% ·
insiders ≤20% · liq ≥$15k · vol24/liq ≤60 (wash trading).

Todo se ajusta en el dict `F` arriba de `scanner.py`.

## 5. 24/7 en GitHub Actions

El workflow ya está en `.github/workflows/scanner.yml`. Necesita **repo público**
(los privados tienen 2000 min/mes, no alcanza ni para un día). Corre un job de
5h45 y se releva cada 6h, así que el poll sigue siendo de 30s, no de 5 minutos.

**Tu lista de wallets no va al repo.** Se guarda en un gist privado:

```bash
gh gist create smart.json --desc "scanner state"        # anotá el id que imprime
gh secret set GIST_ID --body "<id>"
gh secret set GH_TOKEN --body "<token con scope gist>"
gh secret set SOLANATRACKER_KEY --body "$SOLANATRACKER_KEY"
gh secret set TELEGRAM_TOKEN --body "$TELEGRAM_TOKEN"
gh secret set TELEGRAM_CHAT_ID --body "$TELEGRAM_CHAT_ID"
```

Sin `GIST_ID` el bot funciona igual, pero en Actions arranca de cero cada relevo.

**Dos cosas antes de subirlo:** el uso aceptable de GitHub Actions pide que los
minutos sean para el proyecto de software, no para correr un servicio propio 24/7;
un bot de cripto permanente es justo el caso que suelen marcar, y la cuenta es tuya.
Y aunque las wallets queden en el gist, el repo público muestra tus filtros y tu
estrategia. Un VPS de $5 evita las dos cosas.

Alternativa local, sin GitHub:

```bash
nohup python3 scanner.py >> scanner.log 2>&1 &
```

## Límites reales

- **Latencia**: detecta por holders, no por transacción. La señal llega dentro del
  minuto, no en el bloque.
- **Top 20**: solo ve wallets con posición grande. Un trader que puso $500 en un
  token de $3M no aparece en el snapshot.
- **30 wallets es una red angosta**: que 3 de ellas coincidan en el mismo token
  chico pasa pocas veces por semana. Es alta precisión, no volumen. Si querés más
  señales, subí `top_n` a 100 o bajá `min_smart` a 2.
