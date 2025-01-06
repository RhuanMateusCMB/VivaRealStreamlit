import streamlit as st
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from datetime import datetime
from config import ConfiguracaoScraper
from database import SupabaseManager

class ScraperVivaReal:
    def configurar_navegador(self) -> webdriver.Chrome:
        opcoes_chrome = Options()
        opcoes_chrome.add_argument('--headless=new')
        opcoes_chrome.add_argument('--window-size=1920,1080')
        opcoes_chrome.add_argument('--disable-gpu')
        opcoes_chrome.add_argument('--no-sandbox')
        opcoes_chrome.add_argument('--disable-dev-shm-usage')
        opcoes_chrome.add_argument(f'user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        opcoes_chrome.add_argument('--disable-blink-features=AutomationControlled')
        opcoes_chrome.add_experimental_option('excludeSwitches', ['enable-automation'])
        opcoes_chrome.add_experimental_option('useAutomationExtension', False)
        return webdriver.Chrome(options=opcoes_chrome)

    # [Resto dos métodos da classe permanecem iguais]

def main():
    st.title("Scraper VivaReal")
    
    url = st.text_input(
        "Digite a URL do VivaReal:",
        placeholder="https://www.vivareal.com.br/..."
    )
    
    num_paginas = st.number_input(
        "Número de páginas para coletar:",
        min_value=1,
        max_value=34,
        value=1
    )
    
    if st.button("Iniciar Coleta"):
        if not url.startswith("https://www.vivareal.com.br/"):
            st.error("URL inválida. A URL deve começar com 'https://www.vivareal.com.br/'")
            return
            
        with st.spinner("Coletando dados..."):
            config = ConfiguracaoScraper()
            config.url_base = url
            scraper = ScraperVivaReal(config)
            df = scraper.coletar_dados(num_paginas=num_paginas)
            
            if df is not None:
                try:
                    db = SupabaseManager()
                    st.info("Limpando tabela existente...")
                    db.limpar_tabela()
                    st.info("Inserindo novos dados...")
                    db.inserir_dados(df)
                    st.success("Dados salvos no Supabase com sucesso!")
                    
                    # Gerar arquivo Excel para download
                    nome_arquivo = f"lotes_eusebio_vivareal_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
                    df.to_excel(nome_arquivo, index=False)
                    
                    with open(nome_arquivo, 'rb') as f:
                        st.download_button(
                            label="Baixar dados em Excel",
                            data=f,
                            file_name=nome_arquivo,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                        
                    # Mostrar preview dos dados
                    st.dataframe(df.head())
                    
                except Exception as e:
                    st.error(f"Erro ao salvar dados: {e}")
            else:
                st.error("Falha na coleta de dados")

if __name__ == "__main__":
    main()
