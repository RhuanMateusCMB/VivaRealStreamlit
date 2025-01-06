import streamlit as st
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time
from datetime import datetime
import logging
from typing import Optional, List, Dict
from dataclasses import dataclass
from supabase import create_client

@dataclass
class ConfiguracaoScraper:
    tempo_espera: int = 20
    pausa_rolagem: int = 3
    espera_carregamento: int = 5
    url_base: str = ""
    tentativas_max: int = 3

class SupabaseManager:
    def __init__(self):
        self.url = st.secrets["SUPABASE_URL"]
        self.key = st.secrets["SUPABASE_KEY"]
        self.supabase = create_client(self.url, self.key, options={'schema': 'public'})

    def limpar_tabela(self):
        self.supabase.table('imoveis').delete().neq('id', 0).execute()

    def inserir_dados(self, df):
        registros = df.to_dict('records')
        self.supabase.table('imoveis').insert(registros).execute()

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
        navegador.execute_cdp_cmd('Network.setUserAgentOverride', {"userAgent": 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'})
        navegador.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        return navegador

    def _capturar_localizacao(self, navegador: webdriver.Chrome) -> tuple:
        try:
            time.sleep(self.config.espera_carregamento)
            localizacao_elemento = WebDriverWait(navegador, self.config.tempo_espera).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '.search-input-location'))
            )
            texto_localizacao = localizacao_elemento.text.strip()
            partes = texto_localizacao.split(' - ')
            if len(partes) == 2:
                localidades = partes[0]
                estado = partes[1].strip()
                return localidades, estado

            self.logger.info(f"Localização capturada: {localidades} - {estado}")
            return localidades, estado

        except Exception as e:
            try:
                url_parts = navegador.current_url.split('/')
                for i, part in enumerate(url_parts):
                    if part in ['acre', 'alagoas', 'amapa', 'amazonas', 'bahia', 'ceara', 'distrito-federal',
                              'espirito-santo', 'goias', 'maranhao', 'mato-grosso', 'mato-grosso-do-sul',
                              'minas-gerais', 'para', 'paraiba', 'parana', 'pernambuco', 'piaui',
                              'rio-de-janeiro', 'rio-grande-do-norte', 'rio-grande-do-sul', 'rondonia',
                              'roraima', 'santa-catarina', 'sao-paulo', 'sergipe', 'tocantins']:
                        estado = part.upper()[:2]
                        if i + 1 < len(url_parts):
                            next_part = url_parts[i + 1]
                            if 'fortaleza' in next_part:
                                localidades = 'Eusébio, Fortaleza'
                            else:
                                localidades = url_parts[i + 1].replace('-', ' ').title()
                            self.logger.info(f"Localização capturada da URL: {localidades} - {estado}")
                            return localidades, estado

            except Exception as inner_e:
                self.logger.error(f"Erro na segunda tentativa de capturar localização: {str(inner_e)}")

            self.logger.error(f"Erro ao capturar localização: {str(e)}")
            return None, None

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

    def coletar_dados(self, num_paginas: int = 5) -> Optional[pd.DataFrame]:
        todos_dados: List[Dict] = []
        id_global = 0
        progresso = st.progress(0)
        status = st.empty()

        try:
            navegador = self._configurar_navegador()
            espera = WebDriverWait(navegador, self.config.tempo_espera)
            navegador.get(self.config.url_base)

            localidade, estado = self._capturar_localizacao(navegador)
            if not localidade or not estado:
                self.logger.error("Não foi possível capturar localidade ou estado")
                return None

            for pagina in range(1, num_paginas + 1):
                try:
                    status.text(f"Processando página {pagina}/{num_paginas}")
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
            return None

        finally:
            navegador.quit()

def main():
    st.title("Scraper VivaReal")
    
    url = st.text_input(
        "URL do VivaReal",
        placeholder="https://www.vivareal.com.br/..."
    )

    num_paginas = st.slider(
        "Número de páginas para coletar",
        min_value=1,
        max_value=34,
        value=5
    )

    if st.button("Iniciar Coleta"):
        if not url.startswith("https://www.vivareal.com.br/"):
            st.error("URL inválida. A URL deve começar com 'https://www.vivareal.com.br/'")
        else:
            status_text = st.empty()
            
            config = ConfiguracaoScraper()
            config.url_base = url
            scraper = ScraperVivaReal(config)
            
            try:
                df = scraper.coletar_dados(num_paginas=num_paginas)
                if df is not None:
                    st.success("Dados coletados com sucesso!")
                    st.dataframe(df)
                    
                    try:
                        db = SupabaseManager()
                        status_text.text("Limpando tabela existente...")
                        db.limpar_tabela()
                        status_text.text("Inserindo novos dados...")
                        db.inserir_dados(df)
                        st.success("Dados salvos no Supabase!")
                    except Exception as e:
                        st.error(f"Erro ao salvar no Supabase: {str(e)}")
                else:
                    st.error("Falha na coleta de dados")
            except Exception as e:
                st.error(f"Erro durante a execução: {str(e)}")

if __name__ == "__main__":
    main()
