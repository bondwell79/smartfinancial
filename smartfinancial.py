import streamlit as st
import yfinance as yf
import pandas as pd
import sqlite3
import bcrypt
import time
from datetime import datetime, timedelta

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
    if current_price < avg_price_market:
        return "🟢 COMPRAR" 
    elif current_price > avg_price_market:
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
                              end=end_date.strftime('%Y-%m-%d'), progress=False, threads=True)
        
        current_prices = {}
        average_prices = {}
        
        # Lógica para extraer precios y promedios de 3M
        if len(tickers) == 1:
            ticker = tickers[0]
            if not yf_data.empty and 'Close' in yf_data:
                current_prices[ticker] = yf_data['Close'].iloc[-1] 
                average_prices[ticker] = yf_data['Close'].mean()
            else:
                current_prices[ticker] = None
                average_prices[ticker] = None
        else:
            for ticker in tickers:
                try:
                    current_prices[ticker] = yf_data['Close'][ticker].iloc[-1]
                    average_prices[ticker] = yf_data['Close'][ticker].mean()
                except KeyError:
                    current_prices[ticker] = None
                    average_prices[ticker] = None

        # Construir los resultados
        results = []
        for index, row in portfolio_df.iterrows():
            ticker = row['ticker']
            total_shares = int(row['total_shares']) # Aseguramos la definición aquí
            
            # DATOS DE COMPRA (SQLITE)
            avg_purchase_price = row['avg_purchase_price']
            total_cost_basis = total_shares * avg_purchase_price

            # DATOS DE MERCADO (YFINANCE)
            avg_price_market = average_prices.get(ticker) 
            current_price = current_prices.get(ticker)
            current_market_value = total_shares * current_price if current_price is not None else 0
            
            # RECOMENDACIÓN
            recommendation = calculate_recommendation(avg_price_market, current_price)
            
            results.append({
                'Valor': ticker,
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

def prepare_chart_data(df_portfolio):
    """Prepara datos para gráficas a partir del dataframe del portfolio."""
    if df_portfolio.empty:
        return None
    
    try:
        # Extraer valores numéricos de los strings con formato
        chart_data = []
        for idx, row in df_portfolio.iterrows():
            ticker = row['Valor']
            # Convertir strings de precio a floats (ej: "$1,234.56" -> 1234.56)
            market_value = float(row['Valor Actual de Mercado'].replace('$', '').replace(',', ''))
            chart_data.append({'Ticker': ticker, 'Valor Mercado': market_value})
        
        return pd.DataFrame(chart_data).set_index('Ticker')
    except Exception as e:
        st.warning(f"⚠️ Error al preparar datos de gráficas: {e}")
        return None

# --- 5. INTERFAZ DE STREAMLIT ---

st.markdown("## 🔒 SmartFinancial: Gestión de Portfolio Personal")

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
                    st.area_chart(chart_data)
    
    with tab2:
        st.markdown("#### Añadir Nuevo Valor a Portfolio")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            add_ticker = st.text_input("Símbolo Bursátil (Ticker)", placeholder="Ej: AAPL", key="add_ticker")
        with col2:
            add_shares = st.text_input("Número de Acciones", placeholder="Ej: 10", key="add_shares")
        with col3:
            add_price = st.text_input("Precio de Compra por Acción", placeholder="Ej: 150.75", key="add_price")
        
        if st.button("➕ Añadir a Portfolio", key="add_btn"):
            if add_ticker and add_shares and add_price:
                success, message = add_to_portfolio(add_ticker, add_shares, add_price)
                if success:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)
            else:
                st.error("❌ Por favor completa todos los campos.")
    
    with tab3:
        st.markdown("#### Eliminar Valor del Portfolio")
        
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
                    st.info(f"**{delete_ticker}** - Acciones: {ticker_info['Acciones'].values[0]} | Valor Mercado: {ticker_info['Valor Actual de Mercado'].values[0]}")
            
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