import streamlit as st
import yfinance as yf
import pandas as pd
import sqlite3
import bcrypt
import time
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

# --- 1. CONFIGURACIÓN Y BASE DE DATOS ---
DB_NAME = 'smartfinancial.db'

# Configuración de página
st.set_page_config(page_title="SmartFinancial Portfolio", layout="wide", initial_sidebar_state="expanded")

# Inicializar session_state
if 'username' not in st.session_state:
    st.session_state.username = None
if 'page' not in st.session_state:
    st.session_state.page = 'login'  # login, portfolio, user_panel

def init_db():
    """Inicializa la base de datos y las tablas de Usuarios y Portfolio."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL)")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            shares INTEGER NOT NULL,
            purchase_price REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- 2. FUNCIONES DE NAVEGACIÓN Y ESTADO ---

def get_user_id(username):
    """Obtiene el ID del usuario por su nombre de usuario."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
    result = cursor.fetchone()
    conn.close()
    if result:
        return result[0]
    return None

# --- 3. FUNCIONES DE AUTENTICACIÓN ---

def register_user(username, password):
    """Registra un nuevo usuario."""
    if not username or not password:
        return False, "❌ Usuario o contraseña no pueden estar vacíos."
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    try:
        password_bytes = password.encode('utf-8')
        password_hash = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode('utf-8')
        cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, password_hash))
        conn.commit()
        return True, "✅ Registro exitoso. Ahora puedes iniciar sesión."
    
    except sqlite3.IntegrityError:
        return False, "❌ Error: El nombre de usuario ya existe."
    except Exception as e:
        return False, f"❌ Error de registro: {e}"
    finally:
        conn.close()

def login_user(username, password):
    """Verifica el usuario y la contraseña e inicia la sesión."""
    if not username or not password:
        return False, "❌ Usuario o contraseña no pueden estar vacíos."
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        user_id, password_hash = result
        if bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8')):
            st.session_state.username = username
            st.session_state.page = 'portfolio'
            return True, "✅ Inicio de sesión correcto."
        else:
            return False, "❌ Contraseña incorrecta."
    else:
        return False, "❌ Usuario no encontrado."

def logout():
    """Cierra la sesión del usuario actual."""
    st.session_state.username = None
    st.session_state.page = 'login'

# --- 4. FUNCIONES DE PORTFOLIO ---

def calculate_recommendation(avg_price_market, current_price):
    """Calcula la recomendación basada en el precio actual vs. promedio de 3 meses."""
    if current_price is None or avg_price_market is None:
        return "N/D"
    if current_price < avg_price_market*0.75:
        return "🟢 COMPRAR" 
    elif current_price > avg_price_market*1.25:
        return "🔴 VENDER"  
    else:
        return "🟡 MANTENER"

