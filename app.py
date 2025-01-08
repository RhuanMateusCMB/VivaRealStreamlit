# Bibliotecas para interface web
import streamlit as st

# Bibliotecas para manipulação de dados
import pandas as pd

# Bibliotecas Selenium para web scraping
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# Bibliotecas utilitárias
import time
from datetime import datetime
import logging
from typing import Optional, List, Dict
from dataclasses import dataclass

# Biblioteca para conexão com Supabase
from supabase import create_client

# Configuração da página Streamlit
st.set_page_config(
    page_title="CMB - Capital",
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
    tempo_espera: int = 30  # Aumentar de 20 para 30
    pausa_rolagem: int = 5  # Aumentar de 3 para 5
    espera_carregamento: int = 10  # Aumentar de 5 para 10
    url_base: str = "https://www.vivareal.com.br/venda/ceara/eusebio/lote-terreno_residencial/#onde=,Cear%C3%A1,Eus%C3%A9bio,,,,,city,BR%3ECeara%3ENULL%3EEusebio,-14.791623,-39.283324,&itl_id=1000183&itl_name=vivareal_-_botao-cta_buscar_to_vivareal_resultado-pesquisa"
    tentativas_max: int = 3

class SupabaseManager:
    def __init__(self):
        self.url = st.secrets["SUPABASE_URL"]
        self.key = st.secrets["SUPABASE_KEY"]
        self.supabase = create_client(self.url, self.key)

    def limpar_tabela(self):
        self.supabase.table('teste').delete().neq('id', 0).execute()

    def inserir_dados(self, df):
        # Primeiro, pegamos o maior ID atual na tabela
        result = self.supabase.table('teste').select('id').order('id.desc').limit(1).execute()
        ultimo_id = result.data[0]['id'] if result.data else 0
        
        # Ajustamos os IDs do novo dataframe
        df['id'] = df['id'].apply(lambda x: x + ultimo_id)
        
        # Convertemos a coluna data_coleta para o formato correto
        df['data_coleta'] = pd.to_datetime(df['data_coleta']).dt.strftime('%Y-%m-%d')
        
        # Agora inserimos os dados
        registros = df.to_dict('records')
        self.supabase.table('teste').insert(registros).execute()

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

            # Usando webdriver_manager para gerenciar o ChromeDriver automaticamente
            #from webdriver_manager.chrome import ChromeDriverManager
            #from selenium.webdriver.chrome.service import Service as ChromeService
            
            #service = ChromeService(ChromeDriverManager().install())
            #navegador = webdriver.Chrome(service=service, options=opcoes_chrome)
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
        for tentativa in range(3):  # 3 tentativas para cada imóvel
            try:
                # Funções auxiliares para conversão
                def converter_preco(texto: str) -> float:
                    try:
                        numero = texto.replace('R$', '').replace('.', '').replace(',', '.').strip()
                        return float(numero)
                    except (ValueError, AttributeError):
                        self.logger.warning(f"Erro ao converter preço: {texto}")
                        return 0.0

                def converter_area(texto: str) -> float:
                    try:
                        numero = texto.replace('m²', '').replace(',', '.').strip()
                        return float(numero)
                    except (ValueError, AttributeError):
                        self.logger.warning(f"Erro ao converter área: {texto}")
                        return 0.0

                # Aguardar elementos específicos com timeout individual
                wait = WebDriverWait(imovel, 10)
                
                # Extrair preço com retry
                try:
                    preco_elemento = wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'div.property-card__price'))
                    )
                    preco_texto = preco_elemento.text
                except Exception as e:
                    self.logger.warning(f"Erro ao extrair preço na tentativa {tentativa + 1}: {e}")
                    time.sleep(2)
                    continue

                # Extrair área com retry
                try:
                    area_elemento = wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'span.property-card__detail-area'))
                    )
                    area_texto = area_elemento.text
                except Exception as e:
                    self.logger.warning(f"Erro ao extrair área na tentativa {tentativa + 1}: {e}")
                    time.sleep(2)
                    continue

                # Converter valores
                preco = converter_preco(preco_texto)
                area = converter_area(area_texto)
                
                # Calcular preço por m² com validação
                if area > 0:
                    preco_m2 = round(preco / area, 2)
                else:
                    preco_m2 = 0.0
                    self.logger.warning(f"Área zero encontrada para imóvel ID {id_global}")

                # Extrair outros dados com tratamento de erro
                try:
                    titulo = wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'span.property-card__title'))
                    ).text
                except Exception:
                    titulo = "Título não disponível"
                    self.logger.warning(f"Título não encontrado para imóvel ID {id_global}")

                try:
                    endereco = wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'span.property-card__address'))
                    ).text
                except Exception:
                    endereco = "Endereço não disponível"
                    self.logger.warning(f"Endereço não encontrado para imóvel ID {id_global}")

                try:
                    link = wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'a.property-card__content-link'))
                    ).get_attribute('href')
                except Exception:
                    link = ""
                    self.logger.warning(f"Link não encontrado para imóvel ID {id_global}")

                # Montar dicionário de dados
                dados = {
                    'id': id_global,
                    'titulo': titulo,
                    'endereco': endereco,
                    'area_m2': area,
                    'preco_real': preco,
                    'preco_m2': preco_m2,
                    'link': link,
                    'pagina': pagina,
                    'data_coleta': datetime.now().strftime("%Y-%m-%d"),
                    'estado': '',
                    'localidade': ''
                }

                # Validar dados críticos
                if preco == 0 or area == 0:
                    self.logger.warning(f"Dados incompletos para imóvel ID {id_global}: Preço={preco}, Área={area}")
                    if tentativa < 2:  # Se não for a última tentativa
                        time.sleep(2)
                        continue

                return dados

            except Exception as e:
                self.logger.error(f"Erro ao extrair dados do imóvel na tentativa {tentativa + 1}: {str(e)}")
                if tentativa < 2:  # Se não for a última tentativa
                    time.sleep(2)
                    continue
                return None

        self.logger.error(f"Falha em todas as tentativas de extrair dados do imóvel ID {id_global}")
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
        st.title("🏗️ Coleta Informações Gerais Terrenos - Eusebio, CE")
        
        st.markdown("""
        <div style='text-align: center; padding: 1rem 0;'>
            <p style='font-size: 1.2em; color: #666;'>
                Coleta de dados de terrenos à venda em Eusébio, Ceará
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        # Botão para o Looker Studio
        st.markdown("""
        <div style='text-align: center; padding: 1rem 0;'>
            <a href='https://lookerstudio.google.com/reporting/105d6f24-d91f-4953-875c-3d4cc45a8fda' target='_blank'>
                <button style='
                    background-color: #FF4B4B;
                    color: white;
                    padding: 12px 24px;
                    border: none;
                    border-radius: 8px;
                    font-size: 18px;
                    cursor: pointer;
                    box-shadow: 0 2px 5px rgba(0,0,0,0.2);
                    transition: all 0.3s ease;
                    margin: 10px 0;
                '>
                    📊 Acessar Dashboard no Looker Studio
                </button>
            </a>
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
