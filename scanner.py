#!/usr/bin/env python3
"""Escáner de meme coins en Solana: smart money + anti-rug. Sin API keys.

  python3 scanner.py --rank        # los 30 mejores traders (necesita SOLANATRACKER_KEY)
  python3 scanner.py --bootstrap   # alternativa sin key: aprende ganadoras solo
  python3 scanner.py               # loop: avisa cuando >=3 smart wallets entran
  python3 scanner.py --once
  python3 scanner.py --add WALLET [WALLET...]   # cargar tus traders (o un .txt, o URLs)
  python3 scanner.py --wallets     # ver la lista de smart money
  python3 scanner.py --export      # la lista sola, para el secret SMART_JSON
  python3 scanner.py --test

Datos: DexScreener (precio/liq/vol) + RugCheck (holders, insiders, authorities, LP).
Alertas a Telegram si exportás TELEGRAM_TOKEN y TELEGRAM_CHAT_ID.
"""
import json, os, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

F = dict(
    # rango de compra
    mcap_min=120_000, mcap_max=5_000_000,
    mcap_min_nueva=30_000,  # recién salidas: piso más bajo, el x10 está acá
    edad_nueva_h=24,        # hasta qué edad un par cuenta como "recién salido"
    liq_min=15_000,
    # gatillo de alerta
    min_smart=3,          # smart wallets dentro del top 20 de holders
    top_n=30,             # cuántos traders vigilar (los tuyos van aparte, siempre)
    min_wins=3,           # una wallet es "smart" si acertó en >=3 tokens ganadores
    # anti-rug (todo esto tiene que dar OK o se descarta)
    holder_max_pct=15,    # holder individual (sin contar AMM/locker/lockers)
    top10_max_pct=45,     # concentración del top 10
    insider_max_pct=20,   # suma de holders marcados insider por RugCheck
    lp_locked_min=90,     # % de LP bloqueada
    rug_score_max=35,     # score_normalised de RugCheck (más alto = más riesgo)
    vol_liq_max=60,       # arriba de esto huele a wash trading
    # bootstrap / rank: qué cuenta como "token ganador"
    win_ch24_min=150, win_mcap_min=400_000,
    rank_mcap_min=5_000_000,  # --rank: tokens que ya llegaron acá (los 300k -> 40M)
    rank_roi_min=500,          # % — entró abajo de verdad (500% = 6x). Corta a las ballenas del +20%
    rank_pnl_min=10_000,       # $ — y ganó plata real. Corta el polvo con ROI de 1.000.000%
    rank_roi_max=1_000_000,    # % — techo de cordura: 10.000x no lo hace un humano, es dato roto
    rank_pnl_max=50_000_000,   # $ — idem, arriba de esto es un router/pool mal etiquetado
    rank_x100=10_000,          # % — tiene que haber roto un x100 al menos una vez
    rank_x20=2_000,            # % — y los x20 tienen que ser constantes:
    rank_x20_veces=2,          #     al menos 2 tokens distintos arriba de x20
    rank_rondas=2,             # rondas de bola de nieve: en qué más ganaron los que califican
    pos_min=20,                # posiciones históricas: menos que esto es suerte, no historial
    pos_max=5_000,             # y más que esto es una granja de bots (vimos una con 182.463)
    bundle_max_overlap=0.5,  # si dos ganadores comparten >50% de holders, es el mismo grupo
)
POLL = 20  # segundos entre ciclos
HITOS = (2, 5, 10)          # múltiplos que se avisan desde el mcap de la alerta
VENTANA = 21 * 86400        # después de esto se deja de seguir el token

DIR = Path(__file__).parent
SMART = DIR / "smart.json"      # {"wallets": {addr: {"wins": n, "tokens": []}}, "creditados": []}
ESTADO = DIR / "estado.json"    # {mint: ultimo_n_smart_alertado}
UA = {"User-Agent": "Mozilla/5.0 (meme-scanner)"}


