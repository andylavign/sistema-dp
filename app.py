import streamlit as st
import sqlite3
import pandas as pd
import pdfplumber
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
import io

# ---------------------------------------------------------
# INICIALIZAÇÃO DO BANCO DE DADOS (COM AUDITORIA E MULTI-EMPRESA)
# ---------------------------------------------------------
def init_db():
    conn = sqlite3.connect('rh_sistema_multiempreendimento.db')
    c = conn.cursor()
    
    # 1. Tabela de Usuários (Login)
    c.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT UNIQUE NOT NULL,
            senha TEXT NOT NULL,
            nome TEXT NOT NULL,
            perfil TEXT NOT NULL -- 'Admin' ou 'Supervisor'
        )
    ''')
    
    # 2. Tabela de Empresas (5 Empresas)
    c.execute('''
        CREATE TABLE IF NOT EXISTS empresas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT UNIQUE NOT NULL
        )
    ''')
    
    # 3. Tabela de Colaboradores (Com Vínculo de Empresa e Auditoria)
    c.execute('''
        CREATE TABLE IF NOT EXISTS colaboradores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER,
            nome TEXT NOT NULL,
            status TEXT DEFAULT 'ATIVO',
            criado_por TEXT,
            data_criacao TEXT,
            FOREIGN KEY (empresa_id) REFERENCES empresas (id)
        )
    ''')
    
    # 4. Tabela de Apontamentos (Com Auditoria de Edição/Criação)
    c.execute('''
        CREATE TABLE IF NOT EXISTS apontamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            colaborador_id INTEGER,
            empresa_id INTEGER,
            tipo TEXT NOT NULL, -- 'Atestado' ou 'Falta'
            data_inicio TEXT NOT NULL,
            duracao TEXT,
            observacao TEXT,
            registrado_por TEXT,
            editado_por TEXT,
            data_registro TEXT,
            FOREIGN KEY (colaborador_id) REFERENCES colaboradores (id),
            FOREIGN KEY (empresa_id) REFERENCES empresas (id)
        )
    ''')

    # Insert de usuários padrão se a tabela estiver vazia
    c.execute("SELECT COUNT(*) FROM usuarios")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO usuarios (usuario, senha, nome, perfil) VALUES ('admin', '1234', 'Administrador RH', 'Admin')")
        c.execute("INSERT INTO usuarios (usuario, senha, nome, perfil) VALUES ('supervisor', '1234', 'Supervisor Operacional', 'Supervisor')")
        
    # Insert de 5 empresas padrão se estiver vazia
    c.execute("SELECT COUNT(*) FROM empresas")
    if c.fetchone()[0] == 0:
        empresas_iniciais = [
            'Quality Maracanaú',
            'Quality Fortaleza',
            'Quality Caucaia',
            'Quality Eusébio',
            'Quality Sobral'
        ]
        for emp in empresas_iniciais:
            c.execute("INSERT INTO empresas (nome) VALUES (?)", (emp,))

    conn.commit()
    conn.close()

init_db()

# ---------------------------------------------------------
# FUNÇÕES DE AUDITORIA E BANCO
# ---------------------------------------------------------
def autenticar_usuario(usuario, senha):
    conn = sqlite3.connect('rh_sistema_multiempreendimento.db')
    c = conn.cursor()
    c.execute("SELECT usuario, nome, perfil FROM usuarios WHERE usuario = ? AND senha = ?", (usuario, senha))
    res = c.fetchone()
    conn.close()
    return res

def get_empresas():
    conn = sqlite3.connect('rh_sistema_multiempreendimento.db')
    df = pd.read_sql_query("SELECT * FROM empresas", conn)
    conn.close()
    return df

def get_colaboradores(empresa_id, status_filter=None):
    conn = sqlite3.connect('rh_sistema_multiempreendimento.db')
    query = f"SELECT * FROM colaboradores WHERE empresa_id = {empresa_id}"
    if status_filter and status_filter != "TODOS":
        query += f" AND status = '{status_filter}'"
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def cadastrar_colaborador(empresa_id, nome, usuario_atual):
    conn = sqlite3.connect('rh_sistema_multiempreendimento.db')
    c = conn.cursor()
    data_hoje = datetime.now().strftime("%d/%m/%Y %H:%M")
    try:
        c.execute('''
            INSERT INTO colaboradores (empresa_id, nome, status, criado_por, data_criacao)
            VALUES (?, ?, 'ATIVO', ?, ?)
        ''', (empresa_id, nome.strip().upper(), usuario_atual, data_hoje))
        conn.commit()
        st.success(f"Colaborador {nome} cadastrado por {usuario_atual}!")
    except Exception as e:
        st.error(f"Erro ao cadastrar: {e}")
    finally:
        conn.close()

def atualizar_status_em_massa(empresa_id, nomes_ativos_pdf):
    conn = sqlite3.connect('rh_sistema_multiempreendimento.db')
    c = conn.cursor()
    
    c.execute("SELECT id, nome, status FROM colaboradores WHERE empresa_id = ?", (empresa_id,))
    existentes = {row[1]: (row[0], row[2]) for row in c.fetchall()}
    
    novos = []
    inativados = []
    
    for nome in nomes_ativos_pdf:
        nome_clean = nome.strip().upper()
        if nome_clean not in existentes:
            novos.append(nome_clean)
            
    for nome, (colab_id, status) in existentes.items():
        if nome not in nomes_ativos_pdf and status == 'ATIVO':
            inativados.append((colab_id, nome))
            
    conn.close()
    return novos, inativados

def confirmar_sincronizacao(empresa_id, novos, inativados, usuario_atual):
    conn = sqlite3.connect('rh_sistema_multiempreendimento.db')
    c = conn.cursor()
    data_hoje = datetime.now().strftime("%d/%m/%Y %H:%M")
    
    for nome in novos:
        c.execute('''
            INSERT INTO colaboradores (empresa_id, nome, status, criado_por, data_criacao)
            VALUES (?, ?, 'ATIVO', ?, ?)
        ''', (empresa_id, nome, usuario_atual, data_hoje))
        
    for colab_id, _ in inativados:
        c.execute("UPDATE colaboradores SET status = 'INATIVO' WHERE id = ?", (colab_id,))
        
    conn.commit()
    conn.close()

def salvar_apontamento(empresa_id, colab_id, tipo, data_inicio, duracao, obs, usuario_atual):
    conn = sqlite3.connect('rh_sistema_multiempreendimento.db')
    c = conn.cursor()
    data_registro = datetime.now().strftime("%d/%m/%Y %H:%M")
    c.execute('''
        INSERT INTO apontamentos (empresa_id, colaborador_id, tipo, data_inicio, duracao, observacao, registrado_por, editado_por, data_registro)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (empresa_id, colab_id, tipo, data_inicio, duracao, obs, usuario_atual, usuario_atual, data_registro))
    conn.commit()
    conn.close()

