from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import libsql_client
import datetime
import os
import numpy as np
import asyncio
from openai import OpenAI

app = FastAPI(title="stratOS Unified API")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ============================================================================
# CONFIGURACIÓN (Variables de Entorno)
# ============================================================================
LIBSQL_URL = os.environ.get("LIBSQL_URL", "https://stratos-db-raul-0602.aws-us-west-2.turso.io")
LIBSQL_AUTH_TOKEN = os.environ.get("LIBSQL_AUTH_TOKEN", "PEGA_TU_TOKEN_DE_LIBSQL_AQUI")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "PEGA_TU_TOKEN_DE_OPENROUTER_AQUI")

CAPITAL_INICIAL = 650.0
COMISION_PCT = 0.0018
RESERVA_PCT = 0.20

# Cliente OpenRouter
ai_client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)

# Estado en memoria para los agentes
estado_agentes = {
    "investigador": {"status": "Idle", "log": "Esperando directiva..."},
    "sintetizador": {"status": "Idle", "log": "Esperando hipotesis..."},
    "developer": {"status": "Idle", "log": "Esperando codigo..."},
    "auditor": {"status": "Idle", "log": "Esperando backtest..."},
    "telemetria": {"status": "Idle", "log": "Monitoreando infraestructura..."}
}

def get_db():
    return libsql_client.create_client_sync(url=LIBSQL_URL, auth_token=LIBSQL_AUTH_TOKEN)

def init_db():
    client = get_db()
    client.execute('''CREATE TABLE IF NOT EXISTS trades (
        trade_id TEXT PRIMARY KEY, timestamp_entrada TEXT, bot_id TEXT, accion TEXT,
        simbolo TEXT, precio_entrada REAL, precio_salida REAL, nocional REAL,
        pnl_neto REAL, estado TEXT, duracion_min INTEGER, bar_close_time TEXT, execution_type TEXT)''')
    client.execute('''CREATE TABLE IF NOT EXISTS active_positions (
        trade_id TEXT PRIMARY KEY, bot_id TEXT, simbolo TEXT, timeframe TEXT,
        tipo TEXT, entry_price REAL, tp_price REAL, sl_price REAL, bar_close_time TEXT)''')
    client.close()

init_db()

# ============================================================================
# MODELOS
# ============================================================================
class EntradaPayload(BaseModel):
    bot_id: str
    action: str
    symbol: str
    price: float
    tp_price: float
    sl_price: float
    timeframe: str
    bar_close_time: str

class CierrePayload(BaseModel):
    trade_id: str
    exit_price: float
    exec_type: str

class AgentOrder(BaseModel):
    prompt: str

# ============================================================================
# RUTAS DEL DASHBOARD (TRADING)
# ============================================================================
@app.get("/")
def read_index():
    return FileResponse("static/index.html")