def load_portfolio():
    """Carga el portfolio, obtiene precios actuales y promedio de 3 meses."""
    username = st.session_state.username
    
    if not username:
        empty_df = pd.DataFrame(columns=['Valor', 'Acciones', 'Precio Compra (Unidad)', 'Costo Total Pagado', 'Valor Actual de Mercado', 'Precio Promedio (3M)', 'Precio Actual', 'Recomendación'])
        return empty_df, "⚠️ Error: No hay usuario logeado."

    try:
        user_id = get_user_id(username)
            
        conn = sqlite3.connect(DB_NAME)
        
        # CONSULTA SQL MODIFICADA para incluir el precio promedio de compra del usuario (avg_purchase_price)
        query = """
            SELECT 
                ticker, 
                SUM(shares) as total_shares, 
                SUM(shares * purchase_price) / SUM(shares) as avg_purchase_price
            FROM 
                portfolio
            WHERE 
                user_id = ?
            GROUP BY 
                ticker
        """
        portfolio_df = pd.read_sql_query(query, conn, params=(user_id,))
        conn.close()
        
        if portfolio_df.empty:
             return pd.DataFrame(columns=['Valor', 'Acciones', 'Precio Compra (Unidad)', 'Costo Total Pagado', 'Valor Actual de Mercado', 'Precio Promedio (3M)', 'Precio Actual', 'Recomendación']), "ℹ️ Tu portfolio está vacío. Añade valores para empezar."

        tickers = portfolio_df['ticker'].tolist()
        
        # Obtener datos de yfinance (90 días)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=90) 
        yf_data = yf.download(tickers, start=start_date.strftime('%Y-%m-%d'), 
                              end=end_date.strftime('%Y-%m-%d'), progress=False, threads=True,auto_adjust=False)
        
        current_prices = {}
        average_prices = {}
        nombrelargo = {}
        
        # Lógica para extraer precios y promedios de 3M
        if len(tickers) == 1:
            ticker = tickers[0]
            nombrelargo[ticker] = yf.Ticker(ticker).info.get('longName', ticker)
            if not yf_data.empty and 'Close' in yf_data:
                tickerp = yf.Ticker(ticker)
                precio_actual = tickerp.history(period="1d")["Close"].iloc[-1]
                current_prices[ticker] = precio_actual
                average_prices[ticker] = float(yf_data['Close'].mean())
                print(f"DEBUG 1: Ticker {ticker} - Current Price: {current_prices[ticker]}, Average Price: {average_prices[ticker]}")
            else:
                current_prices[ticker] = 0
                average_prices[ticker] = 0
                print(f"DEBUG 2: Ticker {ticker} - Current Price: {current_prices[ticker]}, Average Price: {average_prices[ticker]}")
        else:
            for ticker in tickers:
                try:
                    tickerp = yf.Ticker(ticker)
                    nombrelargo[ticker] = tickerp.info.get('longName', ticker)
                    precio_actual = tickerp.history(period="1d")["Close"].iloc[-1]
                    current_prices[ticker] = precio_actual
                    average_prices[ticker] = float(yf_data['Close'][ticker].mean())
                    print(f"DEBUG 3: Ticker {ticker} - Current Price: {current_prices[ticker]}, Average Price: {average_prices[ticker]}")
                except KeyError:
                    current_prices[ticker] = 0
                    average_prices[ticker] = 0
                    print(f"DEBUG 4: Ticker {ticker} - Current Price: {current_prices[ticker]}, Average Price: {average_prices[ticker]}")

        # Construir los resultados
        results = []
        for index, row in portfolio_df.iterrows():
            ticker = row['ticker']
            total_shares = int(row['total_shares']) # Aseguramos la definición aquí
            
            # DATOS DE COMPRA (SQLITE)
            avg_purchase_price = row['avg_purchase_price']
            total_cost_basis = total_shares * avg_purchase_price
            nombre_ticker = nombrelargo.get(ticker)

            # DATOS DE MERCADO (YFINANCE)
            avg_price_market = average_prices.get(ticker) 
            current_price = current_prices.get(ticker)
            current_market_value = total_shares * current_price if current_price is not None else 0
            
            # RECOMENDACIÓN
            recommendation = calculate_recommendation(avg_price_market, current_price)
            
            results.append({
                'Valor': nombre_ticker,
                'Ticker': ticker,
                'Acciones': total_shares,
                
                'Precio Compra (Unidad)': f"${avg_purchase_price:,.2f}",
                'Costo Total Pagado': f"${total_cost_basis:,.2f}",
                'Valor Actual de Mercado': f"${current_market_value:,.2f}",
                
                'Precio Promedio (3M)': f"${avg_price_market:,.2f}" if avg_price_market is not None else "N/D",
                'Precio Actual': f"${current_price:,.2f}" if current_price is not None else "N/D",
                'Recomendación': recommendation
            })

        final_df = pd.DataFrame(results)
        return final_df, f"✅ Portfolio cargado. Precios y promedio de 3M actualizados al {time.strftime('%H:%M:%S')}."

    except Exception as e:
        error_df = pd.DataFrame({'Valor': ['Error'], 'Acciones': [str(e)]})
        return error_df, f"❌ Error al cargar portfolio: {e}"

def add_to_portfolio(ticker, shares_str, price_str):
    """Añade una acción al portfolio del usuario logeado."""
    username = st.session_state.username
    
    if not username:
        return False, "❌ Error: Debes iniciar sesión para añadir valores."
    
    try:
        shares = int(shares_str)
        price = float(price_str)
        ticker = ticker.upper()
        if shares <= 0 or price <= 0:
            raise ValueError("Número de acciones y precio deben ser positivos.")
    except ValueError as e:
        return False, f"❌ Error de entrada: {e}"

    try:
        user_id = get_user_id(username)
        if user_id is None:
             return False, "❌ Error: Usuario no encontrado."

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute(
            "INSERT INTO portfolio (user_id, ticker, shares, purchase_price) VALUES (?, ?, ?, ?)",
            (user_id, ticker, shares, price)
        )
        conn.commit()
        conn.close()
        
        return True, f"✅ '{ticker}' ({shares} acc. a ${price:,.2f}) añadido a tu portfolio."
        
    except Exception as e:
        return False, f"❌ Error al añadir valor: {e}"

def delete_from_portfolio(ticker):
    """Elimina un ticker del portfolio del usuario logeado."""
    username = st.session_state.username
    
    if not username:
        return False, "❌ Error: Debes iniciar sesión para eliminar valores."
    
    try:
        ticker = ticker.upper()
        user_id = get_user_id(username)
        if user_id is None:
            return False, "❌ Error: Usuario no encontrado."
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Eliminar todas las entradas del ticker para este usuario
        cursor.execute(
            "DELETE FROM portfolio WHERE user_id = ? AND ticker = ?",
            (user_id, ticker)
        )
        conn.commit()
        conn.close()
        
        return True, f"✅ '{ticker}' ha sido eliminado de tu portfolio."
        
    except Exception as e:
        return False, f"❌ Error al eliminar valor: {e}"

# --- 5. FUNCIONES PARA MERCADOS Y LISTADOS DE ACCIONES ---

