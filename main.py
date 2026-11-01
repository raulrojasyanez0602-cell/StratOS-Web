from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import libsql_client
import datetime
import os
import numpy as np

app = FastAPI(title="stratOS Trading API")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ============================================================================
# CONFIGURACIÓN
# ============================================================================
LIBSQL_URL = os.environ.get("LIBSQL_URL", "https://stratos-db-raul-0602.aws-us-west-2.turso.io")
LIBSQL_AUTH_TOKEN = os.environ.get("LIBSQL_AUTH_TOKEN", "PEGA_TU_TOKEN_DE_TURSO_AQUI")

CAPITAL_INICIAL = 650.0
COMISION_PCT = 0.0018
RESERVA_PCT = 0.20

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

# ============================================================================
# RUTAS DE LA WEB Y MÉTRICAS
# ============================================================================
@app.get("/api/metrics")
def get_metrics():
    # 1. Definimos la lista maestra de tus 4 bots
    ALL_BOTS = ["Bot 01", "Bot 02", "Bot 03", "Bot 04"]
    
    client = get_db()
    # 2. Traemos los trades y calculamos el PnL individual por bot
    res_trades = client.execute("SELECT pnl_neto, duracion_min FROM trades WHERE estado = 'CERRADO'")
    res_bots = client.execute("SELECT bot_id, SUM(pnl_neto) FROM trades WHERE estado = 'CERRADO' GROUP BY bot_id")
    
    rows = res_trades.rows
    # Convertimos el resultado de bots en un diccionario: {"Bot 01": 15.5, "Bot 02": -2.0}
    bot_pnls = {r[0]: r[1] for r in res_bots.rows}
    client.close()

    # 3. Construimos la lista de bots para el frontend SIEMPRE con los 4
    bots_para_frontend = []
    for b in ALL_BOTS:
        # Si el bot no ha operado, su pnl será 0.0
        bots_para_frontend.append({
            "name": b,
            "status": "Activo",
            "pnl": round(bot_pnls.get(b, 0.0), 2)
        })

    # 4. Manejo de caso vacío (Sin trades)
    if not rows:
        return {
            "balance": CAPITAL_INICIAL, "pnl": 0.0, "win_rate": 0.0, "profit_factor": 0.0,
            "sharpe": 0.0, "sortino": 0.0, "expectancy": 0.0, "reserva": CAPITAL_INICIAL * RESERVA_PCT,
            "capital_operativo": CAPITAL_INICIAL * (1-RESERVA_PCT), "duracion_prom": 0,
            "equity": [CAPITAL_INICIAL]*7, "dates": ["D1", "D2", "D3", "D4", "D5", "D6", "Hoy"],
            "bots": bots_para_frontend, # <-- AQUÍ YA ENVIAMOS LOS 4
            "last_update": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        }

    # 5. Cálculos matemáticos (Tu código original)
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
    eq_curve = [CAPITAL_INICIAL]
    for p in pnls: eq_curve.append(eq_curve[-1] + p)
    while len(eq_curve) < 7: eq_curve.insert(0, CAPITAL_INICIAL)

    return {
        "balance": round(balance, 2), "pnl": round(pnl_acum, 2), "win_rate": round(wr, 2),
        "profit_factor": round(pf, 2), "sharpe": round(sharpe, 2), "sortino": round(sortino, 2),
        "expectancy": round(expectancy, 2), "reserva": round(reserva_usd, 2),
        "capital_operativo": round(balance - reserva_usd, 2),
        "duracion_prom": round(np.mean(duraciones), 1) if duraciones else 0,
        "equity": eq_curve[-7:], "dates": ["T-6", "T-5", "T-4", "T-3", "T-2", "T-1", "Hoy"],
        "bots": bots_para_frontend, # <-- AQUÍ ENVIAMOS LOS 4
        "last_update": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    }
# ============================================================================
# RUTAS PARA LOS BOTS (ENTRADA Y CIERRE)
# ============================================================================
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