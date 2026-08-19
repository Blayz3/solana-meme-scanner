#!/usr/bin/env python3
"""Panel local: corre el bot y muestra en el navegador lo que dice comprar.

    python3 app.py        ->  http://localhost:7777

Sin dependencias (subprocess + http.server), igual que el resto del proyecto.
El scanner es un subproceso: su stdout es el log del panel y su estado.json,
la tabla de monedas.
"""
import json
import subprocess
import sys
import threading
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

DIR = Path(__file__).parent
ESTADO = DIR / "estado.json"
ULTIMO = DIR / "ultimo.json"
PUERTO = 7777
LOG = deque(maxlen=400)


def correr():
    """El scanner como subproceso: su stdout es el log del panel."""
    bot = subprocess.Popen([sys.executable, "-u", str(DIR / "scanner.py")],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for linea in bot.stdout:
        LOG.append(linea.rstrip())
        print(linea, end="")
    LOG.append(f"--- el scanner terminó (código {bot.wait()}) ---")


def leer(p, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default   # el scanner puede estar escribiéndolo justo ahora


def ultimo():
    return leer(ULTIMO, {"cerca": [], "simbolos": [], "en_rango": 0, "nuevas": 0, "gatillo": 3, "t": 0})


def tokens():
    """Lo alertado, lo último arriba. El estado viejo (int pelado) no tiene nada que mostrar."""
    d = leer(ESTADO, {})
    return sorted((dict(v, mint=m) for m, v in d.items() if isinstance(v, dict)),
                  key=lambda v: -v["t"])


HTML = """<!doctype html><meta charset=utf-8><title>solana meme scanner</title>
<style>
 :root{--bg:#0b0d10;--panel:#14181d;--linea:#232a32;--txt:#e6edf3;--gris:#7d8896;--lima:#c9f31d}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--txt);
   font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
 header{padding:14px 20px;border-bottom:1px solid var(--linea);display:flex;
   align-items:baseline;gap:12px} h1{font-size:15px;margin:0;letter-spacing:.14em;text-transform:uppercase}
 #estado{color:var(--gris);font-size:12px} main{padding:20px;display:grid;gap:20px}
 table{width:100%;border-collapse:collapse} th{text-align:left;font-weight:400;color:var(--gris);
   font-size:11px;letter-spacing:.1em;text-transform:uppercase;padding:0 10px 8px;white-space:nowrap}
 td{padding:10px;border-top:1px solid var(--linea);white-space:nowrap}
 tr:hover td{background:var(--panel)} a{color:var(--txt)} .num{text-align:right}
 .x{font-weight:700} .g0{color:var(--gris)} .g2{color:#6cb6ff} .g5{color:#f0b429} .g10{color:var(--lima)}
 .sym{font-weight:700} .nueva{color:var(--lima);font-size:11px;margin-left:6px}
 .vacio{color:var(--gris);padding:24px 10px}
 .riesgo{color:#f0743e;font-size:11px;white-space:normal}
 .escaneado{margin-top:10px;font-size:11px;color:#4d5560;white-space:normal;line-height:1.7}
 h2{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--gris);
   margin:0 0 10px;font-weight:400} h2 small{text-transform:none;letter-spacing:0}
 pre{background:var(--panel);border:1px solid var(--linea);border-radius:6px;padding:14px;
   margin:0;max-height:34vh;overflow:auto;color:var(--gris);font-size:12px;white-space:pre-wrap}
</style>
<header><h1>Solana meme scanner</h1><span id=estado>conectando…</span></header>
<main>
 <section><h2>Alertadas — comprar</h2>
 <table><thead><tr><th>Moneda<th class=num>Entrada<th class=num>Ahora<th class=num>Múltiplo
   <th class=num>Objetivo x10<th class=num>Wallets<th>Alertada<th></tr></thead>
  <tbody id=filas></tbody></table></section>
 <section><h2>En observación <small id=sub></small></h2>
  <table><thead><tr><th>Moneda<th class=num>Mcap<th class=num>Smart wallets<th>Riesgo<th></tr></thead>
   <tbody id=cerca></tbody></table></section>
 <pre id=log></pre>
</main>
<script>
const usd = n => '$' + Math.round(n).toLocaleString('es');
const hace = t => { const m = (Date.now()/1000 - t)/60;
  return m < 60 ? `hace ${m|0} min` : m < 1440 ? `hace ${m/60|0} h` : `hace ${m/1440|0} d`; };
const clase = x => x >= 10 ? 'g10' : x >= 5 ? 'g5' : x >= 2 ? 'g2' : 'g0';

async function refrescar() {
  let d;
  try { d = await (await fetch('/datos')).json(); }
  catch { estado.textContent = 'panel caído'; return; }
  estado.textContent = `${d.tokens.length} monedas alertadas · el bot escanea cada 20 s`;
  filas.innerHTML = d.tokens.map(t => `<tr>
    <td><span class=sym>${t.sym || t.mint.slice(0,4)}</span>${t.nueva ? '<span class=nueva>NUEVA</span>' : ''}
    <td class=num>${usd(t.mcap0)}<td class=num>${usd(t.mcap0 * t.x)}
    <td class="num x ${clase(t.x)}">${t.x.toFixed(1)}x
    <td class="num g0">${usd(t.mcap0 * 10)}<td class=num>${t.n}
    <td class=g0>${hace(t.t)}
    <td>${t.url ? `<a href="${t.url}" target=_blank>dexscreener ↗</a>` : ''}</tr>`).join('')
    || '<tr><td colspan=8 class=vacio>Todavía ninguna. El bot avisa acá y por Telegram.</td></tr>';
  const u = d.ultimo;
  sub.textContent = u.t ? `— ${u.en_rango} tokens en rango (${u.nuevas} recién salidas) · gatillo ${u.gatillo} wallets`
                          + (u.anti_rug === false ? ' · anti-rug APAGADO' : '')
                        : '— esperando el primer ciclo…';
  cerca.innerHTML = u.cerca.map(t => `<tr>
    <td><span class=sym>${t.sym}</span>${t.nueva ? '<span class=nueva>NUEVA</span>' : ''}
    <td class=num>${usd(t.mcap)}<td class="num ${t.n >= u.gatillo ? 'g10' : 'g0'}">${t.n} de ${u.gatillo}
    <td>${(t.riesgo || []).length ? `<span class=riesgo>⚠️ ${t.riesgo.join(', ')}</span>` : ''}
    <td><a href="${t.url}" target=_blank>dexscreener ↗</a></tr>`).join('')
    || `<tr><td colspan=5 class=vacio>Ninguno de los ${u.en_rango} tokens del ciclo tiene smart money
         adentro — es lo normal, el gatillo salta pocas veces por día.
         <div class=escaneado>Escaneados sin señal (no son recomendaciones): ${(u.simbolos || []).join(' · ')}</div>
       </td></tr>`;
  log.textContent = d.log.join('\\n');
  log.scrollTop = log.scrollHeight;
}
refrescar(); setInterval(refrescar, 3000);
</script>"""


class Panel(BaseHTTPRequestHandler):
    def do_GET(self):
        json_ = self.path.startswith("/datos")
        cuerpo = json.dumps({"log": list(LOG), "tokens": tokens(), "ultimo": ultimo()}) if json_ else HTML
        self.send_response(200)
        self.send_header("Content-Type", "application/json" if json_ else "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo.encode())

    def log_message(self, *_):
        pass  # el log del panel es el del bot, no el de cada request


if __name__ == "__main__":
    threading.Thread(target=correr, daemon=True).start()
    print(f"panel en http://localhost:{PUERTO}  (ctrl-c para cortar)")
    webbrowser.open(f"http://localhost:{PUERTO}")
    try:
        HTTPServer(("127.0.0.1", PUERTO), Panel).serve_forever()
    except KeyboardInterrupt:
        print("\nchau")
