import streamlit as st
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import time
from datetime import datetime
import logging
from typing import Optional, List, Dict
from dataclasses import dataclass
from supabase import create_client

# Configuração da página Streamlit
st.set_page_config(
    page_title="Scraper VivaReal - Terrenos em Eusébio",
    page_icon="🏗️",
    layout="wide"
)

# Estilo CSS personalizado
st.markdown("""
    <style>
    .stButton>button {
        width: 100%;
        height: 3em;
        font-size: 20px;
    }
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    </style>
    """, unsafe_allow_html=True)

@dataclass
class ConfiguracaoScraper:
    tempo_espera: int = 20
    pausa_rolagem: int = 3
    espera_carregamento: int = 5
    url_base: str = "https://www.vivareal.com.br/venda/ceara/eusebio/lote-terreno_residencial/#onde=,Cear%C3%A1,Eus%C3%A9bio,,,,,city,BR%3ECeara%3ENULL%3EEusebio,-14.791623,-39.283324,&itl_id=1000183&itl_name=vivareal_-_botao-cta_buscar_to_vivareal_resultado-pesquisa"
    tentativas_max: int = 3

class SupabaseManager:
    def __init__(self):
        self.url = st.secrets["SUPABASE_URL"]
        self.key = st.secrets["SUPABASE_KEY"]
        self.supabase = create_client(self.url, self.key)

    def limpar_tabela(self):
        self.supabase.table('imoveisatual').delete().neq('id', 0).execute()

    def inserir_dados(self, df):
        # Primeiro, pegamos o maior ID atual na tabela
        result = self.supabase.table('imoveisatual').select('id').order('id.desc').limit(1).execute()
        ultimo_id = result.data[0]['id'] if result.data else 0
        
        # Ajustamos os IDs do novo dataframe
        df['id'] = df['id'].apply(lambda x: x + ultimo_id)
        
        # Convertemos a coluna data_coleta para o formato correto
        df['data_coleta'] = pd.to_datetime(df['data_coleta']).dt.strftime('%Y-%m-%d')
        
        # Agora inserimos os dados
        registros = df.to_dict('records')
        self.supabase.table('imoveisatual').insert(registros).execute()