# Base de datos de mercados con sus índices
MARKETS_DATA = {
    "IBEX 35 (Madrid)": {
        "suffix": ".MC",
        "index": "^IBEX"
    },
    "CAC 40 (París)": {
        "suffix": ".PA",
        "index": "^FCHI"
    },
    "DAX (Alemania)": {
        "suffix": ".DE",
        "index": "^GDAXI"
    },
    "FTSE 100 (Londres)": {
        "suffix": ".L",
        "index": "^FTSE"
    },
    "S&P 500 (USA)": {
        "suffix": "",
        "index": "^GSPC"
    },
    "NASDAQ (USA Tech)": {
        "suffix": "",
        "index": "^IXIC"
    },
    "Nikkei 225 (Tokio)": {
        "suffix": ".T",
        "index": "^N225"
    },
    "SSE (Shanghái)": {
        "suffix": ".SS",
        "index": "000001.SS"
    },
    "Cryptomonedas (USD)": {
        "suffix": "-USD",
        "index": ""
    }
}

def get_stock_data_for_market(market_name):
    """Obtiene datos de precios y estadísticas para todas las acciones de un mercado."""
    market_info = MARKETS_DATA.get(market_name)
    if not market_info:
        return None, "❌ Mercado no encontrado."
    
    suffix = market_info.get("suffix", "")
    index_ticker = market_info.get("index", "")
    
    try:
        # Obtener el índice principal para extraer sus componentes
        st.info(f"⏳ Descargando lista de acciones del mercado {market_name}...")
        
        # Obtener datos históricos del índice
        end_date = datetime.now()
        start_date = end_date - timedelta(days=1)
        
        # Descargar el índice para verificar que existe (solo si proporcionado)
        index_data = None
        index_obj = None
        if index_ticker:
            try:
                index_data = yf.download(index_ticker, start=start_date.strftime('%Y-%m-%d'), 
                                        end=end_date.strftime('%Y-%m-%d'), progress=False, threads=False)
                # Obtener información del índice para acceder a sus componentes
                index_obj = yf.Ticker(index_ticker)
            except Exception as e:
                # No es crítico si no se puede descargar el índice; continuar con los tickers definidos
                st.warning(f"⚠️ No se pudo descargar/consultar el índice {index_ticker}: {e}")
        
        # Intentar obtener componentes del índice (varían según la fuente)
        # Para cada mercado, obtener la lista de componentes disponible
        tickers = []
        
        if market_name == "IBEX 35 (Madrid)":
            # Componentes del IBEX 35 - Lista completa actualizada
            tickers = ["ACS","ACX","AMS","ANA","ANE","BBVA","BKT","CABK",
                        "CLNX","COL","AENA","ELE","ENG","FDR","FER","GRF","IAG","IBE","IDR","ITX","LOG","MAP","MRL","MTS",
                        "NTGY","PUIG","RED","REP","ROVI","SAB",
                        "SAN","SCYR","SLR","TEF","UNI"]
        elif market_name == "CAC 40 (París)":
            tickers = ["OR", "CS", "AIR", "CA", "DPT", "EI", "FP", "GLE", "HO",
                      "KER", "LMT", "MC", "MIC", "ML", "MR", "MT", "NWL", "ORA",
                      "RI", "SAF", "SGO", "STM", "SU", "SW", "URW", "VIE", "WFT", "BN", "CDI", "EN"]
        elif market_name == "DAX (Alemania)":
            tickers = ["SAP", "SIE", "ADS", "BMW", "BAS", "BAY", "BEI", "CON",
                      "DAI", "DBK", "EXE", "FRE", "HEI", "HNR", "IFX", "LIN",
                      "MRK", "MUV2", "RWE", "VOW3", "ZAL", "ZIM", "VNA", "LHA", "RXO", "QIA", "PUM"]
        elif market_name == "FTSE 100 (Londres)":
            tickers = ["LLOY", "HSBA", "BARB", "GLEN", "RB", "AZN", "GSK", "ULVR",
                      "BP", "SHEL", "PPHM", "SMDS", "CRH", "RIO", "STAN",
                      "EVR", "REL", "KGF", "ICP", "LGEN", "BARC", "NWG", "PSH", "PNN", "SVT", "EXPN"]
        elif market_name == "S&P 500 (USA)":
            # Los 500 componentes del S&P 500 - aquí incluimos una lista representativa
            # En producción, se podría usar una API de SP Global o una fuente más completa
            tickers = ["AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA", "BRK.B",
                      "JPM", "JNJ", "V", "WMT", "XOM", "CVX", "MCD", "KO", "DIS", "BA", "GE",
                      "INTC", "AMD", "IBM", "CSCO", "ORCL", "CRM", "NFLX", "PYPL", "ADBE", "QCOM",
                      "MU", "AVGO", "TXN", "TSM", "ASML", "NOW", "INTU", "AMAT", "LRCX", "CDNS",
                      "SNPS", "ACN", "ADSK", "ADP", "ANSS", "APPF", "ASNA", "BAND", "BLDR", "BRKS",
                      "BX", "CACI", "CAL", "CASS", "CBPO", "CBSH", "CDAY", "CDW", "CFRT", "CHGG"]
        elif market_name == "NASDAQ (USA Tech)":
            tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "TSLA", "ASML",
                      "ADA", "AVGO", "CDNS", "CMCSA", "COST", "CTAS", "CSCO", "CRWD",
                      "FANG", "JBLU", "NFLX", "PYPL", "QCOM", "ROKU", "SNPS", "VRSK", "AMD", "INTC",
                      "AMAT", "LRCX", "MU", "MCHP", "MRVL", "NXPI", "ON", "PANW", "PD", "PLTR",
                      "PSTG", "SSNC", "STX", "STWD", "SWKS", "TCOM", "TEAM", "TEVA", "TKLF", "TLRY"]
        elif market_name == "Nikkei 225 (Tokio)":
            tickers = ["6758", "8306", "9984", "7203", "6861", "8031", "9433", "4503",
                      "4522", "5108", "8058", "9201", "9202", "6504", "8035", "9062",
                      "5411", "7267", "2768", "6273", "9605", "7211", "3405", "5201", "8604"]
        elif market_name == "SSE (Shanghái)":
            tickers = ["600000", "600004", "600008", "600009", "600010", "600011",
                      "600012", "600015", "600016", "600017", "600018", "600019",
                      "600020", "600021", "600022", "600023", "600028", "600030", "600031", "600033",
                      "600035", "600036", "600037", "600038", "600039", "600048", "600050"]
        elif market_name == "Cryptomonedas (USD)":
            # Principales criptomonedas (se les añadirá el sufijo '-USD' definido en MARKETS_DATA)
            tickers = [
                "BTC", "ETH", "BNB", "USDT", "USDC", "ADA", "XRP", "SOL",
                "DOGE", "DOT", "LTC", "AVAX", "MATIC", "LINK", "TRX", "ATOM"
            ]
        # Agregar suffix a los tickers
        full_tickers = [f"{ticker}{suffix}" for ticker in tickers if ticker]
        
        if not full_tickers:
            return None, "❌ No se encontraron acciones para este mercado."
        
        # Descargar datos para los últimos períodos
        end_date = datetime.now()
        start_date_1y = end_date - timedelta(days=365)
        start_date_6m = end_date - timedelta(days=180)
        start_date_3m = end_date - timedelta(days=90)
        
        # Descargar datos de 1 año para todo (en batches si hay muchos)
        batch_size = 20
        stock_list = []
        failed_tickers = []
        
        for batch_idx in range(0, len(full_tickers), batch_size):
            batch_tickers = full_tickers[batch_idx:batch_idx + batch_size]
            
            try:
                yf_data_1y = yf.download(batch_tickers, start=start_date_1y.strftime('%Y-%m-%d'), 
                                        end=end_date.strftime('%Y-%m-%d'), progress=False, threads=True)
                
                # Procesar cada ticker en el batch
                for ticker in batch_tickers:
                    try:
                        # Obtener datos históricos
                        if len(batch_tickers) == 1:
                            historical_data = yf_data_1y
                        else:
                            if ticker not in yf_data_1y['Close'].columns:
                                failed_tickers.append((ticker, "Sin datos históricos en yfinance"))
                                continue
                            historical_data = yf_data_1y['Close'][ticker]
                        
                        if historical_data is None or (hasattr(historical_data, 'empty') and historical_data.empty) or len(historical_data) == 0:
                            failed_tickers.append((ticker, "Datos históricos vacíos"))
                            continue
                        
                        # Obtener información de la acción
                        stock = yf.Ticker(ticker)
                        info = stock.info
                        
                        # Precios actuales
                        current_price = info.get('currentPrice') or info.get('regularMarketPrice')
                        
                        # Si no tenemos precio actual de yfinance, usamos el último cierre
                        if not current_price:
                            if len(batch_tickers) == 1:
                                current_price = yf_data_1y['Close'].iloc[-1] if not yf_data_1y.empty else None
                            else:
                                if ticker in yf_data_1y['Close'].columns:
                                    current_price = yf_data_1y['Close'][ticker].iloc[-1] if len(yf_data_1y['Close'][ticker]) > 0 else None
                        
                        if not current_price:
                            failed_tickers.append((ticker, "No hay precio actual disponible"))
                            continue
                        
                        # Calcular precios para diferentes períodos
                        stock_data_item = {
                            'ticker': ticker,
                            'name': info.get('longName', ticker),
                            'current_price': current_price
                        }
                        
                        # Procesar data por períodos
                        if len(batch_tickers) == 1:
                            data = yf_data_1y
                        else:
                            if ticker in yf_data_1y['Close'].columns:
                                data = yf_data_1y['Close'][ticker]
                            else:
                                failed_tickers.append((ticker, "No hay datos en el batch"))
                                continue
                        
                        # Último año
                        if len(data) > 0:
                            stock_data_item['price_1y_avg'] = data.mean()
                            stock_data_item['price_1y_min'] = data.min()
                            stock_data_item['price_1y_max'] = data.max()
                        else:
                            stock_data_item['price_1y_avg'] = stock_data_item['price_1y_min'] = stock_data_item['price_1y_max'] = None
                        
                        # Últimos 6 meses
                        data_6m = data[data.index >= start_date_6m]
                        if len(data_6m) > 0:
                            stock_data_item['price_6m_min'] = data_6m.min()
                            stock_data_item['price_6m_max'] = data_6m.max()
                        else:
                            stock_data_item['price_6m_min'] = stock_data_item['price_6m_max'] = None
                        
                        # Últimos 3 meses
                        data_3m = data[data.index >= start_date_3m]
                        if len(data_3m) > 0:
                            stock_data_item['price_3m_avg'] = data_3m.mean()
                            stock_data_item['price_3m_min'] = data_3m.min()
                            stock_data_item['price_3m_max'] = data_3m.max()
                        else:
                            stock_data_item['price_3m_avg'] = stock_data_item['price_3m_min'] = stock_data_item['price_3m_max'] = None
                        
                        stock_list.append(stock_data_item)
                    
                    except Exception as e:
                        failed_tickers.append((ticker, str(e)[:50]))
                        continue
            
            except Exception as e:
                for ticker in batch_tickers:
                    failed_tickers.append((ticker, f"Error en batch: {str(e)[:40]}"))
                continue
        
        if not stock_list:
            return None, "❌ No se pudieron obtener datos para este mercado."
        
        # Crear mensaje con información de acciones no encontradas
        message = f"✅ {len(stock_list)} acciones cargadas"
        if failed_tickers:
            message += f" ({len(failed_tickers)} no disponibles)"
        message += "."
        
        # Guardar info de tickers fallidos en session_state para mostrar después
        st.session_state.failed_tickers_info = {
            'market': market_name,
            'failed': failed_tickers
        }
        
        return stock_list, message
    
    except Exception as e:
        return None, f"❌ Error al cargar datos del mercado: {e}"