@app.get("/api/metrics")
def get_metrics():
    client = get_db()
    res_trades = client.execute("SELECT pnl_neto, duracion_min FROM trades WHERE estado = 'CERRADO'")
    rows = res_trades.rows
    res_abiertos = client.execute("SELECT COUNT(*) FROM active_positions")
    abiertos = res_abiertos.rows[0][0]
    client.close()

    if not rows:
        return {
            "balance": CAPITAL_INICIAL, "pnl": 0.0, "win_rate": 0.0, "profit_factor": 0.0,
            "sharpe": 0.0, "sortino": 0.0, "calmar": 0.0, "expectancy": 0.0,
            "reserva": CAPITAL_INICIAL * RESERVA_PCT, "capital_operativo": CAPITAL_INICIAL * (1-RESERVA_PCT),
            "duracion_prom": 0, "equity": [CAPITAL_INICIAL]*7, "dates": ["D1", "D2", "D3", "D4", "D5", "D6", "Hoy"],
            "bots": [{"name": "Bot 01 - BTC", "status": "Activo", "pnl": 0.0}, {"name": "Bot 02 - ETH", "status": "Activo", "pnl": 0.0}],
            "last_update": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        }

    pnls = [r[0] for r in rows]
    duraciones = [r[1] for r in rows if r[1] is not None]
    total_tr = len(pnls)
    ganadores = [p for p in pnls if p > 0]
    perdedores = [p for p in pnls if p <= 0]
    
    pnl_acum = sum(pnls)
    balance = CAPITAL_INICIAL + pnl_acum
    wr = (len(ganadores) / total_tr * 100) if total_tr > 0 else 0
    pf = (sum(ganadores) / abs(sum(perdedores))) if sum(perdedores) != 0 else 0
    
    avg_win = np.mean(ganadores) if ganadores else 0
    avg_loss = abs(np.mean(perdedores)) if perdedores else 0
    expectancy = (wr/100 * avg_win) - ((1 - wr/100) * avg_loss)
    
    returns = np.array(pnls) / CAPITAL_INICIAL
    sharpe = (np.mean(returns) / np.std(returns) * np.sqrt(252)) if np.std(returns) > 0 else 0
    downside_returns = returns[returns < 0]
    sortino = (np.mean(returns) / np.std(downside_returns) * np.sqrt(252)) if len(downside_returns) > 0 and np.std(downside_returns) > 0 else 0
    
    reserva_usd = balance * RESERVA_PCT
    capital_operativo = balance - reserva_usd

    eq_curve = [CAPITAL_INICIAL]
    for p in pnls: eq_curve.append(eq_curve[-1] + p)
    while len(eq_curve) < 7: eq_curve.insert(0, CAPITAL_INICIAL)

    return {
        "balance": round(balance, 2), "pnl": round(pnl_acum, 2), "win_rate": round(wr, 2),
        "profit_factor": round(pf, 2), "sharpe": round(sharpe, 2), "sortino": round(sortino, 2),
        "calmar": 0.0, "expectancy": round(expectancy, 2), "reserva": round(reserva_usd, 2),
        "capital_operativo": round(capital_operativo, 2), "duracion_prom": round(np.mean(duraciones), 1) if duraciones else 0,
        "equity": eq_curve[-7:], "dates": ["T-6", "T-5", "T-4", "T-3", "T-2", "T-1", "Hoy"],
        "bots": [{"name": "Bot 01 - BTC", "status": "Activo", "pnl": 0.0}],
        "last_update": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    }

# ============================================================================
# RUTAS DEL BOARDROOM (AGENTES IA)
# ============================================================================
@app.get("/api/agents/status")
def get_agent_status():
    return estado_agentes

@app.post("/api/agents/run")
async def run_agents(order: AgentOrder):
    orden_ceo = order.prompt
    
    MODEL_FAST = "meta-llama/llama-3-8b-instruct:free"
    MODEL_CODE = "mistralai/mistral-7b-instruct:free"

    def llamar_llm(prompt, model):
        try:
            res = ai_client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], temperature=0.2)
            return res.choices[0].message.content
        except Exception as e:
            return f"Error: {e}"

    # Agente 1: Investigador
    estado_agentes["investigador"] = {"status": "Working", "log": "Analizando mercado..."}
    log1 = llamar_llm(f"Orden: '{orden_ceo}'. Propón 3 variables cuantitativas (ej. RSI, Volumen). Sin código.", MODEL_FAST)
    estado_agentes["investigador"]["log"] = log1

    # Agente 2: Sintetizador
    estado_agentes["sintetizador"] = {"status": "Working", "log": "Creando hipotesis..."}
    log2 = llamar_llm(f"Basado en: {log1}\nCrea una regla booleana exacta para señales de compra.", MODEL_FAST)
    estado_agentes["sintetizador"]["log"] = log2

    # Agente 3: Developer (AQUI ESTA EL CODIGO)
    estado_agentes["developer"] = {"status": "Working", "log": "Escribiendo codigo Python..."}
    log3 = llamar_llm(f"Escribe solo la función calcular_senales(df, params) en Pandas para esta regla: {log2}. Usa .shift(1).", MODEL_CODE)
    codigo_limpio = log3.replace("```python", "").replace("```", "")
    estado_agentes["developer"]["log"] = codigo_limpio

    # Agente 4: Auditor
    estado_agentes["auditor"] = {"status": "Working", "log": "Auditando codigo..."}
    log4 = llamar_llm(f"Revisa este código: {log3}\nResponde '✅ APROBADO' o '❌ RECHAZADO' y por qué.", MODEL_CODE)
    estado_agentes["auditor"]["log"] = log4

    # Agente 5: Telemetria
    estado_agentes["telemetria"] = {"status": "Working", "log": "Enviando reporte..."}
    await asyncio.sleep(1)
    estado_agentes["telemetria"]["log"] = "✅ Mision cumplida."

    return {"success": True}
