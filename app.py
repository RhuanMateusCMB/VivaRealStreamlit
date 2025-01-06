import streamlit as st
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from datetime import datetime
from supabase import create_client

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

    def __init__(self, url_base):
        self.url_base = url_base
        self.navegador = None
        self.wait = None

    def iniciar_navegador(self):
        self.navegador = self.configurar_navegador()
        self.wait = WebDriverWait(self.navegador, 10)

    def fechar_navegador(self):
        if self.navegador:
            self.navegador.quit()

    def coletar_dados(self, num_paginas=1):
        try:
            self.iniciar_navegador()
            todos_imoveis = []

            for pagina in range(1, num_paginas + 1):
                url_pagina = f"{self.url_base}?pagina={pagina}"
                self.navegador.get(url_pagina)
                
                # Aguarda o carregamento dos imóveis
                self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "property-card__content")))
                
                # Coleta dados dos imóveis
                cards = self.navegador.find_elements(By.CLASS_NAME, "property-card__content")
                
                for card in cards:
                    try:
                        titulo = card.find_element(By.CLASS_NAME, "property-card__title").text
                        area = card.find_element(By.CLASS_NAME, "property-card__detail-area").text
                        preco = card.find_element(By.CLASS_NAME, "property-card__price").text
                        
                        imovel = {
                            'titulo': titulo,
                            'area': area,
                            'preco': preco,
                            'data_coleta': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        }
                        
                        todos_imoveis.append(imovel)
                    except Exception as e:
                        st.warning(f"Erro ao coletar dados de um imóvel: {e}")
                        continue

            return pd.DataFrame(todos_imoveis)
        
        except Exception as e:
            st.error(f"Erro durante a coleta: {e}")
            return None
        
        finally:
            self.fechar_navegador()

def main():
    st.title("Scraper VivaReal")
    
    # Inicializa o cliente Supabase
    supabase = create_client(
        st.secrets["supabase_url"],
        st.secrets["supabase_key"]
    )
    
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
            scraper = ScraperVivaReal(url)
            df = scraper.coletar_dados(num_paginas=num_paginas)
            
            if df is not None:
                try:
                    # Limpa tabela existente
                    supabase.table("imoveis").delete().neq('id', 0).execute()
                    
                    # Insere novos dados
                    registros = df.to_dict('records')
                    supabase.table("imoveis").insert(registros).execute()
                    st.success("Dados salvos no Supabase com sucesso!")
                    
                    # Gera arquivo Excel para download
                    nome_arquivo = f"lotes_eusebio_vivareal_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
                    df.to_excel(nome_arquivo, index=False)
                    
                    with open(nome_arquivo, 'rb') as f:
                        st.download_button(
                            label="Baixar dados em Excel",
                            data=f,
                            file_name=nome_arquivo,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                    
                    # Mostra preview dos dados
                    st.dataframe(df.head())
                    
                except Exception as e:
                    st.error(f"Erro ao salvar dados: {e}")
            else:
                st.error("Falha na coleta de dados")

if __name__ == "__main__":
    main()