def format_price(price):
    """Formatea un precio para mostrar en la tabla."""
    if price is None:
        return "N/D"
    return f"${price:,.2f}"

def get_ticketnamesmarket(nombre_mercado):
    """
    Obtiene los nombres de tickers de servicios públicos online para un mercado específico.
    
    Parámetros:
    -----------
    nombre_mercado : str
        Nombre del mercado (ej: "IBEX 35 (Madrid)", "CAC 40 (París)", etc.)
    
    Retorna:
    --------
    list
        Lista de tickers (denominaciones clásicas) del mercado
    
    Nota: La función intenta obtener datos de múltiples fuentes:
    1. Wikipedia (para componentes del índice)
    2. Yahoo Finance (para datos del índice)
    3. Bases de datos predefinidas como fallback
    """
    
    try:
        # Mapeo de mercados a URLs de Wikipedia con componentes
        wikipedia_urls = {
            "IBEX 35 (Madrid)": "https://en.wikipedia.org/wiki/IBEX_35",
            "CAC 40 (París)": "https://en.wikipedia.org/wiki/CAC_40",
            "DAX (Alemania)": "https://en.wikipedia.org/wiki/DAX",
            "FTSE 100 (Londres)": "https://en.wikipedia.org/wiki/FTSE_100_Index",
            "S&P 500 (USA)": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            "NASDAQ (USA Tech)": "https://en.wikipedia.org/wiki/NASDAQ-100",
            "Nikkei 225 (Tokio)": "https://en.wikipedia.org/wiki/Nikkei_225",
            "SSE (Shanghái)": "https://en.wikipedia.org/wiki/Shanghai_Stock_Exchange"
        }
        
        tickers_list = []
        
        if nombre_mercado not in wikipedia_urls:
            return []
        
        url = wikipedia_urls[nombre_mercado]
        
        # Realizar petición a Wikipedia
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Estrategias de extracción según el mercado
        if nombre_mercado == "IBEX 35 (Madrid)":
            # Buscar la tabla con los componentes del IBEX 35
            tables = soup.find_all('table', {'class': 'wikitable'})
            for table in tables:
                rows = table.find_all('tr')
                for row in rows[1:]:  # Saltar encabezados
                    cells = row.find_all('td')
                    if len(cells) > 1:
                        ticker = cells[1].text.strip()
                        if ticker and len(ticker) <= 6:  # Los tickers tienen máximo 6 caracteres
                            tickers_list.append(ticker)
        
        elif nombre_mercado == "CAC 40 (París)":
            tables = soup.find_all('table', {'class': 'wikitable'})
            for table in tables:
                rows = table.find_all('tr')
                for row in rows[1:]:
                    cells = row.find_all('td')
                    if len(cells) > 0:
                        ticker = cells[0].text.strip()
                        if ticker and len(ticker) <= 6 and ticker.isalpha():
                            tickers_list.append(ticker)
        
        elif nombre_mercado == "DAX (Alemania)":
            tables = soup.find_all('table', {'class': 'wikitable'})
            for table in tables:
                rows = table.find_all('tr')
                for row in rows[1:]:
                    cells = row.find_all('td')
                    if len(cells) > 1:
                        ticker = cells[1].text.strip()
                        if ticker and len(ticker) <= 6 and ticker.isalpha():
                            tickers_list.append(ticker)
        
        elif nombre_mercado == "FTSE 100 (Londres)":
            tables = soup.find_all('table', {'class': 'wikitable'})
            for table in tables:
                rows = table.find_all('tr')
                for row in rows[1:]:
                    cells = row.find_all('td')
                    if len(cells) > 0:
                        ticker = cells[0].text.strip()
                        if ticker and len(ticker) <= 6:
                            tickers_list.append(ticker)
        
        elif nombre_mercado == "S&P 500 (USA)":
            # Para S&P 500, buscar tabla de constituents
            tables = soup.find_all('table', {'class': 'wikitable'})
            if tables:
                table = tables[0]
                rows = table.find_all('tr')
                for row in rows[1:]:
                    cells = row.find_all('td')
                    if len(cells) > 0:
                        ticker = cells[0].text.strip()
                        if ticker and len(ticker) <= 5 and ticker.isalpha():
                            tickers_list.append(ticker)
        
        elif nombre_mercado == "NASDAQ (USA Tech)":
            # Buscar tabla con componentes del NASDAQ-100
            tables = soup.find_all('table', {'class': 'wikitable'})
            for table in tables:
                rows = table.find_all('tr')
                for row in rows[1:]:
                    cells = row.find_all('td')
                    if len(cells) > 0:
                        ticker = cells[0].text.strip()
                        if ticker and len(ticker) <= 5 and ticker.isalpha():
                            tickers_list.append(ticker)
        
        elif nombre_mercado == "Nikkei 225 (Tokio)":
            # Para Nikkei, extraer códigos numéricos
            tables = soup.find_all('table', {'class': 'wikitable'})
            for table in tables:
                rows = table.find_all('tr')
                for row in rows[1:]:
                    cells = row.find_all('td')
                    if len(cells) > 0:
                        code = cells[0].text.strip()
                        # Los códigos del Nikkei son numéricos (4-5 dígitos)
                        if code and code.isdigit() and len(code) <= 5:
                            tickers_list.append(code)
        
        elif nombre_mercado == "SSE (Shanghái)":
            # Para SSE, extraer códigos de acciones chinas
            tables = soup.find_all('table', {'class': 'wikitable'})
            for table in tables:
                rows = table.find_all('tr')
                for row in rows[1:]:
                    cells = row.find_all('td')
                    if len(cells) > 0:
                        code = cells[0].text.strip()
                        # Los códigos de SSE son numéricos (6 dígitos)
                        if code and code.isdigit() and len(code) == 6:
                            tickers_list.append(code)
        
        # Eliminar duplicados y ordenar
        tickers_list = sorted(list(set(tickers_list)))
        
        # Si se obtuvieron tickers, retornarlos
        if tickers_list:
            return tickers_list
        
        # Fallback: retornar lista vacía si no se pudo scrapear
        return []
    
    except requests.exceptions.Timeout:
        # Si timeout, retornar lista vacía
        return []
    except requests.exceptions.ConnectionError:
        # Si error de conexión, retornar lista vacía
        return []
    except Exception as e:
        # Para cualquier otro error, retornar lista vacía
        return []