def get(url, timeout=15):
    for _ in range(2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return json.load(r)
        except Exception as e:
            err = e
            time.sleep(2)
    print(f"  ! fallo {url.split('?')[0]}: {err}", file=sys.stderr)
    return None


def sembrar():
    """En Actions la lista viene del secret SMART_JSON: nunca toca el repo público."""
    semilla = os.getenv("SMART_JSON")
    if semilla and not SMART.exists():
        SMART.write_text(semilla)
        print(f"lista cargada del secret ({len(json.loads(semilla).get('wallets', {}))} wallets)")


def cargar(p, default):
    return json.loads(p.read_text()) if p.exists() else default


# --- fuentes ---------------------------------------------------------------
def candidatos(paginas=3):
    """Mints de Solana: feeds de DexScreener + pools de GeckoTerminal (ambos sin key)."""
    mints = []
    for url in ("https://api.dexscreener.com/token-profiles/latest/v1",
                "https://api.dexscreener.com/token-boosts/latest/v1",
                "https://api.dexscreener.com/token-boosts/top/v1"):
        for t in get(url) or []:
            if t.get("chainId") == "solana" and t.get("tokenAddress"):
                mints.append(t["tokenAddress"])

    gt = "https://api.geckoterminal.com/api/v2/networks/solana/"
    for ruta in ("trending_pools?duration=24h", "pools?sort=h24_volume_usd_desc", "new_pools"):
        for pag in range(1, paginas + 1):
            d = get(f"{gt}{ruta}{'&' if '?' in ruta else '?'}page={pag}")
            for p in (d or {}).get("data") or []:
                mints.append(p["relationships"]["base_token"]["data"]["id"].removeprefix("solana_"))
            time.sleep(2.5)  # GeckoTerminal: 30 req/min
    return list(dict.fromkeys(mints))


NO_MEME = {  # stablecoins, wrappeds y majors: no son el juego
    "USDT", "USDC", "USDS", "USDG", "PYUSD", "EURC", "syrupUSDC", "USDe", "FDUSD", "USD1",
    "SOL", "WSOL", "JitoSOL", "mSOL", "bSOL", "JupSOL", "INF", "hSOL",
    "WBTC", "wBTC", "cbBTC", "zBTC", "ETH", "wETH", "ZEC", "HYPE", "XRP", "SUI", "LINK",
    "JUP", "ORCA", "RAY", "MET", "JLP", "PUMP", "DRIFT", "KMNO"}


def tokens_grandes():
    """Tokens que ya hicieron el recorrido (300k -> 40M): los de mcap alto de hoy.
    Solana Tracker en 2 requests da más que 20 páginas de GeckoTerminal."""
    vistos = {}
    for ruta in ("/tokens/trending/24h", "/tokens/volume/24h", "/tokens/trending/12h",
                 "/tokens/trending/6h", "/tokens/volume/12h", "/tokens/trending/1h",
                 "/tokens/volume/6h", "/tokens/multi/graduated"):
        d = st(ruta, limit=100)
        for t in (d if isinstance(d, list) else filas(d)):
            tok, pools = t.get("token") or {}, t.get("pools") or [{}]
            mcap = max(((p.get("marketCap") or {}).get("usd") or 0) for p in pools)
            sym = tok.get("symbol") or "?"
            if tok.get("mint") and mcap >= F["rank_mcap_min"] and sym not in NO_MEME:
                vistos[tok["mint"]] = {"baseToken": {"symbol": sym, "address": tok["mint"]},
                                       "marketCap": mcap}
    return sorted(vistos.items(), key=lambda x: -x[1]["marketCap"])


def edad_h(par):
    """Horas desde que se creó el par (0 si DexScreener no lo dice)."""
    ts = par.get("pairCreatedAt") or 0
    return (time.time() * 1000 - ts) / 3.6e6 if ts else 0


def en_rango(par):
    """Rango de compra. Las de <24h entran desde $30k: un x10 desde $2M pide $20M,
    desde $50k pide $500k. Abajo el x10 es frecuente, por eso el anti-rug es el mismo."""
    mcap = par.get("marketCap") or par.get("fdv") or 0
    piso = F["mcap_min_nueva"] if 0 < edad_h(par) <= F["edad_nueva_h"] else F["mcap_min"]
    return piso <= mcap <= F["mcap_max"] and liq(par) >= F["liq_min"]


def liq(par):
    return (par.get("liquidity") or {}).get("usd") or 0


def pares(mints):
    """Mejor par (el más líquido) por token, 30 tokens por request.
    Ojo: el endpoint viejo /latest/dex/tokens corta en 30 PARES y se come el 90% de los
    tokens cuando cada uno tiene varios pools. /tokens/v1 devuelve uno por token."""
    out = {}
    for i in range(0, len(mints), 30):
        for p in get("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(mints[i:i + 30])) or []:
            m = p["baseToken"]["address"]
            if m not in out or liq(p) > liq(out[m]):  # el primero entra siempre: liquidity puede ser None
                out[m] = p
        time.sleep(0.3)
    return out


def reporte(mint):
    r = get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report", timeout=20)
    time.sleep(0.4)
    return r if isinstance(r, dict) and "topHolders" in r else None


# --- análisis --------------------------------------------------------------
def holders_reales(rep):
    """Top holders sin AMMs, lockers ni pools. Estos sí son gente."""
    conocidas = rep.get("knownAccounts") or {}
    return [h for h in rep.get("topHolders") or []
            if h.get("owner") and h["owner"] not in conocidas and h.get("address") not in conocidas]


def anti_rug(rep, par):
    """[] si está limpio, si no la lista de razones para descartar."""
    mal = []
    if rep.get("rugged"):
        mal.append("YA RUGEÓ")
    if rep.get("mintAuthority"):
        mal.append("mint authority viva")
    if rep.get("freezeAuthority"):
        mal.append("freeze authority viva")
    for r in rep.get("risks") or []:
        if r.get("level") == "danger":
            mal.append(r.get("name", "riesgo"))
    if (rep.get("score_normalised") or 0) > F["rug_score_max"]:
        mal.append(f"rugcheck {rep.get('score_normalised')}")

    hs = holders_reales(rep)
    if hs and hs[0]["pct"] > F["holder_max_pct"]:
        mal.append(f"holder #1 {hs[0]['pct']:.0f}%")
    if sum(h["pct"] for h in hs[:10]) > F["top10_max_pct"]:
        mal.append(f"top10 {sum(h['pct'] for h in hs[:10]):.0f}%")
    ins = sum(h["pct"] for h in rep.get("topHolders") or [] if h.get("insider"))
    if ins > F["insider_max_pct"]:
        mal.append(f"insiders {ins:.0f}%")

    lp = max([(m.get("lp") or {}).get("lpLockedPct") or 0 for m in rep.get("markets") or []] or [0])
    if lp < F["lp_locked_min"]:
        mal.append(f"LP libre {100 - lp:.0f}%")

    l, vol24 = liq(par), (par.get("volume") or {}).get("h24") or 0
    if l < F["liq_min"]:
        mal.append(f"liq ${l:,.0f}")
    if l and vol24 / l > F["vol_liq_max"]:
        mal.append(f"vol/liq {vol24 / l:.0f} (wash?)")
    return mal


ST = "https://data.solanatracker.io"
NO_HUMANOS = {"bot", "pool", "developer", "exchange", "hacker", "spam_dusting", "arbitrage"}


def st(path, **params):
    """Solana Tracker. Necesita SOLANATRACKER_KEY (gratis en data.solanatracker.io)."""
    key = os.getenv("SOLANATRACKER_KEY")
    if not key:
        sys.exit("falta SOLANATRACKER_KEY — sacá una gratis en https://www.solanatracker.io/data-api")
    url = f"{ST}{path}?" + urllib.parse.urlencode(params)
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={**UA, "x-api-key": key})
            with urllib.request.urlopen(req, timeout=25) as r:
                time.sleep(1.1)  # free tier: 1 req/s
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(5); continue
            print(f"  ! {path}: HTTP {e.code}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"  ! {path}: {e}", file=sys.stderr)
            return None


def filas(resp):
    """La lista de resultados venga con el nombre que venga (traders/firstBuyers/data)."""
    if isinstance(resp, list):
        return resp
    for v in (resp or {}).values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v
    return []


def wallet_de(fila):
    return fila.get("wallet") or fila.get("address") or fila.get("owner")


def humana(fila):
    """False si Solana Tracker la marcó como bot, pool, dev, exchange..."""
    ident = fila.get("identity") or {}
    return not (set(ident.get("tags") or []) & NO_HUMANOS) and not any(
        ident.get(k) for k in ("bot", "pool", "developer", "hacker", "exchange"))


def ganancia(fila):
    pnl = fila.get("pnl") or {}
    tok = pnl.get("token") if isinstance(pnl.get("token"), dict) else pnl
    return float((tok or {}).get("total") or (tok or {}).get("realized") or 0)


def merece(fila):
    """El que buscás: entró abajo (ROI alto) Y se llevó plata real. No la ballena del +20%,
    no el polvo con ROI de 1.000.000% sobre 3 centavos."""
    roi, pnl = fila.get("roi") or 0, ganancia(fila)
    return bool(humana(fila) and wallet_de(fila)
                and F["rank_roi_min"] <= roi <= F["rank_roi_max"]
                and F["rank_pnl_min"] <= pnl <= F["rank_pnl_max"])


def constante(v):
    """El trader que buscás: rompió un x100 alguna vez Y sus x20 se repiten.
    Un solo pelotazo es suerte; el que repite x20 tiene método."""
    x = v.get("x") or []
    return max(x, default=0) >= F["rank_x100"] and sum(1 for r in x if r >= F["rank_x20"]) >= F["rank_x20_veces"]


def analizar(mint):
    """(símbolo, traders que entraron abajo y ganaron) de un token."""
    d = st(f"/v2/pnl/tokens/{mint}/traders", sort="pnl", direction="desc", limit=200)
    sym = ((d or {}).get("meta") or {}).get("symbol") or mint[:6]
    return sym, [f for f in filas(d) if merece(f)]


def expandir(puntos, hechos):
    """Los tokens donde los que YA califican también ganaron. Ahí hay más como ellos."""
    nuevos = set()
    for w in [w for w, v in puntos.items() if constante(v)][:40]:
        d = st(f"/v2/pnl/wallets/{w}/positions", limit=100, sort="pnl", direction="desc")
        for pos in filas(d):
            mint = pos.get("token")
            if isinstance(mint, str) and mint not in hechos and (pos.get("roi") or 0) >= F["rank_x20"]:
                nuevos.add(mint)
    return sorted(nuevos)


def posiciones(w):
    """Cuántos tokens distintos operó en su vida. Un humano: decenas o cientos.
    182.463 es una granja que compra todo — imposible de seguir y ensucia la señal."""
    d = st(f"/v2/pnl/wallets/{w}/positions", limit=1)
    return ((d or {}).get("stats") or {}).get("total")


def elegir(puntos):
    """Los top_n que califican Y son wallets de persona, verificando una por una."""
    top = []
    for v in sorted(({**v, "w": w} for w, v in puntos.items() if constante(v)), key=lambda x: -x["roi"]):
        if len(top) >= F["top_n"]:
            break
        n = posiciones(v["w"])
        if n is None or not (F["pos_min"] <= n <= F["pos_max"]):
            print(f"  x {v['w'][:8]}..: {n} posiciones — fuera")
            continue
        top.append({**v, "pos": n})
    return top


def guardar_top(d, top):
    for w in list(d["wallets"]):                       # el top se recalcula entero
        if not d["wallets"][w].get("mio") and d["wallets"][w].get("pnl"):
            del d["wallets"][w]
    for v in top:
        e = d["wallets"].setdefault(v["w"], {"wins": 0, "tokens": []})
        e.update(pnl=round(v["pnl"]), roi=v["roi"], x=v["x"], pos=v["pos"], tokens=v["tokens"][-20:],
                 wins=max(e["wins"], len(v["tokens"])))
    SMART.write_text(json.dumps(d, indent=1))
    print(f"\ntop {len(top)} traders")
    for v in top:
        xs = " ".join(f"{r / 100:.0f}x" for r in sorted(v["x"], reverse=True)[:5])
        print(f"  ${v['pnl']:>11,.0f}  {v['pos']:>5} pos  [{xs}]  {v['w']}")


def reelegir():
    """Rehacer la selección con lo ya analizado, sin volver a gastar en tokens."""
    d = cargar(SMART, {"wallets": {}})
    guardar_top(d, elegir(d.get("rank") or {}))


def rankear():
    """Los top_n traders que rompieron un x100 y repiten x20."""
    st("/v2/pnl/leaderboard/top", days=1, limit=1)  # falla acá y no después de escanear
    d = cargar(SMART, {"wallets": {}, "creditados": [], "sets": {}})
    puntos = d.setdefault("rank", {})          # se acumula entre corridas
    hechos = set(d.setdefault("rank_hechos", []))
    cola = [m for m, _ in tokens_grandes() if m not in hechos]

    for ronda in range(F["rank_rondas"] + 1):
        print(f"\n--- ronda {ronda}: {len(cola)} tokens ---" if ronda else f"{len(cola)} tokens para analizar")
        for i, mint in enumerate(cola, 1):
            sym, buenos = analizar(mint)
            hechos.add(mint)
            for f in buenos:
                e = puntos.setdefault(wallet_de(f), {"pnl": 0.0, "roi": 0, "tokens": [], "x": []})
                e["pnl"] += ganancia(f)
                e["roi"] = max(e["roi"], round(f.get("roi") or 0))
                e["tokens"] = (e["tokens"] + [sym])[-20:]
                e["x"] = (e["x"] + [round(f.get("roi") or 0)])[-20:]
            if i % 10 == 0 or i == len(cola):
                print(f"  {i}/{len(cola)} — {sum(1 for v in puntos.values() if constante(v))} califican", flush=True)
        if ronda == F["rank_rondas"]:
            break
        cola = expandir(puntos, hechos)

    d["rank_hechos"] = sorted(hechos)[-5000:]
    print(f"\n{len(puntos)} candidatos de {len(hechos)} tokens — verificando cuáles son personas")
    guardar_top(d, elegir(puntos))


def vigiladas(todas=None):
    """Las tuyas (siempre) + los mejores top_n por PnL, o por aciertos si no corriste --rank."""
    todas = cargar(SMART, {"wallets": {}})["wallets"] if todas is None else todas
    mias = {w: v for w, v in todas.items() if v.get("mio")}
    resto = sorted(((w, v) for w, v in todas.items() if not v.get("mio")),
                   key=lambda x: (-(x[1].get("pnl") or 0), -x[1]["wins"]))
    top = {w: v for w, v in resto if v.get("pnl") or v["wins"] >= F["min_wins"]}
    return mias | dict(list(top.items())[:F["top_n"]]), len(mias)


def bundle(duenos, sets):
    """Mint de un ganador previo con el mismo grupo de wallets, si lo hay."""
    return next((m for m, prev in sets.items()
                 if duenos and len(duenos & set(prev)) / len(duenos) > F["bundle_max_overlap"]), None)


def smart_dentro(rep, wallets):
    """Smart wallets presentes en el top 20 de holders, ordenadas por aciertos."""
    dentro = [(h["owner"], h["pct"], wallets[h["owner"]].get("roi") or 0)
              for h in holders_reales(rep) if h["owner"] in wallets]
    return sorted(dentro, key=lambda x: -x[2])   # el de mayor múltiplo primero


def resumen(rep, par, smart):
    hs = holders_reales(rep)
    ins = [h for h in rep.get("topHolders") or [] if h.get("insider")]
    vol24 = (par.get("volume") or {}).get("h24") or 0
    mcap = par.get("marketCap") or par.get("fdv") or 0
    ch = par.get("priceChange") or {}
    edad = edad_h(par)
    lineas = [
        f"{'🆕' if 0 < edad < F['edad_nueva_h'] else '🐋'} {par['baseToken']['symbol']} — "
        f"{len(smart)} smart wallets adentro",
        f"mcap ${mcap:,.0f} | liq ${liq(par):,.0f} | vol24 ${vol24:,.0f} | edad {edad:.1f}h",
        f"1h {ch.get('h1', 0):+.0f}% | 6h {ch.get('h6', 0):+.0f}% | 24h {ch.get('h24', 0):+.0f}%",
        f"holders {rep.get('totalHolders', '?')} | top1 {hs[0]['pct']:.1f}% | top10 "
        f"{sum(h['pct'] for h in hs[:10]):.0f}% | insiders {len(ins)} ({sum(h['pct'] for h in ins):.1f}%)",
        "smart money:",
    ]
    lineas += [f"  {w[:4]}..{w[-4:]}  {pct:.2f}% del supply" + (f"  (max {roi / 100:.0f}x)" if roi else "  (tuya)")
               for w, pct, roi in smart[:6]]
    lineas += [par["url"], rep["mint"]]
    return "\n".join(lineas)


def telegram(msg):
    tok, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return
    body = urllib.parse.urlencode({"chat_id": chat, "text": msg, "disable_web_page_preview": "true"}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", body, timeout=10).read()
    except Exception as e:
        print(f"  ! telegram: {e}", file=sys.stderr)


# --- seguimiento de lo alertado --------------------------------------------
def n_de(estado, mint):
    """Cuántas smart wallets se avisaron ya (estado viejo guardaba el int pelado)."""
    v = estado.get(mint)
    return v["n"] if isinstance(v, dict) else (v or 0)


def avanzar(v, mcap):
    """Múltiplo desde la alerta y el hito recién cruzado, si cruzó alguno."""
    x = mcap / v["mcap0"] if v.get("mcap0") else 0
    if x <= v["x"]:
        return v["x"], None
    return round(x, 2), max((h for h in HITOS if x >= h > v["hito"]), default=None)


def seguir(estado):
    """Precio de lo ya alertado: avisa cada hito y guarda el máximo. Sin esto no hay
    forma de saber si el gatillo encuentra x10 o solo encuentra ruido."""
    vivos = [m for m, v in estado.items() if isinstance(v, dict)
             and v["hito"] < HITOS[-1] and time.time() - v["t"] < VENTANA]
    for mint, par in pares(vivos).items():
        v, mcap = estado[mint], par.get("marketCap") or par.get("fdv") or 0
        v["x"], hito = avanzar(v, mcap)
        if hito:
            v["hito"] = hito
            telegram(f"\U0001F680 {par['baseToken']['symbol']} x{v['x']:.1f} desde la alerta "
                     f"(${v['mcap0']:,.0f} -> ${mcap:,.0f})\n{par['url']}")


def stats():
    d = [v for v in cargar(ESTADO, {}).values() if isinstance(v, dict)]
    if not d:
        return print("todavía no hay alertas con seguimiento")
    print(f"{len(d)} alertas seguidas")
    for h in HITOS:
        n = sum(1 for v in d if v["x"] >= h)
        print(f"  x{h}+: {n:3}  ({n / len(d) * 100:.0f}%)")
    xs = sorted(v["x"] for v in d)
    print(f"  máximo x{xs[-1]:.1f} | mediana x{xs[len(xs) // 2]:.1f}")


# --- modos -----------------------------------------------------------------
def escanear(wallets, estado):
    dentro = {m: p for m, p in pares(candidatos(2)).items() if en_rango(p)}
    nuevas = sum(1 for p in dentro.values() if 0 < edad_h(p) <= F["edad_nueva_h"])
    print(f"[{time.strftime('%H:%M:%S')}] {len(dentro)} tokens en rango "
          f"${F['mcap_min'] / 1000:.0f}k-${F['mcap_max'] / 1e6:.0f}M "
          f"({nuevas} recién salidas desde ${F['mcap_min_nueva'] / 1000:.0f}k)", flush=True)

    for mint, par in dentro.items():
        rep = reporte(mint)
        if not rep:
            continue
        smart = smart_dentro(rep, wallets)
        if len(smart) < F["min_smart"] or len(smart) <= n_de(estado, mint):
            continue  # sin señal, o ya avisé con esta cantidad
        mal = anti_rug(rep, par)
        if mal:
            print(f"  x {par['baseToken']['symbol']}: {len(smart)} smart pero {', '.join(mal[:3])}")
            continue
        prev = estado.get(mint)
        if isinstance(prev, dict):
            prev["n"] = len(smart)          # 2da alerta del mismo token: el mcap de entrada es el primero
        else:
            estado[mint] = {"n": len(smart), "x": 1.0, "hito": 1, "t": time.time(),
                            "mcap0": par.get("marketCap") or par.get("fdv") or 0,
                            "sym": par["baseToken"]["symbol"], "url": par["url"],
                            "nueva": 0 < edad_h(par) <= F["edad_nueva_h"]}
        msg = resumen(rep, par, smart)
        print("\n" + "=" * 60 + "\n" + msg + "\n" + "=" * 60 + "\n", flush=True)
        telegram(msg)
        ESTADO.write_text(json.dumps(estado))
    seguir(estado)
    ESTADO.write_text(json.dumps(estado))


def bootstrap():
    """Aprende smart money: holders de tokens que YA pumpearon. Correr seguido."""
    d = cargar(SMART, {"wallets": {}, "creditados": [], "sets": {}})
    wallets, hechos, sets = d["wallets"], set(d["creditados"]), d.setdefault("sets", {})
    for mint, p in pares(candidatos()).items():
        ch24 = (p.get("priceChange") or {}).get("h24") or 0
        mcap = p.get("marketCap") or p.get("fdv") or 0
        if mint in hechos or ch24 < F["win_ch24_min"] or mcap < F["win_mcap_min"]:
            continue
        rep = reporte(mint)
        if not rep or rep.get("rugged"):
            continue
        hechos.add(mint)
        sym = p["baseToken"]["symbol"]
        duenos = {h["owner"] for h in holders_reales(rep) if h["pct"] <= 10 and not h.get("insider")}
        # mismo grupo de wallets en dos tokens = bundle/sniper cluster, no talento
        gemelo = bundle(duenos, sets)
        if gemelo:
            print(f"  ~ {sym}: bundle, comparte holders con {gemelo[:6]}.. — no cuenta")
            continue
        sets[mint] = sorted(duenos)
        print(f"  ganador {sym} ({ch24:+.0f}% 24h, ${mcap:,.0f})")
        for owner in duenos:
            w = wallets.setdefault(owner, {"wins": 0, "tokens": []})
            w["wins"] += 1
            w["tokens"] = (w["tokens"] + [sym])[-20:]
    d["creditados"] = sorted(hechos)[-2000:]
    d["sets"] = dict(list(sets.items())[-300:])
    SMART.write_text(json.dumps(d, indent=1))
    buenas = {w: v for w, v in wallets.items() if v["wins"] >= F["min_wins"]}
    print(f"{len(wallets)} wallets vistas, {len(buenas)} con >={F['min_wins']} aciertos")


B58 = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")


def normalizar(txt):
    """Wallet suelta, con comas/comillas, o URL (solscan/gmgn/axiom/birdeye). None si no es válida."""
    w = txt.strip().strip(',;"\'').split("?")[0].rstrip("/").split("/")[-1]
    return w if 32 <= len(w) <= 44 and not set(w) - B58 else None


def agregar(entradas):
    """--add: tus traders de confianza entran como smart money sin esperar el bootstrap."""
    textos = []
    for e in entradas:
        crudo = Path(e).read_text() if Path(e).exists() else e
        textos += [w for l in crudo.splitlines() for w in l.split("#")[0].split()]
    d = cargar(SMART, {"wallets": {}, "creditados": [], "sets": {}})
    nuevas = 0
    for t in textos:
        w = normalizar(t)
        if not w:
            print(f"  ! no parece wallet de Solana, la salteo: {t}")
            continue
        e = d["wallets"].setdefault(w, {"wins": 0, "tokens": []})
        nuevas += not e.get("mio")
        e["mio"] = True
        e["wins"] = max(e["wins"], F["min_wins"])  # cuentan desde ya
        if "tuya" not in e["tokens"]:
            e["tokens"].append("tuya")
    SMART.write_text(json.dumps(d, indent=1))
    print(f"+{nuevas} — tenés {sum(1 for v in d['wallets'].values() if v.get('mio'))} wallets propias cargadas")


def exportar():
    """Solo las wallets vigiladas, para el secret SMART_JSON (el análisis queda local)."""
    w, _ = vigiladas()
    print(json.dumps({"wallets": w}, indent=1))


def listar():
    wallets = cargar(SMART, {"wallets": {}})["wallets"]
    for w, v in sorted(wallets.items(), key=lambda x: (-x[1].get("mio", False), -x[1]["wins"]))[:60]:
        if v["wins"] >= F["min_wins"]:
            print(f"{'TUYA' if v.get('mio') else v['wins']:>4}  {w}  {', '.join(v['tokens'][-6:])}")


def test():
    rep = {"mint": "M", "rugged": False, "mintAuthority": None, "freezeAuthority": None,
           "risks": [], "score_normalised": 5, "totalHolders": 900,
           "knownAccounts": {"AMM1": {"type": "AMM"}},
           "markets": [{"lp": {"lpLockedPct": 100}}],
           "topHolders": [{"owner": "AMM1", "address": "x", "pct": 40, "insider": False}] +
                         [{"owner": f"W{i}", "address": f"a{i}", "pct": 2.0, "insider": False} for i in range(10)]}
    par = {"baseToken": {"symbol": "T"}, "url": "u", "pairCreatedAt": (time.time() - 7200) * 1000,
           "liquidity": {"usd": 60_000}, "volume": {"h24": 300_000}, "marketCap": 800_000,
           "priceChange": {"h1": 5, "h6": 40, "h24": 120}}
    wallets = {"W0": {"wins": 3, "roi": 30_000}, "W1": {"wins": 2}, "W3": {"wins": 5, "roi": 90_000},
               "AMM1": {"wins": 9, "roi": 99_999}}

    assert anti_rug(rep, par) == [], anti_rug(rep, par)
    s = smart_dentro(rep, wallets)
    assert [w for w, _, _ in s] == ["W3", "W0", "W1"], s          # ordenadas por aciertos
    assert "AMM1" not in dict((w, 1) for w, _, _ in s)            # el pool no es smart money
    assert len(s) >= F["min_smart"]
    assert "mint authority viva" in anti_rug({**rep, "mintAuthority": "abc"}, par)
    conc = {**rep, "topHolders": [{**rep["topHolders"][1], "pct": 30}] + rep["topHolders"][2:]}
    assert any("holder #1" in m for m in anti_rug(conc, par)), "concentración aceptada"
    ins = {**rep, "topHolders": [{**h, "insider": True, "pct": 3} for h in rep["topHolders"][1:]]}
    assert any("insiders" in m for m in anti_rug(ins, par)), "insiders aceptados"
    assert any("LP libre" in m for m in anti_rug({**rep, "markets": [{"lp": {"lpLockedPct": 0}}]}, par))
    assert any("wash" in m for m in anti_rug({**rep, }, {**par, "volume": {"h24": 9_000_000}}))
    real = "62qc2CNXwrYqQScmEdiZFFAnJR262PxWEuNQtxfafNgV"
    assert normalizar(real) == real
    assert normalizar(f"  {real},\n") == real                              # pegado de una lista
    assert normalizar(f"https://gmgn.ai/sol/address/{real}?tab=pnl") == real  # pegado del navegador
    assert normalizar(f"https://solscan.io/account/{real}/") == real
    assert normalizar("0x1234") is None and normalizar(real + "0OIl") is None
    # parseo de Solana Tracker (respuestas con la forma documentada en el SDK)
    resp = {"traders": [
        {"wallet": "W9", "pnl": {"token": {"realized": 900, "unrealized": 100, "total": 1000},
                                 "wallet": {"invested": 200, "proceeds": 1200}}, "identity": {"tags": ["kol"]}},
        {"wallet": "BOT", "pnl": {"token": {"total": 99999}}, "identity": {"tags": ["bot"], "bot": True}},
        {"wallet": "POOL", "pnl": {"token": {"total": 50000}}, "identity": {"pool": {"dex": "raydium"}}},
    ], "pagination": {"page": 1}}
    f = filas(resp)
    assert len(f) == 3 and wallet_de(f[0]) == "W9", f
    assert ganancia(f[0]) == 1000 and ganancia({"pnl": {"total": 7}}) == 7
    assert humana(f[0]) and not humana(f[1]) and not humana(f[2]), "no filtra bots/pools"
    # el corazón del ranking: ni ballenas de ROI bajo, ni polvo de ROI infinito
    assert merece({"wallet": "W", "roi": 85749, "pnl": {"token": {"total": 1_922_307}}}), "descarta al bueno"
    assert not merece({"wallet": "W", "roi": 55, "pnl": {"token": {"total": 3_462_884}}}), "acepta ballena +55%"
    assert not merece({"wallet": "W", "roi": 185_584_295_978, "pnl": {"token": {"total": 0}}}), "acepta polvo"
    assert not merece({"wallet": "W", "roi": 482_271_612, "pnl": {"token": {"total": 186_875_666_373}}}), \
        "acepta el artefacto de $186.000M"
    # x100 alguna vez + x20 constantes
    assert constante({"x": [81_850, 3_100]}), "rechaza al bueno (818x + 31x)"
    assert not constante({"x": [81_850, 400]}), "un solo x20: no es constante"
    assert not constante({"x": [3_100, 2_400, 2_100]}), "muchos x20 pero nunca rompió el x100"
    assert not constante({"x": []}) and not constante({})
    assert filas({"firstBuyers": [{"address": "X"}]})[0]["address"] == "X"   # otro nombre de lista
    assert filas(None) == [] and wallet_de({}) is None
    todas = {f"R{i}": {"wins": 2, "tokens": [], "pnl": i * 1000} for i in range(50)}
    todas |= {"MIA1": {"wins": 0, "tokens": [], "mio": True}, "FLOJA": {"wins": 1, "tokens": []}}
    sel, mias = vigiladas(todas)
    assert mias == 1 and "MIA1" in sel, "las tuyas tienen que estar siempre"
    assert len(sel) == F["top_n"] + 1, f"top_n no se respeta: {len(sel)}"
    assert "R49" in sel and "R0" not in sel, "no ordena por PnL"
    assert "FLOJA" not in sel, "entra una sin PnL ni aciertos"
    nueva = {**par, "marketCap": 45_000, "pairCreatedAt": (time.time() - 3 * 3600) * 1000}
    assert en_rango(nueva), "una recién salida de $45k queda afuera"
    assert not en_rango({**nueva, "pairCreatedAt": (time.time() - 90 * 3600) * 1000}), \
        "$45k con 90h de edad no es recién salida, es un token muerto"
    assert not en_rango({**nueva, "marketCap": 20_000}), "acepta por debajo del piso de nuevas"
    assert not en_rango({**nueva, "liquidity": {"usd": 500}}), "acepta sin liquidez"
    assert not en_rango({**par, "marketCap": 9_000_000}), "acepta arriba del techo"
    assert en_rango(par) and edad_h({}) == 0
    assert liq({"liquidity": None}) == 0 and liq({"liquidity": {"usd": 5}}) == 5
    assert bundle({"a", "b", "c"}, {"M1": ["a", "b", "z"]}) == "M1", "bundle no detectado"
    assert bundle({"a", "b", "c", "d"}, {"M1": ["a", "q"]}) is None, "falso bundle"
    # seguimiento: hitos una sola vez, y el máximo no baja
    assert n_de({"M": 3}, "M") == 3 and n_de({"M": {"n": 4}}, "M") == 4 and n_de({}, "M") == 0
    v = {"mcap0": 500_000, "x": 1.0, "hito": 1, "t": time.time(), "n": 3}
    v["x"], h = avanzar(v, 1_200_000)
    assert (v["x"], h) == (2.4, 2), (v["x"], h)
    v["hito"] = h
    v["x"], h = avanzar(v, 900_000)
    assert (v["x"], h) == (2.4, None), "el máximo bajó con el precio"
    v["x"], h = avanzar(v, 6_000_000)
    assert (v["x"], h) == (12.0, 10), "se saltea hitos en un salto grande"   # 5 y 10 juntos: avisa el mayor
    v["hito"] = h
    assert avanzar(v, 6_100_000)[1] is None, "reavisa un hito ya avisado"
    assert avanzar({"mcap0": 0, "x": 1.0, "hito": 1}, 9e6) == (1.0, None), "divide por mcap 0"
    resumen(rep, par, s)
    print("ok")


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--test" in a:
        test()
    elif "--bootstrap" in a:
        bootstrap()
    elif "--rank" in a:
        rankear()
    elif "--reelegir" in a:
        reelegir()
    elif "--add" in a:
        agregar(a[a.index("--add") + 1:])
    elif "--export" in a:
        exportar()
    elif "--wallets" in a:
        listar()
    elif "--stats" in a:
        stats()
    else:
        sembrar()
        wallets, mias = vigiladas()
        if len(wallets) < F["min_smart"]:
            sys.exit(f"solo {len(wallets)} wallets vigiladas: con menos de {F['min_smart']} no puede saltar "
                     f"la alerta.\nCargá las tuyas con --add o traé el top con --rank (ver README).")
        print(f"vigilando con {len(wallets)} smart wallets ({mias} tuyas), gatillo >={F['min_smart']}")
        estado = cargar(ESTADO, {})
        while True:
            try:
                escanear(wallets, estado)
            except KeyboardInterrupt:
                break
            if "--once" in a:
                break
            time.sleep(POLL)