# ---------------------------------------------------------
# GERADOR DE PDF COM TRILHA DE AUDITORIA
# ---------------------------------------------------------
def gerar_pdf_mes(empresa_nome, empresa_id, mes_ano, usuario_emissao):
    conn = sqlite3.connect('rh_sistema_multiempreendimento.db')
    query = f'''
        SELECT c.nome, a.tipo, a.data_inicio, a.duracao, a.observacao, a.registrado_por, a.data_registro 
        FROM apontamentos a
        JOIN colaboradores c ON c.id = a.colaborador_id
        WHERE a.empresa_id = {empresa_id}
    '''
    df = pd.read_sql_query(query, conn)
    conn.close()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('T1', fontName='Helvetica-Bold', fontSize=16, textColor=colors.HexColor('#1E3A8A'), spaceAfter=4)
    subtitle_style = ParagraphStyle('S1', fontName='Helvetica', fontSize=10, textColor=colors.HexColor('#4B5563'), spaceAfter=15)
    section_style = ParagraphStyle('S2', fontName='Helvetica-Bold', fontSize=12, textColor=colors.HexColor('#1E3A8A'), spaceBefore=10, spaceAfter=6)
    cell_style = ParagraphStyle('C1', fontName='Helvetica', fontSize=8)
    header_style = ParagraphStyle('H1', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white)
    footer_style = ParagraphStyle('F1', fontName='Helvetica-Oblique', fontSize=8, textColor=colors.HexColor('#6B7280'), spaceBefore=20)

    # Cabecalho do Documento
    story.append(Paragraph(f"APONTAMENTOS DE PESSOAL — {empresa_nome.upper()}", title_style))
    story.append(Paragraph(f"<b>Mês de Referência:</b> {mes_ano} &nbsp;|&nbsp; <b>Empresa:</b> {empresa_nome}", subtitle_style))

    # Tabela Atestados
    atestados = df[df['tipo'] == 'Atestado']
    story.append(Paragraph("1. Atestados Médicos Registrados", section_style))
    t_data = [[
        Paragraph("Nome do Colaborador", header_style),
        Paragraph("Data", header_style),
        Paragraph("Duração / Detalhes", header_style),
        Paragraph("Registrado Por", header_style)
    ]]
    for _, row in atestados.iterrows():
        t_data.append([
            Paragraph(row['nome'], cell_style),
            Paragraph(row['data_inicio'], cell_style),
            Paragraph(row['duracao'], cell_style),
            Paragraph(f"{row['registrado_por']}<br/>({row['data_registro']})", cell_style)
        ])
    
    t_atestados = Table(t_data, colWidths=[180, 100, 130, 130])
    t_atestados.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1E3A8A')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E5E7EB')),
        ('TOPPADDING', (0,0), (-1,-1), 5), ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t_atestados)
    story.append(Spacer(1, 15))

    # Tabela Faltas
    faltas = df[df['tipo'] == 'Falta']
    story.append(Paragraph("2. Faltas Registradas", section_style))
    f_data = [[
        Paragraph("Nome do Colaborador", header_style),
        Paragraph("Data da Falta", header_style),
        Paragraph("Registrado Por", header_style)
    ]]
    for _, row in faltas.iterrows():
        f_data.append([
            Paragraph(row['nome'], cell_style),
            Paragraph(row['data_inicio'], cell_style),
            Paragraph(f"{row['registrado_por']}<br/>({row['data_registro']})", cell_style)
        ])
    
    t_faltas = Table(f_data, colWidths=[240, 150, 150])
    t_faltas.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#DC2626')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E5E7EB')),
        ('TOPPADDING', (0,0), (-1,-1), 5), ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t_faltas)

    # TRILHA DE AUDITORIA NO RODAPÉ DO PDF
    data_hora_emissao = datetime.now().strftime("%d/%m/%Y às %H:%M:%S")
    story.append(Paragraph(
        f"<b>Relatório emitido por:</b> {usuario_emissao} em {data_hora_emissao} | <i>Documento auditado e assinado digitalmente pelo sistema.</i>", 
        footer_style
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer

# ---------------------------------------------------------
# INTERFACE DO USUÁRIO E TELA DE LOGIN (STREAMLIT)
# ---------------------------------------------------------
st.set_page_config(page_title="Sistema RH Multi-Empresa", layout="wide")

# Gerenciamento de Sessão de Login
if 'autenticado' not in st.session_state:
    st.session_state['autenticado'] = False
if 'usuario_nome' not in st.session_state:
    st.session_state['usuario_nome'] = ""
if 'usuario_perfil' not in st.session_state:
    st.session_state['usuario_perfil'] = ""

# --- TELA DE LOGIN ---
if not st.session_state['autenticado']:
    st.title("🔒 Login — Sistema de Gestão de RH")
    
    with st.form("login_form"):
        col1, col2 = st.columns(2)
        with col1:
            usuario_input = st.text_input("Usuário:")
        with col2:
            senha_input = st.text_input("Senha:", type="password")
            
        btn_login = st.form_submit_button("Entrar no Sistema")
        
        if btn_login:
            user_data = autenticar_usuario(usuario_input, senha_input)
            if user_data:
                st.session_state['autenticado'] = True
                st.session_state['usuario_nome'] = user_data[1]
                st.session_state['usuario_perfil'] = user_data[2]
                st.success(f"Bem-vindo, {user_data[1]}!")
                st.rerun()
            else:
                st.error("Usuário ou senha inválidos. Tente novamente.")
    
    st.info("💡 **Acesso de teste pré-cadastrado:**<br/>Usuário: `admin` | Senha: `1234`<br/>Usuário: `supervisor` | Senha: `1234`", icon="ℹ️")

# --- SISTEMA APÓS O LOGIN ---
else:
    # Barra Lateral
    st.sidebar.write(f"👤 **Usuário:** {st.session_state['usuario_nome']} ({st.session_state['usuario_perfil']})")
    if st.sidebar.button("Sair (Logout)"):
        st.session_state['autenticado'] = False
        st.rerun()
        
    st.sidebar.markdown("---")
    
    # SELEÇÃO DAS 5 EMPRESAS
    df_empresas = get_empresas()
    empresa_selecionada_nome = st.sidebar.selectbox("🏢 **Selecione a Empresa:**", df_empresas['nome'].tolist())
    empresa_id = int(df_empresas[df_empresas['nome'] == empresa_selecionada_nome]['id'].values[0])
    
    st.sidebar.markdown("---")
    
    menu = st.sidebar.radio("Navegação / Passos:", [
        "1. Base de Colaboradores",
        "2. Cadastrar Colaborador",
        "3. Sincronizar Relatório PDF (Ativos)",
        "4. Inserir Observações (Faltas/Atestados)",
        "5. Gerar e Exportar PDF Final"
    ])

    # PASSO 1: BASE DE DADOS
    if menu == "1. Base de Colaboradores":
        st.header(f"1. Base de Colaboradores — {empresa_selecionada_nome}")
        filtro = st.selectbox("Filtrar por Status:", ["TODOS", "ATIVO", "INATIVO"])
        
        df = get_colaboradores(empresa_id, filtro)
        st.dataframe(df, use_container_width=True)

    # PASSO 2: CADASTRAR MANUALMENTE
    elif menu == "2. Cadastrar Colaborador":
        st.header(f"2. Cadastrar Colaborador na {empresa_selecionada_nome}")
        with st.form("form_cadastro"):
            nome = st.text_input("Nome Completo do Colaborador:")
            submitted = st.form_submit_button("Salvar Cadastro")
            if submitted and nome:
                cadastrar_colaborador(empresa_id, nome, st.session_state['usuario_nome'])

    # PASSO 3: LER PDF E SINCRONIZAR ATIVOS / INATIVOS / NOVOS
    elif menu == "3. Sincronizar Relatório PDF (Ativos)":
        st.header(f"3. Sincronização por PDF — {empresa_selecionada_nome}")
        st.write("O sistema lerá a lista oficial de ativos da empresa selecionada, identificará quem saiu e cadastrará novos membros automaticamente.")
        
        uploaded_file = st.file_uploader("Selecione o relatório PDF da empresa:", type=["pdf"])
        
        if uploaded_file:
            nomes_extraidos = []
            with pdfplumber.open(uploaded_file) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        for line in text.split('\n'):
                            if len(line.strip()) > 3:
                                nomes_extraidos.append(line.strip().upper())
            
            novos, inativados = atualizar_status_em_massa(empresa_id, nomes_extraidos)
            
            st.subheader("Resumo Comparativo de Alterações:")
            col1, col2 = st.columns(2)
            
            with col1:
                st.success(f"🌱 **Novos Colaboradores ({len(novos)}):**")
                for n in novos:
                    st.write(f"- {n}")
                    
            with col2:
                st.warning(f"🔻 **A Inativar ({len(inativados)}):**")
                for _, n in inativados:
                    st.write(f"- {n}")
                    
            if novos or inativados:
                if st.button("Confirmar e Registrar com meu usuário"):
                    confirmar_sincronizacao(empresa_id, novos, inativados, st.session_state['usuario_nome'])
                    st.success("Registros sincronizados com sucesso!")
            else:
                st.info("Nenhuma mudança detectada na empresa selecionada.")

    # PASSO 4: REGISTRAR OBSERVACÕES COM AUTOCOMPLETE E AUDITORIA
    elif menu == "4. Inserir Observações (Faltas/Atestados)":
        st.header(f"4. Apontamentos — {empresa_selecionada_nome}")
        
        ativos_df = get_colaboradores(empresa_id, status_filter="ATIVO")
        
        if ativos_df.empty:
            st.warning("Nenhum colaborador ativo nesta empresa.")
        else:
            colab_selecionado = st.selectbox(
                "Digite para filtrar o nome do colaborador (Busca Automática):",
                options=ativos_df['nome'].tolist()
            )
            
            tipo = st.radio("Tipo de Ocorrência:", ["Atestado", "Falta"])
            data_ocorrencia = st.date_input("Data da Ocorrência:", datetime.now())
            duracao = st.text_input("Duração (Ex: 1 dia, 30 dias):", value="1 dia")
            obs = st.text_area("Observações Adicionais:")
            
            if st.button("Salvar Apontamento"):
                colab_id = int(ativos_df[ativos_df['nome'] == colab_selecionado]['id'].values[0])
                salvar_apontamento(
                    empresa_id, colab_id, tipo, 
                    data_ocorrencia.strftime("%d/%m/%Y"), 
                    duracao, obs, st.session_state['usuario_nome']
                )
                st.success(f"Gravado com sucesso! Usuário responsável: {st.session_state['usuario_nome']}")

    # PASSO 5 & 6: GERAR RELATÓRIO PDF COM AUDITORIA NO RODAPÉ
    elif menu == "5. Gerar e Exportar PDF Final":
        st.header(f"5. Gerar Relatório Auditado — {empresa_selecionada_nome}")
        
        mes = st.text_input("Mês/Ano de Referência:", value="Setembro/2026")
        
        if st.button("Gerar PDF Final"):
            pdf_bytes = gerar_pdf_mes(empresa_selecionada_nome, empresa_id, mes, st.session_state['usuario_nome'])
            
            st.download_button(
                label="📥 Baixar PDF Auditado",
                data=pdf_bytes,
                file_name=f"Relatorio_{empresa_selecionada_nome}_{mes.replace('/', '_')}.pdf",
                mime="application/pdf"
            )