class ScraperVivaReal:
    def __init__(self, config: ConfiguracaoScraper):
        self.config = config
        self.logger = self._configurar_logger()

    @staticmethod
    def _configurar_logger() -> logging.Logger:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        return logging.getLogger(__name__)

    def _configurar_navegador(self) -> webdriver.Chrome:
        try:
            opcoes_chrome = Options()
            opcoes_chrome.add_argument('--headless=new')
            opcoes_chrome.add_argument('--no-sandbox')
            opcoes_chrome.add_argument('--disable-dev-shm-usage')
            opcoes_chrome.add_argument('--disable-gpu')
            opcoes_chrome.add_argument('--window-size=1920,1080')
            opcoes_chrome.add_argument('--disable-blink-features=AutomationControlled')
            opcoes_chrome.add_argument('--enable-cookies')
            opcoes_chrome.binary_location = "/usr/bin/chromium"
            
            service = Service("/usr/bin/chromedriver")
            navegador = webdriver.Chrome(service=service, options=opcoes_chrome)
            navegador.execute_cdp_cmd('Network.setUserAgentOverride', {
                "userAgent": 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })
            navegador.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            return navegador
        except Exception as e:
            self.logger.error(f"Erro ao configurar navegador: {str(e)}")
            return None

    def _capturar_localizacao(self, navegador: webdriver.Chrome) -> tuple:
        if navegador is None:
            return None, None
            
        try:
            # Aguarda a página carregar completamente
            time.sleep(self.config.espera_carregamento * 2)  # Aumentando o tempo de espera
            
            # Primeira tentativa: buscar pelo seletor CSS
            try:
                localizacao_elemento = WebDriverWait(navegador, self.config.tempo_espera).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '.search-input-location'))
                )
                texto_localizacao = localizacao_elemento.text.strip()
                if texto_localizacao:
                    partes = texto_localizacao.split(' - ')
                    if len(partes) == 2:
                        return partes[0], partes[1].strip()
            except Exception:
                pass
    
            # Segunda tentativa: extrair da URL
            url_parts = navegador.current_url.split('/')
            for i, part in enumerate(url_parts):
                if part == 'ceara':
                    return 'Eusébio', 'CE'
                    
            # Terceira tentativa: valor padrão para Eusébio
            return 'Eusébio', 'CE'
    
        except Exception as e:
            self.logger.error(f"Erro ao capturar localização: {str(e)}")
            return 'Eusébio', 'CE'

    def _rolar_pagina(self, navegador: webdriver.Chrome) -> None:
        for _ in range(3):
            navegador.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(self.config.pausa_rolagem)

    def _extrair_dados_imovel(self, imovel: webdriver.remote.webelement.WebElement,
                    id_global: int, pagina: int) -> Optional[Dict]:
        try:
            preco_texto = imovel.find_element(By.CSS_SELECTOR, 'div.property-card__price').text
            area_texto = imovel.find_element(By.CSS_SELECTOR, 'span.property-card__detail-area').text

            def converter_preco(texto: str) -> float:
                numero = texto.replace('R$', '').replace('.', '').replace(',', '.').strip()
                try:
                    return float(numero)
                except ValueError:
                    return 0.0

            def converter_area(texto: str) -> float:
                numero = texto.replace('m²', '').replace(',', '.').strip()
                try:
                    return float(numero)
                except ValueError:
                    return 0.0

            preco = converter_preco(preco_texto)
            area = converter_area(area_texto)
            preco_m2 = round(preco / area, 2) if area > 0 else 0.0

            return {
                'id': id_global,
                'titulo': imovel.find_element(By.CSS_SELECTOR, 'span.property-card__title').text,
                'endereco': imovel.find_element(By.CSS_SELECTOR, 'span.property-card__address').text,
                'area_m2': area,
                'preco_real': preco,
                'preco_m2': preco_m2,
                'link': imovel.find_element(By.CSS_SELECTOR, 'a.property-card__content-link').get_attribute('href'),
                'pagina': pagina,
                'data_coleta': datetime.now().strftime("%Y-%m-%d"),
                'estado': '',
                'localidade': ''
            }
        except Exception as e:
            self.logger.error(f"Erro ao extrair dados: {str(e)}")
            return None

    def _encontrar_botao_proxima(self, espera: WebDriverWait) -> Optional[webdriver.remote.webelement.WebElement]:
        seletores = [
            "//button[contains(., 'Próxima página')]",
            "//a[contains(., 'Próxima página')]",
            "//button[@title='Próxima página']"
        ]

        for seletor in seletores:
            try:
                return espera.until(EC.element_to_be_clickable((By.XPATH, seletor)))
            except:
                continue
        return None

    def coletar_dados(self, num_paginas: int = 10) -> Optional[pd.DataFrame]:
        navegador = None
        todos_dados: List[Dict] = []
        id_global = 0
        progresso = st.progress(0)
        status = st.empty()
    
        try:
            navegador = self._configurar_navegador()
            if navegador is None:
                st.error("Não foi possível inicializar o navegador")
                return None
    
            espera = WebDriverWait(navegador, self.config.tempo_espera)
            navegador.get(self.config.url_base)
            
            # Aguarda a página carregar
            time.sleep(self.config.espera_carregamento)
    
            localidade, estado = self._capturar_localizacao(navegador)
            if not localidade or not estado:
                st.error("Não foi possível capturar a localização")
                return None

            for pagina in range(1, num_paginas + 1):
                try:
                    status.text(f"⏳ Processando página {pagina}/{num_paginas}")
                    progresso.progress(pagina / num_paginas)
                    
                    time.sleep(self.config.espera_carregamento)
                    self._rolar_pagina(navegador)

                    imoveis = espera.until(EC.presence_of_all_elements_located(
                        (By.CSS_SELECTOR, 'div[data-type="property"]')))

                    if not imoveis:
                        self.logger.warning(f"Sem imóveis na página {pagina}")
                        break

                    for imovel in imoveis:
                        id_global += 1
                        if dados := self._extrair_dados_imovel(imovel, id_global, pagina):
                            dados['estado'] = estado
                            dados['localidade'] = localidade
                            todos_dados.append(dados)

                    if pagina < num_paginas:
                        botao_proxima = self._encontrar_botao_proxima(espera)
                        if not botao_proxima:
                            break
                        navegador.execute_script("arguments[0].click();", botao_proxima)

                except Exception as e:
                    self.logger.error(f"Erro na página {pagina}: {str(e)}")
                    continue

            return pd.DataFrame(todos_dados) if todos_dados else None

        except Exception as e:
            self.logger.error(f"Erro crítico: {str(e)}")
            st.error(f"Erro durante a coleta: {str(e)}")
            return None

        finally:
            if navegador:
                try:
                    navegador.quit()
                except Exception as e:
                    self.logger.error(f"Erro ao fechar navegador: {str(e)}")

