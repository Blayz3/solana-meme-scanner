# solana-meme-scanner

Te avisa por Telegram cuando **≥3 de los 30 mejores traders** entran a un token
limpio con mcap entre **$120k y $5M**. Busca cada **20 minutos**.

El único criterio del token es ese: que estén 3 o más adentro y que no sea rug.
Lo exigente es quién entra en la lista de traders.

```bash
python3 scanner.py --rank        # rearmar los 30 traders (necesita key, ~25 min)
python3 scanner.py --reelegir    # rehacer la selección sin reanalizar tokens
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

Un trader entra a la lista solo si cumple las tres cosas:

1. **Rompió un x100** alguna vez — al menos un token con ROI ≥10.000%.
2. **Sus x20 se repiten** — ≥2 tokens distintos arriba de x20. Un pelotazo es suerte;
   repetir es método.
3. **Es una persona** — entre 20 y 5.000 posiciones históricas. Hay wallets con
   **182.463 tokens operados**: son granjas que compran todo, cumplen el x100 de casualidad
   y son imposibles de seguir. Se filtraron nueve, de 7.000 a 42.000 posiciones.

Y por token, para que ese acierto cuente: ROI ≥500% con ganancia ≥$10.000 — abajo de eso
es polvo, arriba de un techo (ROI ≤1.000.000%, ≤$50M) es un router mal etiquetado.
Sin ese techo el ranking lo encabezaba una wallet con $186.000 millones.

**Cómo los busca.** Arranca por los tokens que ya hicieron el recorrido (mcap ≥$5M hoy) y
después va en **bola de nieve**: a los que califican les mira en qué otros tokens ganaron,
analiza esos, y repite. Así llegó a **776 tokens y 9.099 candidatos** — las listas de
trending sueltas dan 45 tokens y se agotan enseguida.

**La lista está congelada**: el bot NO reanaliza, solo vigila. Para refrescarla algún día,
`--rank` (~25 min, necesita `SOLANATRACKER_KEY` gratis de
[solanatracker.io/data-api](https://www.solanatracker.io/data-api)) y resubir el secret.
`--reelegir` rehace solo la selección con lo ya analizado, en un minuto.

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

Cada corrida junta ~200 tokens de DexScreener + GeckoTerminal, se queda con los de tu
rango y les pide el reporte de RugCheck. Manda alerta a Telegram si hay **≥3 wallets
vigiladas** en el top-20 de holders **y** pasa todo el anti-rug. Vuelve a avisar si la
cuenta sube (3 → 5). Una corrida tarda ~25 segundos.

### Anti-rug (todo tiene que dar OK)

mint y freeze authority quemadas · no marcado `rugged` · sin riesgos `danger` ·
score RugCheck ≤35 · LP bloqueada ≥90% · holder #1 ≤15% · top10 ≤45% ·
insiders ≤20% · liq ≥$15k · vol24/liq ≤60 (wash trading).

Todo se ajusta en el dict `F` arriba de `scanner.py`.

## 5. 24/7 en GitHub Actions

Ya está corriendo: `.github/workflows/scanner.yml` busca **cada 20 minutos** (GitHub
suele demorar unos minutos más). `estado.json` viaja por el cache de Actions para no
repetirte el mismo token en cada corrida.

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
  el ranking cada par de meses con `--rank`.
- **Cada 20 min, no al instante**: si tres de ellos entran justo después de una corrida,
  te enterás hasta 20 minutos después.

## Panel local

    python3 app.py     # http://localhost:7777

Corre el scanner en tu máquina y muestra en el navegador lo alertado: mcap de
entrada, mcap de ahora, múltiplo alcanzado y a qué mcap está el x10. El log del
bot va abajo. Necesita `smart.json` local (el de Actions vive en el secret).
