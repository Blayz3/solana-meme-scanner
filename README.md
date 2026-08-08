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

## 1. El bot de Telegram

1. Abrí [@BotFather](https://t.me/BotFather) en Telegram y mandá `/newbot`.
2. Le ponés nombre y usuario (tiene que terminar en `bot`). Te devuelve un token
   tipo `8123456789:AAH...`.
3. **Escribile algo a tu bot** — Telegram no deja que te hable primero.
4. Sacá tu chat id abriendo esta URL en el navegador, con tu token:
   `https://api.telegram.org/bot<TOKEN>/getUpdates` → buscá `"chat":{"id":123456789`.

```bash
gh secret set TELEGRAM_TOKEN --body "8123456789:AAH..."
gh secret set TELEGRAM_CHAT_ID --body "123456789"
```

Para probarlo local: `export TELEGRAM_TOKEN=... TELEGRAM_CHAT_ID=...`

## 2. Los 30 traders (análisis único, ya hecho)

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

**Esto ya se corrió y la lista está congelada**: 30 traders, de 8.185x a 10x, sacados
de 1.683 candidatos en 70 tokens grandes. El bot NO reanaliza: solo vigila. Si algún
día querés refrescarla, corré `--rank` a mano y volvé a subir el secret (paso 5).

Necesita `SOLANATRACKER_KEY` (gratis en [solanatracker.io/data-api](https://www.solanatracker.io/data-api)),
solo para este paso — el bot vigilando no la usa.

## 3. Tus wallets

Van aparte de los 30: **nunca se caen de la lista**.

```bash
python3 scanner.py --add 62qc2CNXwrYqQScmEdiZFFAnJR262PxWEuNQtxfafNgV
python3 scanner.py --add mis-traders.txt
```

Acepta direcciones sueltas, un `.txt` (una por línea, `#` para comentar), y URLs
pegadas del navegador (gmgn, solscan, axiom, birdeye). Para sacar una, borrala de
`smart.json`.

**Después de agregar wallets hay que resubir el secret** (paso 5), si no Actions
sigue con la lista vieja.

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

Ya está corriendo en un repo público (los privados dan 2000 min/mes, no alcanza).
`.github/workflows/scanner.yml` levanta un job de 5h45 y se releva cada 6h, así que
el poll sigue siendo de 30s y no los 5 minutos del cron de Actions.

**Tu lista de wallets no está en el repo** — `smart.json` está en `.gitignore` y viaja
como secret cifrado:

```bash
python3 scanner.py --export | gh secret set SMART_JSON
```

Correlo cada vez que agregues wallets o refresques el ranking. Para arrancar ya sin
esperar al cron:

```bash
gh workflow run scanner.yml
gh run watch
```

**Antes de dejarlo así:** el uso aceptable de GitHub Actions pide que los minutos sean
para el proyecto de software, no para correr un servicio propio 24/7; un bot de cripto
permanente es justo el caso que suelen marcar, y la cuenta es tuya. Además el repo
público muestra tus filtros y tu estrategia (las wallets no). Un VPS de $5 evita las dos.

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
  señales, bajá `min_smart` a 2 o corré `--rank` con `rank_min_tokens=2` y `top_n=100`.
- **La lista envejece**: un trader que la rompió en 2025 puede estar retirado. Refrescá
  el ranking cada par de meses.