def prepare_chart_data(df_portfolio):
    """Prepara datos para gráficas a partir del dataframe del portfolio."""
    if df_portfolio.empty:
        return None
    
    try:
        # Extraer valores numéricos de los strings con formato
        chart_data = []
        for idx, row in df_portfolio.iterrows():
            ticker = row['Ticker']
            # Convertir strings de precio a floats
            market_value = float(row['Valor Actual de Mercado'].replace('$', '').replace(',', ''))
            cost_value = float(row['Costo Total Pagado'].replace('$', '').replace(',', ''))
            ganancia = market_value - cost_value
            
            chart_data.append({
                'Ticker': ticker, 
                'Valor Mercado': market_value,
                'Ganancia': ganancia
            })
        
        return pd.DataFrame(chart_data).set_index('Ticker')
    except Exception as e:
        st.warning(f"⚠️ Error al preparar datos de gráficas: {e}")
        return None

# --- 5. INTERFAZ DE STREAMLIT ---

st.markdown("## 🔒 SmartFinancial: Gestión de Portfolio Personal")
st.markdown("Aviso: versión experimental para gestión básica de portfolios. Usa con precaución.")

# Pantalla de LOGIN / REGISTRO
if st.session_state.page == 'login':
    st.markdown("### Acceso a SmartFinancial")
    
    # Tabs para cambiar entre Login y Registro
    tab1, tab2 = st.tabs(["🔑 Iniciar Sesión", "📝 Registrar"])
    
    with tab1:
        st.markdown("#### Iniciar Sesión")
        login_username = st.text_input("Usuario", key="login_user")
        login_password = st.text_input("Contraseña", type="password", key="login_pass")
        
        if st.button("Acceder", key="login_btn"):
            success, message = login_user(login_username, login_password)
            if success:
                st.success(message)
                st.rerun()
            else:
                st.error(message)
    
    with tab2:
        st.markdown("#### Registrar Nuevo Usuario")
        reg_username = st.text_input("Nuevo Usuario", key="reg_user")
        reg_password = st.text_input("Nueva Contraseña", type="password", key="reg_pass")
        
        if st.button("Registrar", key="reg_btn"):
            success, message = register_user(reg_username, reg_password)
            if success:
                st.success(message)
            else:
                st.error(message)