# ============================================================================
# RUTAS DE OPERACIONES (TRADING)
# ============================================================================
@app.get("/api/trades")
def get_trades():
    client = get_db()
    res = client.execute("SELECT trade_id, timestamp_entrada, bot_id, accion, simbolo, precio_entrada, precio_salida, pnl_neto, estado FROM trades ORDER BY timestamp_entrada DESC LIMIT 20")
    client.close()
    trades = [{"trade_id": r[0], "timestamp": r[1], "bot_id": r[2], "accion": r[3], "simbolo": r[4], "precio_entrada": r[5], "precio_salida": r[6], "pnl_neto": r[7], "estado": r[8]} for r in res.rows]
    return {"success": True, "data": trades}

@app.post("/api/entrada")
def registrar_entrada(payload: EntradaPayload):
    client = get_db()
    res_sym = client.execute("SELECT COUNT(*) FROM active_positions WHERE simbolo = ?", [payload.symbol])
    if res_sym.rows[0][0] >= 1:
        client.close()
        return {"success": False, "error": "symbol_cap"}
    trade_id = f"{payload.bot_id}-{int(datetime.datetime.now().timestamp() * 1000)}"
    now_str = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    res_pnl = client.execute("SELECT SUM(pnl_neto) FROM trades WHERE estado = 'CERRADO'")
    pnl_acum = res_pnl.rows[0][0] or 0.0
    nocional = round((CAPITAL_INICIAL + pnl_acum) * 0.30, 2)
    client.execute('''INSERT INTO trades (trade_id, timestamp_entrada, bot_id, accion, simbolo, precio_entrada, nocional, pnl_neto, estado, bar_close_time, execution_type) VALUES (?, ?, ?, ?, ?, ?, ?, 0.0, 'ABIERTO', ?, 'PENDING')''', [trade_id, now_str, payload.bot_id, payload.action, payload.symbol, payload.price, nocional, payload.bar_close_time])
    client.execute('''INSERT INTO active_positions (trade_id, bot_id, simbolo, timeframe, tipo, entry_price, tp_price, sl_price, bar_close_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', [trade_id, payload.bot_id, payload.symbol, payload.timeframe, payload.action, payload.price, payload.tp_price, payload.sl_price, payload.bar_close_time])
    client.close()
    return {"success": True, "data": trade_id}

@app.post("/api/cierre")
def registrar_cierre(payload: CierrePayload):
    client = get_db()
    res_trade = client.execute("SELECT accion, precio_entrada, nocional, timestamp_entrada FROM trades WHERE trade_id = ?", [payload.trade_id])
    trade = res_trade.rows[0] if res_trade.rows else None
    if not trade:
        client.close()
        return {"success": False, "error": "trade_not_found"}
    accion, precio_entrada, nocional, ts_entrada = trade
    pnl_bruto = nocional * (payload.exit_price - precio_entrada) / precio_entrada if accion == "LONG" else nocional * (precio_entrada - payload.exit_price) / precio_entrada
    pnl_neto = round(pnl_bruto - (nocional * COMISION_PCT), 2)
    entrada_dt = datetime.datetime.strptime(ts_entrada, "%Y-%m-%d %H:%M:%S")
    duracion = int((datetime.datetime.utcnow() - entrada_dt).total_seconds() / 60)
    client.execute('''UPDATE trades SET precio_salida = ?, pnl_neto = ?, estado = 'CERRADO', duracion_min = ?, execution_type = ? WHERE trade_id = ?''', [payload.exit_price, pnl_neto, duracion, payload.exec_type, payload.trade_id])
    client.execute("DELETE FROM active_positions WHERE trade_id = ?", [payload.trade_id])
    client.close()
    return {"success": True, "data": pnl_neto}