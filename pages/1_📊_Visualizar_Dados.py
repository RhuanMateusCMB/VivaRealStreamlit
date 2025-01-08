import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
from datetime import datetime

# Configuração da página
st.set_page_config(
    page_title="Visualização dos Dados - CMB Capital",
    page_icon="📊",
    layout="wide"
)

# Classe para gerenciar conexão com Supabase
class SupabaseManager:
    def __init__(self):
        self.url = st.secrets["SUPABASE_URL"]
        self.key = st.secrets["SUPABASE_KEY"]
        self.supabase = create_client(self.url, self.key)

    def obter_dados(self):
        try:
            response = self.supabase.table('teste').select("*").execute()
            return pd.DataFrame(response.data)
        except Exception as e:
            st.error(f"Erro ao obter dados do Supabase: {str(e)}")
            return None

def main():
    # Título e descrição
    st.title("📊 Visualização de Dados - Terrenos em Eusébio")
    
    st.markdown("""
    <div style='text-align: center; padding: 1rem 0;'>
        <p style='font-size: 1.2em; color: #666;'>
            Análise e visualização dos dados coletados sobre terrenos em Eusébio, Ceará
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Inicializar conexão com Supabase
    db = SupabaseManager()
    df = db.obter_dados()

    if df is not None and not df.empty:
        # Convertendo a coluna de data
        df['data_coleta'] = pd.to_datetime(df['data_coleta'])
        
        # Métricas principais
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total de Registros", len(df))
        with col2:
            preco_medio = df['preco_real'].mean()
            st.metric("Preço Médio", f"R$ {preco_medio:,.2f}")
        with col3:
            area_media = df['area_m2'].mean()
            st.metric("Área Média", f"{area_media:,.2f} m²")
        with col4:
            preco_m2_medio = df['preco_m2'].mean()
            st.metric("Preço/m² Médio", f"R$ {preco_m2_medio:,.2f}")

        # Filtros
        st.markdown("### 🔍 Filtros")
        col1, col2 = st.columns(2)
        
        with col1:
            min_preco = float(df['preco_real'].min())
            max_preco = float(df['preco_real'].max())
            preco_range = st.slider(
                "Faixa de Preço (R$)",
                min_value=min_preco,
                max_value=max_preco,
                value=(min_preco, max_preco)
            )
            
        with col2:
            min_area = float(df['area_m2'].min())
            max_area = float(df['area_m2'].max())
            area_range = st.slider(
                "Faixa de Área (m²)",
                min_value=min_area,
                max_value=max_area,
                value=(min_area, max_area)
            )

        # Aplicar filtros
        df_filtrado = df[
            (df['preco_real'].between(preco_range[0], preco_range[1])) &
            (df['area_m2'].between(area_range[0], area_range[1]))
        ]

        # Visualizações
        st.markdown("### 📈 Visualizações")
        
        # Gráfico de dispersão: Preço x Área
        fig_scatter = px.scatter(
            df_filtrado,
            x='area_m2',
            y='preco_real',
            title='Relação entre Área e Preço',
            labels={'area_m2': 'Área (m²)', 'preco_real': 'Preço (R$)'},
            hover_data=['endereco', 'preco_m2']
        )
        st.plotly_chart(fig_scatter, use_container_width=True)

        # Distribuição de preços por m²
        fig_hist = px.histogram(
            df_filtrado,
            x='preco_m2',
            title='Distribuição de Preços por m²',
            labels={'preco_m2': 'Preço por m² (R$)', 'count': 'Quantidade'},
            nbins=30
        )
        st.plotly_chart(fig_hist, use_container_width=True)

        # Tabela de dados
        st.markdown("### 📋 Dados Detalhados")
        
        # Formatando o DataFrame para exibição
        df_display = df_filtrado.copy()
        df_display['preco_real'] = df_display['preco_real'].apply(lambda x: f'R$ {x:,.2f}')
        df_display['preco_m2'] = df_display['preco_m2'].apply(lambda x: f'R$ {x:,.2f}')
        df_display['area_m2'] = df_display['area_m2'].apply(lambda x: f'{x:,.2f} m²')
        
        st.dataframe(
            df_display,
            use_container_width=True
        )

        # Botão de download
        csv = df_filtrado.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 Baixar dados filtrados em CSV",
            data=csv,
            file_name=f'terrenos_eusebio_filtrados_{datetime.now().strftime("%Y%m%d")}.csv',
            mime='text/csv',
        )

    else:
        st.warning("Não há dados disponíveis para visualização.")

    # Rodapé
    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown("""
        <div style='text-align: center; padding: 1rem 0; color: #666;'>
            <p>Desenvolvido com ❤️ por Rhuan Mateus - CMB Capital</p>
            <p style='font-size: 0.8em;'>Última atualização: Janeiro 2025</p>
        </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