def main():
    try:
        # Inicializar session_state
        if 'df' not in st.session_state:
            st.session_state.df = None
        if 'dados_salvos' not in st.session_state:
            st.session_state.dados_salvos = False
            
        # Títulos e descrição
        st.title("🏗️ Scraper VivaReal - Terrenos em Eusébio")
        
        st.markdown("""
        <div style='text-align: center; padding: 1rem 0;'>
            <p style='font-size: 1.2em; color: #666;'>
                Coleta de dados de terrenos à venda em Eusébio, Ceará
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        # Informações sobre a coleta
        st.info("""
        ℹ️ **Informações sobre a coleta:**
        - Serão coletadas 10 páginas de resultados
        - Apenas terrenos em Eusébio/CE
        - Após a coleta, você pode escolher se deseja salvar os dados no banco
        """)
        
        # Separador visual
        st.markdown("<hr>", unsafe_allow_html=True)
        
        # Botão centralizado
        if st.button("🚀 Iniciar Coleta", type="primary", use_container_width=True):
            st.session_state.dados_salvos = False  # Reset estado de salvamento
            with st.spinner("Iniciando coleta de dados..."):
                config = ConfiguracaoScraper()
                scraper = ScraperVivaReal(config)
                
                st.session_state.df = scraper.coletar_dados()
                
        # Se temos dados coletados
        if st.session_state.df is not None and not st.session_state.df.empty:
            df = st.session_state.df  # Para facilitar a referência
            
            # Métricas principais
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total de Imóveis", len(df))
            with col2:
                preco_medio = df['preco_real'].mean()
                st.metric("Preço Médio", f"R$ {preco_medio:,.2f}")
            with col3:
                area_media = df['area_m2'].mean()
                st.metric("Área Média", f"{area_media:,.2f} m²")
            
            st.success("✅ Dados coletados com sucesso!")
            
            # Exibição dos dados
            st.markdown("### 📊 Dados Coletados")
            st.dataframe(
                df.style.format({
                    'preco_real': 'R$ {:,.2f}',
                    'preco_m2': 'R$ {:,.2f}',
                    'area_m2': '{:,.2f} m²'
                }),
                use_container_width=True
            )
            
            # Confirmação para salvar no banco
            if not st.session_state.dados_salvos:
                st.markdown("### 💾 Salvar no Banco de Dados")
                col1, col2 = st.columns(2)
                
                with col1:
                    if st.button("✅ Sim, salvar dados", key='save_button', use_container_width=True):
                        try:
                            with st.spinner("💾 Salvando dados no banco..."):
                                db = SupabaseManager()
                                db.inserir_dados(df)
                                st.session_state.dados_salvos = True
                                st.success("✅ Dados salvos no banco de dados!")
                                st.balloons()
                        except Exception as e:
                            st.error(f"❌ Erro ao salvar no banco de dados: {str(e)}")
                
                with col2:
                    if st.button("❌ Não salvar", key='dont_save_button', use_container_width=True):
                        st.session_state.dados_salvos = True
                        st.info("📝 Dados não foram salvos no banco.")
            
            # Botão de download
            csv = df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="📥 Baixar dados em CSV",
                data=csv,
                file_name=f'terrenos_eusebio_{datetime.now().strftime("%Y%m%d")}.csv',
                mime='text/csv',
            )
            
            if st.session_state.dados_salvos:
                st.info("🔄 Para iniciar uma nova coleta, atualize a página.")
                
        # Rodapé
        st.markdown("<hr>", unsafe_allow_html=True)
        st.markdown("""
            <div style='text-align: center; padding: 1rem 0; color: #666;'>
                <p>Desenvolvido com ❤️ por Rhuan Mateus - CMB Capital</p>
                <p style='font-size: 0.8em;'>Última atualização: Janeiro 2025</p>
            </div>
        """, unsafe_allow_html=True)
        
    except Exception as e:
        st.error(f"❌ Erro inesperado: {str(e)}")
        st.error("Por favor, atualize a página e tente novamente.")

if __name__ == "__main__":
    main()