# Pantalla de PORTFOLIO
elif st.session_state.page == 'portfolio':
    st.markdown(f"### 📈 Mi Portfolio de Valores - **{st.session_state.username}**")
    
    # Botones de navegación en la parte superior
    col1, col2, col3 = st.columns([1, 1, 10])
    with col1:
        if st.button("👤 Mi Cuenta"):
            st.session_state.page = 'user_panel'
            st.rerun()
    with col2:
        if st.button("🚪 Cerrar Sesión"):
            logout()
            st.rerun()
    
    # Tabs para Ver Portfolio y Añadir Valor
    tab1, tab2, tab3 = st.tabs(["Ver Portfolio", "Añadir Valor", "Eliminar Valor"])
    
    with tab1:
        if st.button("🔄 Recargar Precios Actuales", key="refresh_btn"):
            st.rerun()
        
        portfolio_df, status_msg = load_portfolio()
        st.info(status_msg)
        st.dataframe(portfolio_df, use_container_width=True)

        # ← AQUÍ: añades esto (debajo de st.dataframe)
        st.markdown("---")
        
        # Calcular totales
        costo_total_pagado = sum([float(row['Costo Total Pagado'].replace('$', '').replace(',', '')) for _, row in portfolio_df.iterrows()])
        valor_actual_portfolio = sum([float(row['Valor Actual de Mercado'].replace('$', '').replace(',', '')) for _, row in portfolio_df.iterrows()])
        perdida_ganancia = valor_actual_portfolio - costo_total_pagado
        
        # Mostrar métricas
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Importe Total Pagado", f"${costo_total_pagado:,.2f}")
        with col2:
            st.metric("Valor Actual Portfolio", f"${valor_actual_portfolio:,.2f}")
        with col3:
            color = "inverse" if perdida_ganancia >= 0 else "off"
            st.metric("Pérdida/Ganancia", f"${perdida_ganancia:,.2f}", delta=f"{((perdida_ganancia/costo_total_pagado)*100):.2f}%" if costo_total_pagado > 0 else "0%", delta_color=color)
        
        # Mostrar gráficas si hay datos
        if not portfolio_df.empty and len(portfolio_df) > 0:
            st.markdown("---")
            st.markdown("### 📊 Análisis Visual del Portfolio")
            
            chart_data = prepare_chart_data(portfolio_df)
            if chart_data is not None:
                col1, col2 = st.columns(2)
                with col1:
                    st.bar_chart(chart_data)
                with col2:
                    st.line_chart(chart_data[['Ganancia']])
    
    with tab2:
        selected_market = st.selectbox(
            "Elige un mercado bursátil",
            options=list(MARKETS_DATA.keys()),
            key="market_select"
        )
        
        if selected_market:
            if st.button("📈 Cargar Acciones del Mercado", key="load_market_btn"):
                with st.spinner(f"Cargando acciones de {selected_market}..."):
                    stock_list, load_message = get_stock_data_for_market(selected_market)
                    st.session_state.current_market_data = stock_list
                    st.session_state.current_market_name = selected_market
                    st.info(load_message)
            
            # Mostrar listado de acciones si están disponibles
            if 'current_market_data' in st.session_state and st.session_state.current_market_data:
                st.markdown(f"**Acciones disponibles en {st.session_state.current_market_name}:**")
                
                # Crear tabla con datos formateados
                display_data = []
                for stock in st.session_state.current_market_data:
                    # Valores numéricos (pueden ser None)
                    current_price = stock.get('current_price')
                    price_3m_max = stock.get('price_3m_max')
                    price_6m_max = stock.get('price_6m_max')
                    price_1y_max = stock.get('price_1y_max')
                    price_3m_min = stock.get('price_3m_min')
                    price_6m_min = stock.get('price_6m_min')
                    price_1y_min = stock.get('price_1y_min')

                    # Lógica Compra a Corto: SÍ si precio actual < máx 3M o < máx 6M
                    compra_corto = False
                    if current_price is not None:
                        if (price_3m_max is not None and current_price < (price_3m_min+price_3m_max)/2) or (price_6m_max is not None and current_price < (price_6m_min+price_6m_max)/2):
                            compra_corto = True

                    # Lógica Compra a Largo: SÍ si precio actual < máx 1A
                    compra_largo = False
                    if current_price is not None and price_1y_max is not None and current_price < (price_1y_min+price_1y_max)/2:
                        compra_largo = True

                    display_data.append({
                        'Ticker': stock['ticker'],
                        'Nombre': stock['name'][:40],  # Limitar longitud
                        'Precio Actual': format_price(current_price),
                        'Promedio 3M': format_price(stock.get('price_3m_avg')),
                        'Mín. 3M': format_price(price_3m_min),
                        'Máx. 3M': format_price(price_3m_max),
                        'Mín. 6M': format_price(price_6m_min),
                        'Máx. 6M': format_price(price_6m_max),
                        'Mín. 1A': format_price(price_1y_min),
                        'Máx. 1A': format_price(price_1y_max),
                        # Mostrar con emojis: verde para SÍ, rojo para NO
                        'CC': "🟢SÍ" if compra_corto else "🔴NO",
                        'CL': "🟢SÍ" if compra_largo else "🔴NO"
                    })
                
                df_display = pd.DataFrame(display_data)
                st.dataframe(df_display, use_container_width=True, height=400)
                
                # Mostrar información sobre acciones no disponibles
                if 'failed_tickers_info' in st.session_state and st.session_state.failed_tickers_info['failed']:
                    with st.expander("ℹ️ Acciones no disponibles"):
                        st.markdown(f"**{len(st.session_state.failed_tickers_info['failed'])} acciones no se pudieron cargar:**")
                        failed_df = pd.DataFrame(st.session_state.failed_tickers_info['failed'], columns=['Ticker', 'Motivo'])
                        st.dataframe(failed_df, use_container_width=True)
                        st.markdown("**Posibles motivos:**")
                        st.markdown("""
                        - **Sin datos históricos en yfinance**: El ticker no existe o no está disponible en yfinance
                        - **Datos históricos vacíos**: No hay suficientes datos históricos (requiere al menos datos de 1 año)
                        - **No hay precio actual disponible**: yfinance no pudo obtener el precio actual de la acción
                        - **Sin datos en el batch**: Error al procesar los datos del mercado
                        """)
                
                st.markdown("---")
                st.markdown("##### Selecciona una acción para añadir a tu portfolio:")
                
                # Selector de acción
                ticker_options = [stock['ticker'] for stock in st.session_state.current_market_data]
                selected_ticker = st.selectbox(
                    "Acción a añadir",
                    options=ticker_options,
                    key="market_ticker_select",
                    format_func=lambda x: f"{x} - {[s['name'] for s in st.session_state.current_market_data if s['ticker'] == x][0][:50]}"
                )
                
                # Información de la acción seleccionada
                if selected_ticker:
                    selected_stock = next((s for s in st.session_state.current_market_data if s['ticker'] == selected_ticker), None)
                    if selected_stock:
                        col1, col2 = st.columns(2)
                        with col1:
                            st.metric("Precio Actual", format_price(selected_stock['current_price']))
                        with col2:
                            st.metric("Promedio 3 Meses", format_price(selected_stock.get('price_3m_avg')))
                
                # Inputs para cantidad y precio
                col1, col2 = st.columns(2)
                with col1:
                    market_shares = st.number_input("Número de Acciones", min_value=1, value=1, step=1, key="market_shares")
                with col2:
                    # Usar el precio actual de la acción como sugerencia
                    if selected_ticker:
                        selected_stock = next((s for s in st.session_state.current_market_data if s['ticker'] == selected_ticker), None)
                        market_price = st.number_input("Precio de Compra por Acción", min_value=0.01, value=0.01, step=0.01, key="market_price")
                    else:
                        market_price = st.number_input("Precio de Compra por Acción", min_value=0.01, value=0.01, step=0.01, key="market_price_default")
                
                if st.button("➕ Añadir a Portfolio desde Mercado", key="add_from_market_btn"):
                    if selected_ticker and market_shares > 0 and market_price > 0:
                        success, message = add_to_portfolio(selected_ticker, str(int(market_shares)), str(market_price))
                        if success:
                            st.success(message)
                            st.rerun()
                        else:
                            st.error(message)
                    else:
                        st.error("❌ Por favor completa todos los campos correctamente.")
        
        st.markdown("---")
        
    
    with tab3:        
        # Obtener lista de tickers del usuario
        portfolio_df, _ = load_portfolio()
        
        if not portfolio_df.empty and len(portfolio_df) > 0:
            tickers_list = portfolio_df['Valor'].tolist()
            
            delete_ticker = st.selectbox(
                "Selecciona el ticker a eliminar",
                options=tickers_list,
                key="delete_ticker_select"
            )
            
            # Mostrar información del valor a eliminar
            if delete_ticker:
                ticker_info = portfolio_df[portfolio_df['Valor'] == delete_ticker]
                if not ticker_info.empty:
                    try:
                        st.info(f"**{delete_ticker}** - Acciones: {ticker_info['Acciones'].values[0]} | Valor Mercado: {ticker_info['Valor Actual de Mercado'].values[0]}")
                    except Exception:
                        st.info(f"**{delete_ticker}** - Acciones: {ticker_info['Acciones'].values[0]}")
            
            col1, col2 = st.columns([1, 1])
            with col1:
                if st.button("🗑️ Eliminar Valor", key="delete_btn", type="secondary"):
                    if delete_ticker:
                        success, message = delete_from_portfolio(delete_ticker)
                        if success:
                            st.success(message)
                            st.rerun()
                        else:
                            st.error(message)
            with col2:
                st.warning("⚠️ Esta acción es irreversible")
        else:
            st.info("Tu portfolio está vacío. Primero añade valores para poder eliminarlos.")

# Pantalla de PANEL DE USUARIO
elif st.session_state.page == 'user_panel':
    st.markdown(f"### 👤 Panel de Usuario y Configuración - **{st.session_state.username}**")
    
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("⬅️ Volver al Portfolio", key="back_portfolio_btn"):
            st.session_state.page = 'portfolio'
            st.rerun()
    with col2:
        if st.button("🚪 Cerrar Sesión", key="logout_panel_btn"):
            logout()
            st.rerun()
    
    st.info("Aquí podría ir la configuración de alertas o datos personales.")
    st.markdown(f"**Usuario:** {st.session_state.username}")
    st.markdown(f"**Fecha/Hora:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")