from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import json, os, re, secrets
import urllib.request, urllib.error
from datetime import datetime
from functools import wraps
from contextlib import contextmanager
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from psycopg2 import pool as pgpool

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'atpv-diego-2670-secret-key-fixo')
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = 86400
app.config['SESSION_COOKIE_HTTPONLY'] = True

def _env(nome, padrao=''):
    """Le a variavel ja sem espacos, aspas ou quebras de linha — colar o
    valor no painel costuma trazer esse lixo junto e derruba a requisicao."""
    return (os.environ.get(nome, padrao) or '').strip().strip('"').strip("'").strip()

# ── ZAPSIGN (assinatura eletrônica) ───────────────────────────
ZAPSIGN_TOKEN = _env('ZAPSIGN_TOKEN')
ZAPSIGN_API   = _env('ZAPSIGN_API', 'https://api.zapsign.com.br/api/v1')

# ── ALERTAS (Telegram) ────────────────────────────────────────
TELEGRAM_TOKEN   = _env('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = _env('TELEGRAM_CHAT_ID')
ALERTA_CHAVE     = _env('ALERTA_CHAVE')

# ── BANCO DE DADOS ────────────────────────────────────────────
DATABASE_URL = os.environ.get('DATABASE_URL', '')
HIST_PAGINA  = int(os.environ.get('HIST_PAGINA', '100'))

_POOL = None

def _get_pool():
    """Pool de conexões — evita abrir uma conexão nova (e um handshake
    TLS com o Neon) a cada requisição."""
    global _POOL
    if _POOL is None and DATABASE_URL:
        _POOL = pgpool.ThreadedConnectionPool(1, 8, DATABASE_URL,
                                              cursor_factory=RealDictCursor)
    return _POOL

@contextmanager
def db(commit=False):
    """Abre cursor, devolve a conexão ao pool no fim, sempre."""
    p = _get_pool()
    if p is None:
        raise RuntimeError("DATABASE_URL não configurada")
    conn = p.getconn()
    try:
        cur = conn.cursor()
        yield cur
        if commit:
            conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)

SCHEMA = """
CREATE TABLE IF NOT EXISTS empresas (
    id          TEXT PRIMARY KEY,
    nome        TEXT NOT NULL,
    cnpj        TEXT DEFAULT '',
    contato     TEXT DEFAULT '',
    tel         TEXT DEFAULT '',
    email       TEXT DEFAULT '',
    criado      TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS usuarios (
    id            TEXT PRIMARY KEY,
    nome          TEXT DEFAULT '',
    login         TEXT NOT NULL,
    senha         TEXT NOT NULL,
    perfil        TEXT DEFAULT 'funcionario',
    empresa_id    TEXT,
    ativo         BOOLEAN DEFAULT TRUE,
    ver_relatorio BOOLEAN DEFAULT FALSE,
    criado        TEXT DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS usuarios_login_uniq ON usuarios (lower(login));

CREATE TABLE IF NOT EXISTS pessoas (
    id         BIGSERIAL PRIMARY KEY,
    nome       TEXT DEFAULT '',
    cpf        TEXT DEFAULT '',
    rg         TEXT DEFAULT '',
    rg_org     TEXT DEFAULT '',
    nasc       TEXT DEFAULT '',
    ecivil     TEXT DEFAULT '',
    endereco   TEXT DEFAULT '',
    bairro     TEXT DEFAULT '',
    cidade     TEXT DEFAULT '',
    cep        TEXT DEFAULT '',
    cel        TEXT DEFAULT '',
    email      TEXT DEFAULT '',
    atualizado TEXT DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS pessoas_cpf_uniq ON pessoas (cpf) WHERE cpf <> '';
CREATE INDEX IF NOT EXISTS pessoas_nome_idx ON pessoas (lower(nome));

CREATE TABLE IF NOT EXISTS veiculos (
    id         BIGSERIAL PRIMARY KEY,
    placa      TEXT NOT NULL UNIQUE,
    chassi     TEXT DEFAULT '',
    modelo     TEXT DEFAULT '',
    ano        TEXT DEFAULT '',
    atualizado TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS veiculos_modelo_idx ON veiculos (lower(modelo));

CREATE TABLE IF NOT EXISTS contratantes (
    id         BIGSERIAL PRIMARY KEY,
    nome       TEXT NOT NULL,
    cpf        TEXT DEFAULT '',
    tipo       TEXT DEFAULT '',
    tel        TEXT DEFAULT '',
    pgto       TEXT DEFAULT '',
    atualizado TEXT DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS contratantes_cpf_uniq ON contratantes (cpf) WHERE cpf <> '';
CREATE INDEX IF NOT EXISTS contratantes_nome_idx ON contratantes (lower(nome));

CREATE TABLE IF NOT EXISTS atendimentos (
    id               BIGSERIAL PRIMARY KEY,
    criado           TIMESTAMPTZ DEFAULT NOW(),
    data             TEXT DEFAULT '',
    nome             TEXT DEFAULT '',
    placa            TEXT DEFAULT '',
    modelo           TEXT DEFAULT '',
    vendedor_nome    TEXT DEFAULT '',
    chassi           TEXT DEFAULT '',
    contratante_nome TEXT DEFAULT '',
    contratante_cpf  TEXT DEFAULT '',
    contratante_tipo TEXT DEFAULT '',
    ct_pgto          TEXT DEFAULT '',
    valor_cobrado    TEXT DEFAULT '',
    status_pgto      TEXT DEFAULT 'pendente',
    obs              TEXT DEFAULT '',
    obs_fin          TEXT DEFAULT '',
    user_id          TEXT DEFAULT '',
    user_nome        TEXT DEFAULT '',
    perfil           TEXT DEFAULT '',
    empresa_id       TEXT,
    assinatura_token TEXT DEFAULT '',
    assinatura_url   TEXT DEFAULT '',
    snap             JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS atend_criado_idx  ON atendimentos (criado DESC, id DESC);
CREATE INDEX IF NOT EXISTS atend_empresa_idx ON atendimentos (empresa_id);
CREATE INDEX IF NOT EXISTS atend_nome_idx    ON atendimentos (lower(nome));
CREATE INDEX IF NOT EXISTS atend_placa_idx   ON atendimentos (lower(placa));

CREATE TABLE IF NOT EXISTS cofre (
    id        BIGSERIAL PRIMARY KEY,
    descricao TEXT DEFAULT '',
    valor     TEXT DEFAULT '',
    criado    TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE IF EXISTS atendimentos ADD COLUMN IF NOT EXISTS assinatura_status  TEXT DEFAULT '';
ALTER TABLE IF EXISTS atendimentos ADD COLUMN IF NOT EXISTS assinatura_arquivo TEXT DEFAULT '';
ALTER TABLE IF EXISTS atendimentos ADD COLUMN IF NOT EXISTS assinatura_em      TIMESTAMPTZ;
ALTER TABLE IF EXISTS atendimentos ADD COLUMN IF NOT EXISTS assinatura_nome    TEXT DEFAULT '';
ALTER TABLE IF EXISTS atendimentos ADD COLUMN IF NOT EXISTS assinatura_nivel   TEXT DEFAULT '';
CREATE INDEX IF NOT EXISTS atend_assin_idx ON atendimentos (assinatura_token) WHERE assinatura_token <> '';

CREATE TABLE IF NOT EXISTS processos (
    id               BIGSERIAL PRIMARY KEY,
    criado           TIMESTAMPTZ DEFAULT NOW(),
    atualizado       TIMESTAMPTZ DEFAULT NOW(),
    tipo             TEXT DEFAULT 'multa',
    cliente_nome     TEXT DEFAULT '',
    cliente_cpf      TEXT DEFAULT '',
    cliente_tel      TEXT DEFAULT '',
    placa            TEXT DEFAULT '',
    ait              TEXT DEFAULT '',
    orgao            TEXT DEFAULT '',
    infracao         TEXT DEFAULT '',
    fase             TEXT DEFAULT 'defesa_previa',
    data_notificacao DATE,
    prazo_dias       INTEGER DEFAULT 30,
    prazo_final      DATE,
    protocolo        TEXT DEFAULT '',
    data_protocolo   DATE,
    status           TEXT DEFAULT 'a_protocolar',
    resultado        TEXT DEFAULT '',
    valor_servico    TEXT DEFAULT '',
    status_pgto      TEXT DEFAULT 'pendente',
    obs              TEXT DEFAULT '',
    user_id          TEXT DEFAULT '',
    user_nome        TEXT DEFAULT '',
    empresa_id       TEXT
);
CREATE INDEX IF NOT EXISTS proc_prazo_idx   ON processos (prazo_final);
CREATE INDEX IF NOT EXISTS proc_status_idx  ON processos (status);
CREATE INDEX IF NOT EXISTS proc_cliente_idx ON processos (lower(cliente_nome));
CREATE INDEX IF NOT EXISTS proc_placa_idx   ON processos (lower(placa));

CREATE TABLE IF NOT EXISTS processo_andamentos (
    id          BIGSERIAL PRIMARY KEY,
    processo_id BIGINT REFERENCES processos(id) ON DELETE CASCADE,
    quando      TIMESTAMPTZ DEFAULT NOW(),
    descricao   TEXT DEFAULT '',
    usuario     TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS andam_proc_idx ON processo_andamentos (processo_id, id);

CREATE TABLE IF NOT EXISTS migracoes (
    nome     TEXT PRIMARY KEY,
    aplicada TIMESTAMPTZ DEFAULT NOW()
);
"""

def _ler_blob(cur, chave):
    """Lê uma chave do formato antigo (tabela 'dados' com JSON em texto)."""
    cur.execute("SELECT to_regclass('public.dados') AS t")
    if not cur.fetchone()['t']:
        return []
    cur.execute("SELECT valor FROM dados WHERE chave = %s", (chave,))
    row = cur.fetchone()
    if not row:
        return []
    try:
        d = json.loads(row['valor'])
        return d if isinstance(d, list) else []
    except Exception:
        return []

def _data_br(txt):
    """'25/09/2026 10:30' -> datetime. Devolve None se não der para ler."""
    if not txt:
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(txt).strip(), fmt)
        except ValueError:
            continue
    return None

def _sim_nao(v, padrao=True):
    if isinstance(v, bool): return v
    if v is None: return padrao
    return str(v).lower() in ('true', '1', 'sim')

def migrar_do_blob(cur):
    """Copia os dados do formato antigo para as tabelas novas.
    Roda uma única vez; a tabela 'dados' NÃO é apagada — fica como backup."""
    cur.execute("SELECT 1 FROM migracoes WHERE nome = 'normalizacao_v1'")
    if cur.fetchone():
        return None

    contagem = {}

    for e in _ler_blob(cur, "empresas"):
        cur.execute("""INSERT INTO empresas (id,nome,cnpj,contato,tel,email,criado)
                       VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
                    (str(e.get("id") or secrets.token_hex(8)), e.get("nome",""), e.get("cnpj",""),
                     e.get("contato",""), e.get("tel",""), e.get("email",""), e.get("criado","")))
    contagem['empresas'] = cur.rowcount if cur.rowcount and cur.rowcount > 0 else len(_ler_blob(cur,"empresas"))

    for u in _ler_blob(cur, "usuarios"):
        if not u.get("login") or not u.get("senha"):
            continue
        cur.execute("""INSERT INTO usuarios (id,nome,login,senha,perfil,empresa_id,ativo,ver_relatorio,criado)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (lower(login)) DO NOTHING""",
                    (str(u.get("id") or secrets.token_hex(8)), u.get("nome",""), u.get("login"),
                     u.get("senha"), u.get("perfil","funcionario"), u.get("empresa_id"),
                     _sim_nao(u.get("ativo"), True), _sim_nao(u.get("ver_relatorio"), False),
                     u.get("criado","")))
    contagem['usuarios'] = len(_ler_blob(cur, "usuarios"))

    for p in _ler_blob(cur, "pessoas"):
        cur.execute("""INSERT INTO pessoas (nome,cpf,rg,rg_org,nasc,ecivil,endereco,bairro,cidade,cep,cel,email,atualizado)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (cpf) WHERE cpf <> '' DO NOTHING""",
                    (p.get("nome",""), p.get("cpf",""), p.get("rg",""), p.get("rg_org",""),
                     p.get("nasc",""), p.get("ecivil",""), p.get("end",""), p.get("bairro",""),
                     p.get("cidade",""), p.get("cep",""), p.get("cel",""), p.get("email",""),
                     p.get("atualizado","")))
    contagem['pessoas'] = len(_ler_blob(cur, "pessoas"))

    for v in _ler_blob(cur, "veiculos"):
        if not v.get("placa"):
            continue
        cur.execute("""INSERT INTO veiculos (placa,chassi,modelo,ano,atualizado)
                       VALUES (%s,%s,%s,%s,%s) ON CONFLICT (placa) DO NOTHING""",
                    (v.get("placa","").upper(), v.get("chassi",""), v.get("modelo",""),
                     v.get("ano",""), v.get("atualizado","")))
    contagem['veiculos'] = len(_ler_blob(cur, "veiculos"))

    for c in _ler_blob(cur, "contratantes"):
        if not c.get("nome"):
            continue
        cur.execute("""INSERT INTO contratantes (nome,cpf,tipo,tel,pgto,atualizado)
                       VALUES (%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (cpf) WHERE cpf <> '' DO NOTHING""",
                    (c.get("nome"), c.get("cpf",""), c.get("tipo",""), c.get("tel",""),
                     c.get("pgto",""), c.get("atualizado","")))
    contagem['contratantes'] = len(_ler_blob(cur, "contratantes"))

    for c in _ler_blob(cur, "cofre"):
        cur.execute("INSERT INTO cofre (descricao,valor) VALUES (%s,%s)",
                    (c.get("desc",""), c.get("val","")))
    contagem['cofre'] = len(_ler_blob(cur, "cofre"))

    # Histórico: o mais antigo entra primeiro, para que os IDs cresçam
    # na mesma ordem cronológica da lista antiga.
    hist = _ler_blob(cur, "historico")
    for h in reversed(hist):
        snap = h.get("snap") or {}
        cur.execute("""INSERT INTO atendimentos
            (criado,data,nome,placa,modelo,vendedor_nome,chassi,contratante_nome,contratante_cpf,
             contratante_tipo,ct_pgto,valor_cobrado,status_pgto,obs,obs_fin,
             user_id,user_nome,perfil,empresa_id,snap)
            VALUES (COALESCE(%s, NOW()),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (_data_br(h.get("data")),
             h.get("data",""), h.get("nome",""), h.get("placa",""), h.get("modelo",""),
             snap.get("v_nome",""), snap.get("ve_chassi",""),
             h.get("contratante_nome",""), h.get("contratante_cpf",""),
             h.get("contratante_tipo",""), h.get("ct_pgto",""),
             h.get("valor_cobrado",""), h.get("status_pgto","pendente"),
             h.get("obs",""), h.get("obs_fin",""),
             str(h.get("user_id") or ""), h.get("user_nome",""), h.get("perfil",""),
             h.get("empresa_id"), Json(snap)))
    contagem['atendimentos'] = len(hist)

    cur.execute("INSERT INTO migracoes (nome) VALUES ('normalizacao_v1')")
    return contagem

def init_db():
    with db(commit=True) as cur:
        # O Render pode subir vários processos ao mesmo tempo. Este cadeado
        # garante que só um crie as tabelas e migre; os outros esperam e,
        # ao entrar, já encontram a migração marcada como feita.
        cur.execute("SELECT pg_advisory_xact_lock(918273645)")
        cur.execute(SCHEMA)
        resultado = migrar_do_blob(cur)
        if resultado:
            print("Migração normalizacao_v1 concluída:", resultado)
        # Admin padrão, só se não houver nenhum usuário
        cur.execute("SELECT COUNT(*) AS n FROM usuarios")
        if cur.fetchone()['n'] == 0:
            senha_inicial = os.environ.get('ADMIN_SENHA_INICIAL', 'diego2670')
            cur.execute("""INSERT INTO usuarios (id,nome,login,senha,perfil,ativo,criado)
                           VALUES ('1','Diego Caetano','diego',%s,'admin',TRUE,%s)""",
                        (generate_password_hash(senha_inicial),
                         datetime.now().strftime("%d/%m/%Y %H:%M")))
            print("Usuário admin criado.")

try:
    if DATABASE_URL:
        init_db()
        print("Banco de dados pronto.")
    else:
        print("DATABASE_URL não configurada — banco não inicializado.")
except Exception as e:
    print("Erro ao inicializar banco: %s" % e)

def agora():
    return datetime.now().strftime("%d/%m/%Y %H:%M")

# ── AUTENTICAÇÃO ─────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"erro": "Não autorizado"}), 401
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"erro": "Não autorizado"}), 401
        if session.get('perfil') not in ['admin', 'funcionario']:
            return jsonify({"erro": "Sem permissão"}), 403
        return f(*args, **kwargs)
    return decorated

def so_admin():
    return session.get('perfil') == 'admin'

# ── EXTRAÇÃO POR REGEX ────────────────────────────────────────
def extrair_campos(texto):
    t = texto.replace("\r\n","\n").replace("\t"," ")
    r = {}

    def match(patterns):
        for p in patterns:
            m = re.search(p, t, re.IGNORECASE)
            if m and m.group(1) and m.group(1).strip():
                return m.group(1).strip()
        return ""

    # ── DETECTA SE É CNH (OCR) ───────────────────────────────
    is_cnh = bool(re.search(r"CARTEIRA\s+NACIONAL\s+DE\s+HABILITAC|DRIVER\s+LICENSE|PERMISO\s+DE\s+CONDUC|HABILITAC[AÃ]O", t, re.IGNORECASE))
    is_rg  = bool(re.search(r"CARTEIRA\s+DE\s+IDENTIDADE|REGISTRO\s+GERAL|INSTITUTO\s+DE\s+IDENTIFICA", t, re.IGNORECASE))

    if is_cnh:
        # CNH: nome é a primeira linha com só letras maiúsculas após o cabeçalho
        # Padrão: após "CONDUCCION\n" ou "LICENSE\n" vem o nome
        nome_cnh = match([
            r"CONDUCCION\s*\n\s*([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ][A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ\s]{3,60}?)(?:\s*\n)",
            r"LICENSE[/\s]*PERMISO[^\n]*\n\s*([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ][A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ\s]{3,60}?)(?:\s*\n)",
            r"HABILITAC[AÃ]O[^\n]*\n\s*([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ][A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ\s]{3,60}?)(?:\s*\n)",
        ])
        # Se não achou com padrão, pega a primeira linha com 2+ palavras só letras maiúsculas
        if not nome_cnh:
            for linha in t.split('\n'):
                linha = linha.strip()
                if re.match(r'^[A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ]{2,}(\s+[A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ]{2,})+$', linha):
                    if len(linha) > 8 and not any(w in linha for w in ['BRASIL','FEDERAL','MINISTERIO','SECRETARIA','NACIONAL','TRANSITO','TERRITORIO','HABILITACAO']):
                        nome_cnh = linha
                        break
        if nome_cnh:
            r["v_nome"] = nome_cnh.strip()

        # Data de nascimento na CNH: formato "DD/MM/AAAA, CIDADE, UF" ou linha isolada
        nasc_m = re.search(r"(\d{2}/\d{2}/\d{4}),?\s+([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ][A-Z\s]+),?\s+([A-Z]{2})", t)
        if nasc_m:
            r["v_nasc"] = nasc_m.group(1)
            r["v_cidade"] = nasc_m.group(2).strip() + "/" + nasc_m.group(3)

        # RG da CNH (número de registro — 9+ dígitos)
        rg_cnh = re.search(r"\b(\d{9,11})\b", t)
        if rg_cnh:
            r["v_rg"] = rg_cnh.group(1)

        # Cidade atual (GOIANIA, GO — última ocorrência de cidade/UF)
        cidades = re.findall(r"([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ][A-Z\s]{2,20}),\s*([A-Z]{2})(?:\s|\n|$)", t)
        for cidade, uf in reversed(cidades):
            cidade = cidade.strip()
            if cidade not in ['DRIVER LICENSE','PERMISO','REPUBLICA','MINISTERIO','SECRETARIA']:
                if not r.get("v_cidade"):
                    r["v_cidade"] = cidade + "/" + uf
                break

    elif is_rg:
        # RG: nome após "NOME" ou primeira linha com letras maiúsculas
        r["v_nome"] = match([
            r"NOME[:\s]*([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ][A-Z\s]{3,60}?)(?:\s*\n|\s*DATA)",
        ])
        r["v_nasc"] = match([r"NASCIMENTO[:\s]*(\d{2}/\d{2}/\d{4})"])
        r["v_cidade"] = match([r"NATURAL[:\s]*([A-Z][A-Z\s]{2,30}?)(?:\s*\n|\s*UF)"])

    # ── NOME — padrões gerais (DETRAN, formulários etc) ──────
    if not r.get("v_nome"):
        r["v_nome"] = match([
            r"Nome(?:\s+do\s+Proprietario)?[:\s]+([A-Z][A-Z\s]{3,60}?)(?:\s*CPF|\s*CNPJ|\n)",
            r"Proprietario[:\s]+([A-Z][A-Z\s]{3,60}?)(?:\s*CPF|\n)",
            r"Nome\s+Solicitante[:\s]+([A-Z][A-Z\s]{3,60}?)(?:\s*Tipo|\n)",
            r"Aberto por[:\s]+([A-Z][A-Z\s]{3,60}?)(?:\s*Tipo|\n)",
            r"Nome:[:\s]+([A-Z][A-Z\s]{3,60}?)(?:\s*CPF|\s*CNPJ|\n)",
            r"Nome[^\n:]*:\s*[\t ]*\n[\t ]*([A-Z][A-Z\s]{3,60}?)[\t ]*\n",
        ])
    palavras_invalidas = ['EMPRESARIAL','SITUACAO','ESPECIAL','REGULAR','SUSPENSA','CANCELADA',
                          'INAPTA','BAIXADA','PENDENTE','CONSULTA','SERVICOS','RECEITA',
                          'DRIVER LICENSE','HABILITACAO','REPUBLICA','MINISTERIO']
    if r.get("v_nome") and r["v_nome"].strip().upper() in palavras_invalidas:
        r["v_nome"] = ""

    r["v_cpf"] = match([
        r"CPF[/\s]*CNPJ[:\s]*([\d]{2,3}\.[\d]{3}\.[\d]{3}[/\-][\d]{4}[\-\d]{0,6})",
        r"CPF[:\s]*([\d]{3}\.[\d]{3}\.[\d]{3}-[\d]{2})",
        r"CNPJ[:\s]*([\d]{2}\.[\d]{3}\.[\d]{3}/[\d]{4}-[\d]{2})",
        r"\b(\d{3}\.\d{3}\.\d{3}-\d{2})\b",
        r"\b(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\b",
    ])

    if not r.get("v_rg"):
        r["v_rg"] = match([r"RG[:\s]*([\d]{5,12})", r"Identidade[:\s]*([\d]{5,12})"])

    # Data de nascimento geral
    if not r.get("v_nasc"):
        nasc_g = match([
            r"Nascimento[:\s]*(\d{2}/\d{2}/\d{4})",
            r"Data\s+de\s+Nasc[:\s]*(\d{2}/\d{2}/\d{4})",
        ])
        if nasc_g: r["v_nasc"] = nasc_g

    pm = re.search(r"Placa[:\s]*([A-Z]{3}[-\s]?[\dA-Z]{4})", t, re.IGNORECASE) or \
         re.search(r"\b([A-Z]{3}[-]?[0-9][A-Z0-9][0-9]{2})\b", t)
    if pm: r["ve_placa"] = pm.group(1).replace(" ","").upper()

    cm = re.search(r"Chassi[:\s]*([A-Z0-9]{17})", t, re.IGNORECASE) or \
         re.search(r"\b([A-Z0-9]{17})\b", t)
    if cm: r["ve_chassi"] = cm.group(1).upper()

    r["ve_modelo"] = match([
        r"Marca[/\s]*Modelo[:\s]*[\d-]*\s*([A-Z0-9][A-Z0-9\s/\-\.]{3,50}?)(?:\s*Ano|\s*cor|\s*Cap|\n)",
        r"Modelo[:\s]*[\d-]*\s*([A-Z0-9][A-Z0-9\s/\-\.]{3,40}?)(?:\s*Ano|\s*Cor|\n)",
        r"\d{4,6}-([A-Z][A-Z0-9\s/\.]{3,40}?)(?:\s*Ano\s*Mod|\s*Ano\s*Fab|\n)",
    ])
    if r.get("ve_modelo"): r["ve_modelo"] = re.sub(r"^\d+-","",r["ve_modelo"]).strip()

    fab = re.search(r"Ano\s*Fab[:\s]*(\d{4})", t, re.IGNORECASE)
    mod = re.search(r"Ano\s*Mod[:\s]*(\d{4})", t, re.IGNORECASE)
    if fab and mod: r["ve_ano"] = fab.group(1)+"/"+mod.group(1)
    elif fab: r["ve_ano"] = fab.group(1)
    elif mod: r["ve_ano"] = mod.group(1)

    logradouro = match([
        r"Logradouro[:\s]*([A-Z][^\n]{4,60}?)(?:\s*Bairro|\s*CEP|\s*N[ou]|\n)",
        r"Endere[cC]o[:\s]*([A-Z][^\n]{5,60}?)(?:\s*N[ou]|\s*Bairro|\s*CEP|\n)",
    ])
    nro_m = re.search(r"N[uú]mero[:\s]*(\d+[A-Z]?)", t, re.IGNORECASE) or \
            re.search(r"\bN[o°º][:\s]*(\d+[A-Z]?)", t, re.IGNORECASE)
    nro = nro_m.group(1).strip() if nro_m else ""
    if nro in ["0","00","000"]: nro = "SN"
    complemento = match([r"Complemento[:\s]*([^\n]{3,50}?)(?:\s*N[ouú]|\s*Munic|\s*CEP|\n)"])
    end_parts = []
    if logradouro: end_parts.append(logradouro.strip().rstrip(","))
    if nro: end_parts.append("Nº "+nro)
    if complemento: end_parts.append(complemento.strip())
    if end_parts: r["v_end"] = ", ".join(end_parts)

    r["v_bairro"] = match([r"Bairro[:\s]*([A-Z][^\n]{3,40}?)(?:\s*CEP|\s*Munic|\s*Compl|\n)"])

    if not r.get("v_cidade"):
        cm2 = re.search(r"Munic[íi]pio[:\s]*([^\n]{3,50}?)(?:\s*CEP|\s*UF|\n)", t, re.IGNORECASE)
        cidade_raw = re.sub(r"^[\d\s]+[-]\s*","",cm2.group(1)).strip() if cm2 else ""
        if not cidade_raw: cidade_raw = match([r"Cidade[:\s]*([A-Z][^\n]{3,30}?)(?:\s*CEP|\s*UF|\n)"])
        r["v_cidade"] = cidade_raw

    cep_m = re.search(r"CEP[:\s]*([\d]{2}[.;]?[\d]{3}[-.]?[\d]{3})", t, re.IGNORECASE)
    if cep_m:
        c = re.sub(r"\D","",cep_m.group(1))
        if len(c)==8: r["v_cep"] = c[:5]+"-"+c[5:]

    for k in ["v_nome","v_bairro","v_cidade","ve_modelo"]:
        if r.get(k) and len(r[k])<3: r[k]=""

    return {k:v for k,v in r.items() if v}

# ── ROTAS DE AUTENTICAÇÃO ─────────────────────────────────────
@app.route("/")
def index():
    if 'user_id' not in session:
        return render_template("login.html")
    return render_template("index.html")

@app.route("/login", methods=["GET"])
def login_page():
    if 'user_id' in session:
        return redirect('/')
    return render_template("login.html")

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json() or {}
    login = (data.get("login") or "").strip().lower()
    senha = data.get("senha") or ""
    with db() as cur:
        cur.execute("SELECT * FROM usuarios WHERE lower(login) = %s AND ativo = TRUE", (login,))
        user = cur.fetchone()
    if not user or not check_password_hash(user['senha'], senha):
        return jsonify({"erro": "Login ou senha incorretos"}), 401
    session.permanent = True
    session['user_id']    = user['id']
    session['user_nome']  = user['nome']
    session['perfil']     = user['perfil']
    session['empresa_id'] = user.get('empresa_id')
    return jsonify({"ok": True, "perfil": user['perfil'], "nome": user['nome']})

@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/api/me")
def api_me():
    if 'user_id' not in session:
        return jsonify({"logado": False})
    return jsonify({"logado": True, "nome": session.get('user_nome'),
                    "perfil": session.get('perfil'), "empresa_id": session.get('empresa_id')})

# ── EXTRAÇÃO ──────────────────────────────────────────────────
@app.route("/api/extrair", methods=["POST"])
@login_required
def api_extrair():
    data = request.get_json() or {}
    campos = extrair_campos(data.get("texto", ""))
    return jsonify({"campos": campos, "total": len(campos)})

# ── HISTÓRICO / ATENDIMENTOS ──────────────────────────────────
CAMPOS_LISTA = ("id, data, nome, placa, modelo, valor_cobrado, status_pgto, obs_fin, "
                "user_nome, empresa_id, assinatura_url, assinatura_token")

def _escopo_empresa():
    """Empresa só enxerga os próprios atendimentos."""
    if session.get('perfil') == 'empresa':
        return " AND empresa_id = %s", [session.get('empresa_id')]
    return "", []

@app.route("/api/historico", methods=["GET"])
@login_required
def api_hist_get():
    q = (request.args.get("q") or "").strip().lower()
    try:
        limite = int(request.args.get("limite", HIST_PAGINA))
    except ValueError:
        limite = HIST_PAGINA
    limite = max(1, min(limite, 1000))

    base, base_params = _escopo_empresa()
    cond, params = base, list(base_params)
    if q:
        cond += " AND (lower(nome) LIKE %s OR lower(placa) LIKE %s)"
        params += ['%' + q + '%', '%' + q + '%']

    with db() as cur:
        # total geral (o contador da tela nao muda quando o usuario busca)
        cur.execute("SELECT COUNT(*) AS n FROM atendimentos WHERE TRUE" + base, base_params)
        total = cur.fetchone()['n']
        cur.execute("SELECT COUNT(*) AS n FROM atendimentos WHERE TRUE" + cond, params)
        encontrados = cur.fetchone()['n']
        cur.execute("SELECT " + CAMPOS_LISTA + " FROM atendimentos WHERE TRUE" + cond +
                    " ORDER BY id DESC LIMIT %s", params + [limite])
        itens = [dict(r) for r in cur.fetchall()]
    return jsonify({"total": total, "encontrados": encontrados, "itens": itens})

@app.route("/api/historico", methods=["POST"])
@login_required
def api_hist_post():
    data = request.get_json() or {}
    snap = data.get("snap") or {}
    with db(commit=True) as cur:
        cur.execute("""INSERT INTO atendimentos
            (data,nome,placa,modelo,vendedor_nome,chassi,contratante_nome,contratante_cpf,
             contratante_tipo,ct_pgto,valor_cobrado,status_pgto,obs,
             user_id,user_nome,perfil,empresa_id,snap)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (agora(), data.get("nome", ""), data.get("placa", ""), data.get("modelo", ""),
             snap.get("v_nome", ""), snap.get("ve_chassi", ""),
             data.get("contratante_nome", ""), data.get("contratante_cpf", ""),
             data.get("contratante_tipo", ""), data.get("ct_pgto", ""),
             data.get("valor_cobrado", ""), data.get("status_pgto") or "pendente",
             data.get("obs", ""),
             str(session.get('user_id') or ""), session.get('user_nome') or "",
             session.get('perfil') or "", session.get('empresa_id'), Json(snap)))
        novo = cur.fetchone()['id']
    return jsonify({"ok": True, "id": novo})

@app.route("/api/historico/<int:aid>", methods=["DELETE"])
@login_required
def api_hist_del(aid):
    cond, params = _escopo_empresa()
    with db(commit=True) as cur:
        cur.execute("DELETE FROM atendimentos WHERE id = %s" + cond, [aid] + params)
        apagou = cur.rowcount
    if not apagou:
        return jsonify({"erro": "Não encontrado"}), 404
    return jsonify({"ok": True})

@app.route("/api/historico/<int:aid>/snap", methods=["GET"])
@login_required
def api_hist_snap(aid):
    cond, params = _escopo_empresa()
    with db() as cur:
        cur.execute("SELECT snap FROM atendimentos WHERE id = %s" + cond, [aid] + params)
        row = cur.fetchone()
    if not row:
        return jsonify({"erro": "Não encontrado"}), 404
    return jsonify({"ok": True, "snap": row['snap'] or {}})

@app.route("/api/historico/<int:aid>/financeiro", methods=["PUT"])
@login_required
def api_fin_put(aid):
    data = request.get_json() or {}
    cond, params = _escopo_empresa()
    with db(commit=True) as cur:
        cur.execute("""UPDATE atendimentos SET
                       valor_cobrado = COALESCE(%s, valor_cobrado),
                       status_pgto   = COALESCE(%s, status_pgto),
                       obs_fin       = COALESCE(%s, obs_fin)
                       WHERE id = %s""" + cond,
                    [data.get('valor_cobrado'), data.get('status_pgto'),
                     data.get('obs_fin'), aid] + params)
        ok = cur.rowcount
    if not ok:
        return jsonify({"erro": "Não encontrado"}), 404
    return jsonify({"ok": True})

# ── PESSOAS ───────────────────────────────────────────────────
def _pessoa_saida(r):
    """Mantém o nome 'end' que o frontend já usa."""
    d = dict(r)
    d['end'] = d.pop('endereco', '')
    return d

@app.route("/api/pessoas", methods=["GET"])
@login_required
def api_pessoas_get():
    q = (request.args.get("q") or "").strip().lower()
    with db() as cur:
        if q:
            cur.execute("""SELECT * FROM pessoas
                           WHERE lower(nome) LIKE %s OR cpf LIKE %s
                           ORDER BY id DESC LIMIT 20""", ('%'+q+'%', '%'+q+'%'))
        else:
            cur.execute("SELECT * FROM pessoas ORDER BY id DESC LIMIT 20")
        return jsonify([_pessoa_saida(r) for r in cur.fetchall()])

@app.route("/api/pessoas", methods=["POST"])
@login_required
def api_pessoas_post():
    d = request.get_json() or {}
    if not d.get("nome") and not d.get("cpf"):
        return jsonify({"erro": "Informe nome ou CPF"}), 400
    cpf = (d.get("cpf") or "").strip()
    vals = (d.get("nome",""), cpf, d.get("rg",""), d.get("rg_org",""), d.get("nasc",""),
            d.get("ecivil",""), d.get("end",""), d.get("bairro",""), d.get("cidade",""),
            d.get("cep",""), d.get("cel",""), d.get("email",""), agora())
    with db(commit=True) as cur:
        if cpf:
            cur.execute("""INSERT INTO pessoas
                (nome,cpf,rg,rg_org,nasc,ecivil,endereco,bairro,cidade,cep,cel,email,atualizado)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (cpf) WHERE cpf <> '' DO UPDATE SET
                    nome=EXCLUDED.nome, rg=EXCLUDED.rg, rg_org=EXCLUDED.rg_org,
                    nasc=EXCLUDED.nasc, ecivil=EXCLUDED.ecivil, endereco=EXCLUDED.endereco,
                    bairro=EXCLUDED.bairro, cidade=EXCLUDED.cidade, cep=EXCLUDED.cep,
                    cel=EXCLUDED.cel, email=EXCLUDED.email, atualizado=EXCLUDED.atualizado""", vals)
        else:
            cur.execute("""INSERT INTO pessoas
                (nome,cpf,rg,rg_org,nasc,ecivil,endereco,bairro,cidade,cep,cel,email,atualizado)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", vals)
    return jsonify({"ok": True})

# ── VEÍCULOS ──────────────────────────────────────────────────
@app.route("/api/veiculos", methods=["GET"])
@login_required
def api_veiculos_get():
    q = (request.args.get("q") or "").strip().lower()
    with db() as cur:
        if q:
            cur.execute("""SELECT * FROM veiculos
                           WHERE lower(placa) LIKE %s OR lower(modelo) LIKE %s
                           ORDER BY id DESC LIMIT 20""", ('%'+q+'%', '%'+q+'%'))
        else:
            cur.execute("SELECT * FROM veiculos ORDER BY id DESC LIMIT 20")
        return jsonify([dict(r) for r in cur.fetchall()])

@app.route("/api/veiculos", methods=["POST"])
@login_required
def api_veiculos_post():
    d = request.get_json() or {}
    placa = (d.get("placa") or "").strip().upper()
    if not placa:
        return jsonify({"erro": "Informe a placa"}), 400
    with db(commit=True) as cur:
        cur.execute("""INSERT INTO veiculos (placa,chassi,modelo,ano,atualizado)
                       VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT (placa) DO UPDATE SET
                         chassi=EXCLUDED.chassi, modelo=EXCLUDED.modelo,
                         ano=EXCLUDED.ano, atualizado=EXCLUDED.atualizado""",
                    (placa, d.get("chassi",""), d.get("modelo",""), d.get("ano",""), agora()))
    return jsonify({"ok": True})

# ── CONTRATANTES ──────────────────────────────────────────────
@app.route("/api/contratantes", methods=["GET"])
@login_required
def api_contrat_get():
    q = (request.args.get("q") or "").strip().lower()
    with db() as cur:
        if q:
            cur.execute("""SELECT * FROM contratantes
                           WHERE lower(nome) LIKE %s OR cpf LIKE %s
                           ORDER BY id DESC LIMIT 20""", ('%'+q+'%', '%'+q+'%'))
        else:
            cur.execute("SELECT * FROM contratantes ORDER BY id DESC LIMIT 20")
        return jsonify([dict(r) for r in cur.fetchall()])

@app.route("/api/contratantes", methods=["POST"])
@login_required
def api_contrat_post():
    d = request.get_json() or {}
    if not d.get("nome"):
        return jsonify({"erro": "Nome obrigatório"}), 400
    cpf = (d.get("cpf") or "").strip()
    vals = (d.get("nome"), cpf, d.get("tipo",""), d.get("tel",""), d.get("pgto",""), agora())
    with db(commit=True) as cur:
        if cpf:
            cur.execute("""INSERT INTO contratantes (nome,cpf,tipo,tel,pgto,atualizado)
                           VALUES (%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (cpf) WHERE cpf <> '' DO UPDATE SET
                             nome=EXCLUDED.nome, tipo=EXCLUDED.tipo, tel=EXCLUDED.tel,
                             pgto=EXCLUDED.pgto, atualizado=EXCLUDED.atualizado""", vals)
        else:
            cur.execute("""INSERT INTO contratantes (nome,cpf,tipo,tel,pgto,atualizado)
                           VALUES (%s,%s,%s,%s,%s,%s)""", vals)
    return jsonify({"ok": True})

# ── USUÁRIOS (só admin) ───────────────────────────────────────
@app.route("/api/usuarios", methods=["GET"])
@login_required
def api_usuarios_get():
    if not so_admin():
        return jsonify({"erro": "Sem permissão"}), 403
    with db() as cur:
        cur.execute("""SELECT id,nome,login,perfil,empresa_id,ativo,ver_relatorio,criado
                       FROM usuarios ORDER BY criado""")
        return jsonify([dict(r) for r in cur.fetchall()])

@app.route("/api/usuarios", methods=["POST"])
@login_required
def api_usuarios_post():
    if not so_admin():
        return jsonify({"erro": "Sem permissão"}), 403
    d = request.get_json() or {}
    login = (d.get("login") or "").strip().lower()
    if not login or not d.get("senha"):
        return jsonify({"erro": "Login e senha são obrigatórios"}), 400
    with db(commit=True) as cur:
        cur.execute("SELECT 1 FROM usuarios WHERE lower(login) = %s", (login,))
        if cur.fetchone():
            return jsonify({"erro": "Login já existe"}), 400
        cur.execute("""INSERT INTO usuarios (id,nome,login,senha,perfil,empresa_id,ativo,criado)
                       VALUES (%s,%s,%s,%s,%s,%s,TRUE,%s)""",
                    (str(int(datetime.now().timestamp()*1000)), d.get("nome",""), login,
                     generate_password_hash(d.get("senha","")),
                     d.get("perfil","funcionario"), d.get("empresa_id"), agora()))
    return jsonify({"ok": True})

@app.route("/api/usuarios/<uid>", methods=["PUT"])
@login_required
def api_usuarios_put(uid):
    if not so_admin():
        return jsonify({"erro": "Sem permissão"}), 403
    d = request.get_json() or {}
    with db(commit=True) as cur:
        cur.execute("""UPDATE usuarios SET
                       nome       = COALESCE(%s, nome),
                       perfil     = COALESCE(%s, perfil),
                       ativo      = COALESCE(%s, ativo),
                       empresa_id = COALESCE(%s, empresa_id)
                       WHERE id = %s""",
                    (d.get("nome"), d.get("perfil"), d.get("ativo"), d.get("empresa_id"), uid))
        if cur.rowcount == 0:
            return jsonify({"erro": "Não encontrado"}), 404
        if d.get("senha"):
            cur.execute("UPDATE usuarios SET senha = %s WHERE id = %s",
                        (generate_password_hash(d["senha"]), uid))
    return jsonify({"ok": True})

@app.route("/api/usuarios/<uid>", methods=["DELETE"])
@login_required
def api_usuarios_del(uid):
    if not so_admin():
        return jsonify({"erro": "Sem permissão"}), 403
    if uid == session.get('user_id'):
        return jsonify({"erro": "Não pode excluir a si mesmo"}), 400
    with db(commit=True) as cur:
        cur.execute("DELETE FROM usuarios WHERE id = %s", (uid,))
    return jsonify({"ok": True})

@app.route("/api/usuarios/<uid>/permissoes", methods=["PUT"])
@login_required
def api_permissoes(uid):
    if not so_admin():
        return jsonify({"erro": "Sem permissão"}), 403
    d = request.get_json() or {}
    with db(commit=True) as cur:
        cur.execute("UPDATE usuarios SET ver_relatorio = %s WHERE id = %s",
                    (bool(d.get('ver_relatorio', False)), uid))
        if cur.rowcount == 0:
            return jsonify({"erro": "Não encontrado"}), 404
    return jsonify({"ok": True})

# ── EMPRESAS ──────────────────────────────────────────────────
@app.route("/api/empresas", methods=["GET"])
@login_required
def api_empresas_get():
    if session.get('perfil') not in ['admin', 'funcionario']:
        return jsonify({"erro": "Sem permissão"}), 403
    with db() as cur:
        cur.execute("SELECT * FROM empresas ORDER BY nome")
        return jsonify([dict(r) for r in cur.fetchall()])

@app.route("/api/empresas", methods=["POST"])
@login_required
def api_empresas_post():
    if not so_admin():
        return jsonify({"erro": "Sem permissão"}), 403
    d = request.get_json() or {}
    if not d.get("nome"):
        return jsonify({"erro": "Nome é obrigatório"}), 400
    eid = str(int(datetime.now().timestamp()*1000))
    with db(commit=True) as cur:
        cur.execute("""INSERT INTO empresas (id,nome,cnpj,contato,tel,email,criado)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (eid, d.get("nome"), d.get("cnpj",""), d.get("contato",""),
                     d.get("tel",""), d.get("email",""), agora()))
    return jsonify({"ok": True, "id": eid})

@app.route("/api/empresas/<eid>", methods=["DELETE"])
@login_required
def api_empresas_del(eid):
    if not so_admin():
        return jsonify({"erro": "Sem permissão"}), 403
    with db(commit=True) as cur:
        cur.execute("DELETE FROM empresas WHERE id = %s", (eid,))
    return jsonify({"ok": True})

# ── LIMPEZA (só admin) ────────────────────────────────────────
def _limpar(tabelas):
    if not so_admin():
        return jsonify({"erro": "Sem permissão"}), 403
    with db(commit=True) as cur:
        for t in tabelas:
            cur.execute("DELETE FROM " + t)
    return jsonify({"ok": True})

@app.route("/api/limpar-tudo", methods=["POST"])
@login_required
def api_limpar_tudo():
    return _limpar(["atendimentos", "pessoas", "veiculos"])

@app.route("/api/historico-limpar", methods=["POST"])
@login_required
def api_hist_limpar():
    return _limpar(["atendimentos"])

@app.route("/api/pessoas-limpar", methods=["POST"])
@login_required
def api_pessoas_limpar():
    return _limpar(["pessoas"])

@app.route("/api/veiculos-limpar", methods=["POST"])
@login_required
def api_veiculos_limpar():
    return _limpar(["veiculos"])

# ── RELATÓRIOS ────────────────────────────────────────────────
def _valor(v):
    if not v:
        return 0.0
    try:
        return float(str(v).replace('R$', '').replace('.', '').replace(',', '.').strip() or 0)
    except ValueError:
        return 0.0

@app.route("/api/relatorios")
@login_required
def api_relatorios():
    perfil = session.get('perfil')
    if perfil == 'funcionario':
        with db() as cur:
            cur.execute("SELECT ver_relatorio FROM usuarios WHERE id = %s", (session.get('user_id'),))
            row = cur.fetchone()
        if not row or not row['ver_relatorio']:
            return jsonify({"erro": "Sem permissão para relatórios"}), 403

    cond, params = _escopo_empresa()
    de   = _data_br(request.args.get('de', ''))
    ate  = _data_br(request.args.get('ate', ''))
    func = request.args.get('func', '')
    emp  = request.args.get('emp', '')

    if de:
        cond += " AND criado >= %s"; params.append(de)
    if ate:
        cond += " AND criado < %s + INTERVAL '1 day'"; params.append(ate)
    if func and perfil == 'admin':
        cond += " AND user_id = %s"; params.append(func)
    if emp and perfil in ['admin', 'funcionario']:
        cond += " AND empresa_id = %s"; params.append(emp)

    with db() as cur:
        cur.execute("""SELECT id,data,nome,placa,modelo,vendedor_nome,chassi,valor_cobrado,
                              status_pgto,user_id,user_nome,empresa_id,
                              COALESCE(snap->>'c_nome','') AS comprador_nome
                       FROM atendimentos WHERE TRUE""" + cond + " ORDER BY id DESC", params)
        linhas = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT id,nome FROM empresas")
        empresas_map = {e['id']: e['nome'] for e in cur.fetchall()}

    total     = len(linhas)
    recebidos = sum(1 for h in linhas if h['status_pgto'] == 'pago')
    val_total    = sum(_valor(h['valor_cobrado']) for h in linhas)
    val_recebido = sum(_valor(h['valor_cobrado']) for h in linhas if h['status_pgto'] == 'pago')

    por_func, por_emp, por_mes = {}, {}, {}
    for h in linhas:
        v = _valor(h['valor_cobrado'])
        pago = h['status_pgto'] == 'pago'

        uid = h['user_id'] or '?'
        f = por_func.setdefault(uid, {'nome': h['user_nome'] or 'Desconhecido', 'total': 0,
                                      'recebidos': 0, 'val_total': 0, 'val_recebido': 0})
        f['total'] += 1; f['val_total'] += v
        if pago: f['recebidos'] += 1; f['val_recebido'] += v

        eid = h['empresa_id'] or 'escritorio'
        e = por_emp.setdefault(eid, {'nome': empresas_map.get(eid, 'Escritório'), 'total': 0,
                                     'recebidos': 0, 'val_total': 0, 'val_recebido': 0,
                                     'atendimentos': []})
        e['total'] += 1; e['val_total'] += v
        if pago: e['recebidos'] += 1; e['val_recebido'] += v
        e['atendimentos'].append({'placa': h['placa'], 'modelo': h['modelo'],
                                  'chassi': h['chassi'], 'vendedor': h['vendedor_nome'],
                                  'data': h['data'], 'valor': h['valor_cobrado'],
                                  'status': h['status_pgto']})

        mes = (h['data'] or '')[3:10] or '?'
        m = por_mes.setdefault(mes, {'total': 0, 'recebidos': 0, 'val_total': 0})
        m['total'] += 1; m['val_total'] += v
        if pago: m['recebidos'] += 1

    return jsonify({
        'total': total, 'recebidos': recebidos, 'pendentes': total - recebidos,
        'val_total': round(val_total, 2), 'val_recebido': round(val_recebido, 2),
        'val_pendente': round(val_total - val_recebido, 2),
        'por_func': list(por_func.values()),
        'por_emp': list(por_emp.values()),
        'por_mes': [{'mes': k, 'total': v['total'], 'recebidos': v['recebidos'],
                     'val_total': round(v['val_total'], 2)}
                    for k, v in sorted(por_mes.items(), reverse=True)],
        'atendimentos': [{'idx': h['id'], 'id': h['id'], 'data': h['data'], 'placa': h['placa'],
                          'modelo': h['modelo'], 'vendedor': h['vendedor_nome'],
                          'chassi': h['chassi'], 'func': h['user_nome'],
                          'comprador': h['comprador_nome'],
                          'empresa': empresas_map.get(h['empresa_id'], 'Escritório'),
                          'valor': h['valor_cobrado'], 'status': h['status_pgto']}
                         for h in linhas]
    })

# ── COFRE (só admin) ──────────────────────────────────────────
@app.route("/api/cofre", methods=["GET"])
@login_required
def api_cofre_get():
    if not so_admin():
        return jsonify({"erro": "Sem permissão"}), 403
    with db() as cur:
        cur.execute("SELECT id, descricao AS desc, valor AS val FROM cofre ORDER BY id")
        return jsonify([dict(r) for r in cur.fetchall()])

@app.route("/api/cofre", methods=["POST"])
@login_required
def api_cofre_post():
    if not so_admin():
        return jsonify({"erro": "Sem permissão"}), 403
    d = request.get_json() or {}
    if not d.get("desc") or not d.get("val"):
        return jsonify({"erro": "Preencha todos os campos"}), 400
    with db(commit=True) as cur:
        cur.execute("INSERT INTO cofre (descricao,valor) VALUES (%s,%s)", (d["desc"], d["val"]))
    return jsonify({"ok": True})

@app.route("/api/cofre/<int:cid>", methods=["DELETE"])
@login_required
def api_cofre_del(cid):
    if not so_admin():
        return jsonify({"erro": "Sem permissão"}), 403
    with db(commit=True) as cur:
        cur.execute("DELETE FROM cofre WHERE id = %s", (cid,))
    return jsonify({"ok": True})

# ── ASSINATURA ELETRÔNICA (ZapSign) ───────────────────────────
def _zapsign(caminho, payload=None, metodo="GET"):
    """Chama a API da ZapSign. Devolve (dados, erro)."""
    url = ZAPSIGN_API.rstrip("/") + caminho
    corpo = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=corpo, method=metodo, headers={
        "Authorization": "Bearer " + ZAPSIGN_TOKEN,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        detalhe = ""
        try:
            detalhe = e.read().decode("utf-8")[:400]
        except Exception:
            pass
        if e.code in (401, 403):
            return None, "Token da ZapSign inválido ou sem permissão para usar a API."
        return None, "ZapSign respondeu erro %s. %s" % (e.code, detalhe)
    except ValueError as e:
        return None, ("O token da ZapSign parece ter espaços ou quebras de linha. "
                      "Refaça o cadastro da variável ZAPSIGN_TOKEN no Render. (%s)" % e)
    except Exception as e:
        return None, "Não foi possível falar com a ZapSign: %s" % e

# Níveis de autenticação oferecidos ao cliente, do mais leve ao mais forte.
# 'extras' são os campos que a ZapSign usa para exigir cada verificação.
NIVEIS_ASSIN = {
    "simples": {
        "rotulo": "Apenas assinatura na tela",
        "auth_mode": "assinaturaTela",
        "extras": {},
    },
    "email": {
        "rotulo": "Código por e-mail + CPF conferido na Receita",
        "auth_mode": "assinaturaTela-tokenEmail",
        "exige_email": True, "exige_cpf": True,
        "extras": {"require_cpf": True, "validate_cpf": True},
    },
    "sms": {
        "rotulo": "Código por SMS + CPF conferido na Receita",
        "auth_mode": "assinaturaTela-tokenSms",
        "exige_fone": True, "exige_cpf": True,
        "extras": {"require_cpf": True, "validate_cpf": True},
    },
    "whatsapp": {
        "rotulo": "Código por WhatsApp + CPF conferido na Receita",
        "auth_mode": "assinaturaTela-tokenWhatsApp",
        "exige_fone": True, "exige_cpf": True,
        "extras": {"require_cpf": True, "validate_cpf": True},
    },
    "documento": {
        "rotulo": "WhatsApp + CPF + foto do documento e selfie",
        "auth_mode": "assinaturaTela-tokenWhatsApp",
        "exige_fone": True, "exige_cpf": True,
        "extras": {"require_cpf": True, "validate_cpf": True,
                   "require_document_photo": True, "require_selfie_photo": True},
    },
    "biometria": {
        "rotulo": "WhatsApp + CPF + biometria facial validada no governo",
        "auth_mode": "assinaturaTela-tokenWhatsApp",
        "exige_fone": True, "exige_cpf": True,
        "extras": {"require_cpf": True, "validate_cpf": True,
                   "require_document_photo": True, "require_selfie_photo": True,
                   "selfie_validation_type": "face-match-and-datavalid"},
    },
}

@app.route("/api/assinatura/niveis", methods=["GET"])
@login_required
def api_assin_niveis():
    return jsonify({"niveis": [
        {"id": k, "rotulo": v["rotulo"],
         "exige_fone": bool(v.get("exige_fone")),
         "exige_email": bool(v.get("exige_email")),
         "exige_cpf": bool(v.get("exige_cpf"))}
        for k, v in NIVEIS_ASSIN.items()]})

@app.route("/api/assinatura", methods=["POST"])
@login_required
def api_assinatura():
    if not ZAPSIGN_TOKEN:
        return jsonify({"erro": "Token da ZapSign não configurado. Adicione a variável ZAPSIGN_TOKEN no Render."}), 400
    data = request.get_json() or {}
    pdf  = (data.get("pdf_base64") or "").strip()
    nome = (data.get("nome") or "").strip()
    if not pdf:
        return jsonify({"erro": "PDF não recebido."}), 400
    if not nome:
        return jsonify({"erro": "Preencha o nome do vendedor antes de enviar para assinatura."}), 400
    if pdf.startswith("data:") and "," in pdf[:120]:
        pdf = pdf.split(",", 1)[1]

    # ── nível de autenticação exigido do cliente ──────────────
    nivel = (data.get("nivel") or "whatsapp").strip()
    if nivel not in NIVEIS_ASSIN:
        nivel = "whatsapp"
    regra = NIVEIS_ASSIN[nivel]

    email = (data.get("email") or "").strip()
    fone  = re.sub(r"\D", "", data.get("telefone") or "")
    cpf   = re.sub(r"\D", "", data.get("cpf") or "")

    if regra.get("exige_fone") and len(fone) < 10:
        return jsonify({"erro": "Para este nível o celular do cliente é obrigatório. "
                                "Preencha o campo Celular e tente de novo."}), 400
    if regra.get("exige_email") and not email:
        return jsonify({"erro": "Para este nível o e-mail do cliente é obrigatório."}), 400
    if regra.get("exige_cpf") and len(cpf) != 11:
        return jsonify({"erro": "Para este nível o CPF do cliente é obrigatório "
                                "(e precisa ser CPF, não CNPJ)."}), 400

    signer = {"name": nome, "auth_mode": regra["auth_mode"],
              "send_automatic_email": False, "send_automatic_whatsapp": False}
    if email:
        signer["email"] = email
    if len(fone) >= 10:
        signer["phone_country"] = "55"
        signer["phone_number"]  = fone[-11:]
    if len(cpf) == 11:
        signer["cpf"] = cpf
    for chave, valor in regra.get("extras", {}).items():
        signer[chave] = valor

    resp, erro = _zapsign("/docs/", {
        "name": (data.get("titulo") or "Procuração ATPV-e")[:255],
        "base64_pdf": pdf, "lang": "pt-br", "signers": [signer],
    }, "POST")
    if erro:
        return jsonify({"erro": erro}), 502

    signers   = resp.get("signers") or [{}]
    doc_token = resp.get("token", "")
    sign_url  = signers[0].get("sign_url", "")

    # Posiciona a assinatura exatamente sobre a linha do documento.
    # O PDF já leva uma marca invisível; isto reforça com as coordenadas.
    pos = data.get("posicao_assinatura") or {}
    signer_token = signers[0].get("token", "")
    aviso_posicao = ""
    if doc_token and signer_token and pos.get("relative_position_bottom") is not None:
        try:
            rubrica = {
                "page": int(pos.get("page", 0)),
                "relative_position_bottom": float(pos["relative_position_bottom"]),
                "relative_position_left":   float(pos.get("relative_position_left", 55)),
                "relative_size_x":          float(pos.get("relative_size_x", 19.55)),
                "relative_size_y":          float(pos.get("relative_size_y", 9.42)),
                "signer_token": signer_token,
                "type": "signature",
            }
            _, erro_pos = _zapsign("/docs/%s/place-signatures/" % doc_token,
                                   {"rubricas": [rubrica]}, "POST")
            if erro_pos:
                # Não é motivo para falhar o envio: a marca invisível no PDF
                # já orienta a ZapSign, e o cliente assina de qualquer forma.
                aviso_posicao = "Documento criado, mas não deu para fixar a posição da assinatura."
        except (TypeError, ValueError):
            aviso_posicao = "Posição da assinatura não pôde ser calculada."


    # Guarda o link no atendimento, quando informado — assim dá para
    # reabrir depois sem gastar outro documento do plano.
    aid = data.get("atendimento_id")
    if aid and sign_url:
        try:
            with db(commit=True) as cur:
                cur.execute("""UPDATE atendimentos SET assinatura_token=%s, assinatura_url=%s,
                                 assinatura_status=%s, assinatura_nome=%s,
                                 assinatura_nivel=%s, assinatura_em=NULL
                               WHERE id = %s""",
                            (doc_token, sign_url, resp.get("status","pending") or "pending",
                             signers[0].get("name", nome), nivel, int(aid)))
        except Exception:
            pass

    return jsonify({"ok": True, "doc_token": doc_token, "status": resp.get("status", ""),
                    "sign_url": sign_url, "signer_nome": signers[0].get("name", nome),
                    "nivel": nivel, "nivel_rotulo": regra["rotulo"],
                    "aviso": aviso_posicao})

@app.route("/api/assinatura/<doc_token>", methods=["GET"])
@login_required
def api_assinatura_status(doc_token):
    if not ZAPSIGN_TOKEN:
        return jsonify({"erro": "Token da ZapSign não configurado."}), 400
    resp, erro = _zapsign("/docs/%s/" % doc_token)
    if erro:
        return jsonify({"erro": erro}), 502
    return jsonify({
        "ok": True,
        "status": resp.get("status", ""),
        "signed_file": resp.get("signed_file", "") or "",
        "signers": [{"nome": s.get("name", ""), "status": s.get("status", ""),
                     "sign_url": s.get("sign_url", "")} for s in (resp.get("signers") or [])],
    })

# ══════════════════════════════════════════════════════════════
# ACOMPANHAMENTO DAS ASSINATURAS
# ══════════════════════════════════════════════════════════════
STATUS_ASSIN = {
    'pending':  'Aguardando assinatura',
    'signed':   'Assinado',
    'refused':  'Recusado pelo cliente',
    'deleted':  'Removido na ZapSign',
    'expired':  'Expirado',
}

def _assin_saida(r):
    d = dict(r)
    if d.get('assinatura_em'):
        d['assinatura_em'] = d['assinatura_em'].strftime('%d/%m/%Y %H:%M')
    d['status_label'] = STATUS_ASSIN.get(d.get('assinatura_status'),
                                         d.get('assinatura_status') or 'Aguardando assinatura')
    return d

def _atualizar_assinatura(cur, doc_token):
    """Consulta a ZapSign e grava o estado atual do documento.
    Devolve o status, ou None se não deu para consultar."""
    resp, erro = _zapsign("/docs/%s/" % doc_token)
    if erro:
        return None
    status   = resp.get("status", "") or ""
    arquivo  = resp.get("signed_file", "") or ""
    signers  = resp.get("signers") or [{}]
    quem     = signers[0].get("name", "") or ""
    assinado = (status == 'signed')
    cur.execute("""UPDATE atendimentos SET
                     assinatura_status  = %s,
                     assinatura_arquivo = %s,
                     assinatura_nome    = %s,
                     assinatura_em      = CASE WHEN %s THEN COALESCE(assinatura_em, NOW()) ELSE assinatura_em END
                   WHERE assinatura_token = %s""",
                (status, arquivo, quem, assinado, doc_token))
    return status

@app.route("/api/assinaturas", methods=["GET"])
@login_required
def api_assinaturas():
    """Documentos enviados para assinatura, mais recentes primeiro."""
    filtro = (request.args.get("status") or "").strip()
    q      = (request.args.get("q") or "").strip().lower()
    cond, params = _escopo_empresa()
    if filtro == 'pendentes':
        cond += " AND COALESCE(assinatura_status,'') <> 'signed'"
    elif filtro == 'assinados':
        cond += " AND assinatura_status = 'signed'"
    if q:
        cond += " AND (lower(nome) LIKE %s OR lower(placa) LIKE %s)"
        params += ['%'+q+'%', '%'+q+'%']

    with db() as cur:
        cur.execute("""SELECT id, data, nome, placa, modelo, assinatura_token, assinatura_url,
                              assinatura_status, assinatura_arquivo, assinatura_nome, assinatura_em
                       FROM atendimentos
                       WHERE COALESCE(assinatura_token,'') <> ''""" + cond +
                    " ORDER BY id DESC LIMIT 200", params)
        itens = [_assin_saida(r) for r in cur.fetchall()]
        cur.execute("""SELECT
              COUNT(*) FILTER (WHERE assinatura_status = 'signed')                  AS assinados,
              COUNT(*) FILTER (WHERE COALESCE(assinatura_status,'') NOT IN ('signed','refused','expired','deleted')) AS aguardando,
              COUNT(*) AS total
            FROM atendimentos WHERE COALESCE(assinatura_token,'') <> ''""" + cond, params)
        resumo = dict(cur.fetchone())
    return jsonify({"itens": itens, "resumo": resumo})

@app.route("/api/assinaturas/sincronizar", methods=["POST"])
@login_required
def api_assin_sincronizar():
    """Pergunta à ZapSign o estado dos documentos que ainda não foram assinados."""
    if not ZAPSIGN_TOKEN:
        return jsonify({"erro": "Token da ZapSign não configurado."}), 400
    cond, params = _escopo_empresa()
    with db(commit=True) as cur:
        cur.execute("""SELECT assinatura_token FROM atendimentos
                       WHERE COALESCE(assinatura_token,'') <> ''
                         AND COALESCE(assinatura_status,'') NOT IN ('signed','refused','deleted','expired')
                    """ + cond + " ORDER BY id DESC LIMIT 60", params)
        tokens = [r['assinatura_token'] for r in cur.fetchall()]
        novos = 0
        for t in tokens:
            if _atualizar_assinatura(cur, t) == 'signed':
                novos += 1
    return jsonify({"ok": True, "consultados": len(tokens), "assinados_agora": novos})

@app.route("/api/assinaturas/<int:aid>/atualizar", methods=["POST"])
@login_required
def api_assin_um(aid):
    """Atualiza um documento específico."""
    if not ZAPSIGN_TOKEN:
        return jsonify({"erro": "Token da ZapSign não configurado."}), 400
    cond, params = _escopo_empresa()
    with db(commit=True) as cur:
        cur.execute("SELECT assinatura_token FROM atendimentos WHERE id = %s" + cond,
                    [aid] + params)
        row = cur.fetchone()
        if not row or not row['assinatura_token']:
            return jsonify({"erro": "Este atendimento não tem documento enviado."}), 404
        status = _atualizar_assinatura(cur, row['assinatura_token'])
    if status is None:
        return jsonify({"erro": "Não foi possível consultar a ZapSign agora."}), 502
    return jsonify({"ok": True, "status": status,
                    "status_label": STATUS_ASSIN.get(status, status)})

@app.route("/api/zapsign-webhook", methods=["POST"])
def api_zapsign_webhook():
    """A ZapSign chama esta URL quando o documento muda de estado.
    Protegido pela mesma chave do alerta, passada na URL."""
    if ALERTA_CHAVE and (request.args.get("chave") or "") != ALERTA_CHAVE:
        return jsonify({"erro": "Chave inválida"}), 403
    dados = request.get_json(silent=True) or {}
    # O token do documento pode vir em nomes diferentes conforme o evento;
    # por isso procuramos em todos e usamos o webhook apenas como gatilho.
    token = ""
    for chave in ("token", "doc_token", "document_token", "external_id"):
        v = dados.get(chave)
        if isinstance(v, str) and v.strip():
            token = v.strip()
            break
    if not token and isinstance(dados.get("doc"), dict):
        token = (dados["doc"].get("token") or "").strip()
    if not token and isinstance(dados.get("document"), dict):
        token = (dados["document"].get("token") or "").strip()
    if not token:
        return jsonify({"ok": True, "ignorado": "sem token no aviso"}), 200
    try:
        with db(commit=True) as cur:
            # só mexe em documento que é nosso
            cur.execute("SELECT 1 FROM atendimentos WHERE assinatura_token = %s", (token,))
            if not cur.fetchone():
                return jsonify({"ok": True, "ignorado": "documento não é deste sistema"}), 200
            status = _atualizar_assinatura(cur, token)
    except Exception as e:
        return jsonify({"erro": str(e)}), 500
    return jsonify({"ok": True, "status": status})

@app.route("/api/zapsign-webhook/registrar", methods=["POST"])
@login_required
def api_zapsign_registrar():
    """Cadastra o aviso automático na ZapSign, apontando para este sistema."""
    if not so_admin():
        return jsonify({"erro": "Sem permissão"}), 403
    if not ZAPSIGN_TOKEN:
        return jsonify({"erro": "Token da ZapSign não configurado."}), 400
    base = (request.host_url or "").rstrip("/")
    if base.startswith("http://") and "localhost" not in base and "127.0.0.1" not in base:
        base = "https://" + base[len("http://"):]
    destino = base + "/api/zapsign-webhook"
    if ALERTA_CHAVE:
        destino += "?chave=" + ALERTA_CHAVE
    criados, erros = [], []
    for evento in ("doc_signed", "doc_refused"):
        resp, erro = _zapsign("/user/company/webhook/", {"url": destino, "type": evento}, "POST")
        if erro:
            erros.append("%s: %s" % (evento, erro))
        else:
            criados.append(evento)
    if not criados:
        return jsonify({"erro": " | ".join(erros) or "Não foi possível cadastrar."}), 502
    return jsonify({"ok": True, "eventos": criados, "url": destino,
                    "aviso": " | ".join(erros) if erros else ""})


# ══════════════════════════════════════════════════════════════
# RECURSOS DE MULTA E SUSPENSÃO DE CNH
# ══════════════════════════════════════════════════════════════
from datetime import date, timedelta

TIPOS_PROCESSO = {
    'multa':      'Recurso de multa',
    'suspensao':  'Suspensão do direito de dirigir',
    'cassacao':   'Cassação da CNH',
}
FASES = {
    'defesa_previa': 'Defesa prévia',
    'jari':          'Recurso à JARI',
    'cetran':        'Recurso ao CETRAN',
}
ORDEM_FASES = ['defesa_previa', 'jari', 'cetran']
STATUS = {
    'a_protocolar': 'A protocolar',
    'protocolado':  'Protocolado — aguardando julgamento',
    'deferido':     'Deferido (ganhou)',
    'indeferido':   'Indeferido',
    'arquivado':    'Arquivado',
}

def _data_iso(v):
    """Aceita '2026-09-25' ou '25/09/2026'. Devolve date ou None."""
    if not v:
        return None
    if isinstance(v, date):
        return v
    v = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None

def _calcular_prazo(data_notif, dias):
    d = _data_iso(data_notif)
    if not d:
        return None
    try:
        dias = int(dias)
    except (TypeError, ValueError):
        dias = 30
    return d + timedelta(days=dias)

def _andamento(cur, pid, descricao):
    cur.execute("""INSERT INTO processo_andamentos (processo_id,descricao,usuario)
                   VALUES (%s,%s,%s)""",
                (pid, descricao, session.get('user_nome') or ''))

def _escopo_proc():
    if session.get('perfil') == 'empresa':
        return " AND empresa_id = %s", [session.get('empresa_id')]
    return "", []

CAMPOS_PROC = """id, tipo, cliente_nome, cliente_cpf, cliente_tel, placa, ait, orgao,
                 infracao, fase, data_notificacao, prazo_dias, prazo_final, protocolo,
                 data_protocolo, status, resultado, valor_servico, status_pgto, obs,
                 user_nome, empresa_id, criado, atualizado"""

def _proc_saida(r):
    d = dict(r)
    for k in ('data_notificacao', 'prazo_final', 'data_protocolo'):
        if d.get(k):
            d[k] = d[k].isoformat()
    for k in ('criado', 'atualizado'):
        if d.get(k):
            d[k] = d[k].strftime('%d/%m/%Y %H:%M')
    d['tipo_label']   = TIPOS_PROCESSO.get(d.get('tipo'), d.get('tipo'))
    d['fase_label']   = FASES.get(d.get('fase'), d.get('fase'))
    d['status_label'] = STATUS.get(d.get('status'), d.get('status'))
    # dias restantes: negativo = vencido
    if d.get('prazo_final') and d.get('status') == 'a_protocolar':
        d['dias'] = (_data_iso(d['prazo_final']) - date.today()).days
    else:
        d['dias'] = None
    return d

@app.route("/api/processos", methods=["GET"])
@login_required
def api_proc_get():
    q      = (request.args.get("q") or "").strip().lower()
    status = (request.args.get("status") or "").strip()
    tipo   = (request.args.get("tipo") or "").strip()
    urg    = (request.args.get("urgencia") or "").strip()

    cond, params = _escopo_proc()
    if q:
        cond += (" AND (lower(cliente_nome) LIKE %s OR lower(placa) LIKE %s"
                 " OR lower(ait) LIKE %s OR lower(protocolo) LIKE %s)")
        params += ['%'+q+'%'] * 4
    if status:
        cond += " AND status = %s"; params.append(status)
    if tipo:
        cond += " AND tipo = %s"; params.append(tipo)
    if urg == 'vencidos':
        cond += " AND status = 'a_protocolar' AND prazo_final < CURRENT_DATE"
    elif urg == 'hoje':
        cond += " AND status = 'a_protocolar' AND prazo_final = CURRENT_DATE"
    elif urg == 'semana':
        cond += " AND status = 'a_protocolar' AND prazo_final BETWEEN CURRENT_DATE AND CURRENT_DATE + 7"
    elif urg == 'abertos':
        cond += " AND status IN ('a_protocolar','protocolado')"

    with db() as cur:
        cur.execute("SELECT " + CAMPOS_PROC + """ FROM processos WHERE TRUE""" + cond +
                    """ ORDER BY (status = 'a_protocolar') DESC,
                                 prazo_final ASC NULLS LAST, id DESC LIMIT 300""", params)
        itens = [_proc_saida(r) for r in cur.fetchall()]
    return jsonify({"itens": itens, "total": len(itens)})

def _resumo_prazos(cur, cond="", params=None):
    """Contagem por urgência, para o painel e para o alerta."""
    params = params or []
    cur.execute("""SELECT
          COUNT(*) FILTER (WHERE prazo_final <  CURRENT_DATE)                                AS vencidos,
          COUNT(*) FILTER (WHERE prazo_final =  CURRENT_DATE)                                AS hoje,
          COUNT(*) FILTER (WHERE prazo_final BETWEEN CURRENT_DATE + 1 AND CURRENT_DATE + 3)  AS tres_dias,
          COUNT(*) FILTER (WHERE prazo_final BETWEEN CURRENT_DATE + 4 AND CURRENT_DATE + 7)  AS semana,
          COUNT(*)                                                                           AS a_protocolar
        FROM processos
        WHERE status = 'a_protocolar' AND prazo_final IS NOT NULL""" + cond, params)
    return dict(cur.fetchone())

@app.route("/api/processos/prazos", methods=["GET"])
@login_required
def api_proc_prazos():
    cond, params = _escopo_proc()
    with db() as cur:
        resumo = _resumo_prazos(cur, cond, params)
        cur.execute("SELECT " + CAMPOS_PROC + """ FROM processos
                     WHERE status = 'a_protocolar' AND prazo_final IS NOT NULL
                       AND prazo_final <= CURRENT_DATE + 7""" + cond +
                    " ORDER BY prazo_final ASC LIMIT 100", params)
        urgentes = [_proc_saida(r) for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) AS n FROM processos WHERE status='protocolado'" + cond, params)
        resumo['aguardando'] = cur.fetchone()['n']
    return jsonify({"resumo": resumo, "urgentes": urgentes})

@app.route("/api/processos", methods=["POST"])
@login_required
def api_proc_post():
    d = request.get_json() or {}
    if not (d.get("cliente_nome") or "").strip():
        return jsonify({"erro": "Informe o nome do cliente."}), 400
    notif = _data_iso(d.get("data_notificacao"))
    if not notif:
        return jsonify({"erro": "Informe a data da notificação."}), 400
    dias  = d.get("prazo_dias") or 30
    prazo = _data_iso(d.get("prazo_final")) or _calcular_prazo(notif, dias)

    with db(commit=True) as cur:
        cur.execute("""INSERT INTO processos
            (tipo,cliente_nome,cliente_cpf,cliente_tel,placa,ait,orgao,infracao,fase,
             data_notificacao,prazo_dias,prazo_final,valor_servico,status_pgto,obs,
             user_id,user_nome,empresa_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (d.get("tipo","multa"), d.get("cliente_nome","").strip(), d.get("cliente_cpf",""),
             d.get("cliente_tel",""), (d.get("placa","") or "").upper(), d.get("ait",""),
             d.get("orgao",""), d.get("infracao",""), d.get("fase","defesa_previa"),
             notif, int(dias), prazo, d.get("valor_servico",""),
             d.get("status_pgto") or "pendente", d.get("obs",""),
             str(session.get('user_id') or ""), session.get('user_nome') or "",
             session.get('empresa_id')))
        pid = cur.fetchone()['id']
        _andamento(cur, pid, "Processo cadastrado — %s, prazo até %s" %
                   (FASES.get(d.get("fase","defesa_previa"), ""), prazo.strftime("%d/%m/%Y") if prazo else "—"))
    return jsonify({"ok": True, "id": pid})

@app.route("/api/processos/<int:pid>", methods=["GET"])
@login_required
def api_proc_um(pid):
    cond, params = _escopo_proc()
    with db() as cur:
        cur.execute("SELECT " + CAMPOS_PROC + " FROM processos WHERE id = %s" + cond,
                    [pid] + params)
        row = cur.fetchone()
        if not row:
            return jsonify({"erro": "Não encontrado"}), 404
        proc = _proc_saida(row)
        cur.execute("""SELECT id, quando, descricao, usuario FROM processo_andamentos
                       WHERE processo_id = %s ORDER BY id DESC""", (pid,))
        andamentos = [{"id": a['id'], "quando": a['quando'].strftime('%d/%m/%Y %H:%M'),
                       "descricao": a['descricao'], "usuario": a['usuario']}
                      for a in cur.fetchall()]
    return jsonify({"ok": True, "processo": proc, "andamentos": andamentos})

@app.route("/api/processos/<int:pid>", methods=["PUT"])
@login_required
def api_proc_put(pid):
    d = request.get_json() or {}
    cond, params = _escopo_proc()
    notif = _data_iso(d.get("data_notificacao"))
    dias  = d.get("prazo_dias")
    prazo = _data_iso(d.get("prazo_final"))
    if prazo is None and notif and dias:
        prazo = _calcular_prazo(notif, dias)
    with db(commit=True) as cur:
        cur.execute("""UPDATE processos SET
              tipo = COALESCE(%s,tipo), cliente_nome = COALESCE(%s,cliente_nome),
              cliente_cpf = COALESCE(%s,cliente_cpf), cliente_tel = COALESCE(%s,cliente_tel),
              placa = COALESCE(%s,placa), ait = COALESCE(%s,ait), orgao = COALESCE(%s,orgao),
              infracao = COALESCE(%s,infracao), data_notificacao = COALESCE(%s,data_notificacao),
              prazo_dias = COALESCE(%s,prazo_dias), prazo_final = COALESCE(%s,prazo_final),
              valor_servico = COALESCE(%s,valor_servico), status_pgto = COALESCE(%s,status_pgto),
              obs = COALESCE(%s,obs), atualizado = NOW()
            WHERE id = %s""" + cond,
            [d.get("tipo"), d.get("cliente_nome"), d.get("cliente_cpf"), d.get("cliente_tel"),
             (d.get("placa") or None), d.get("ait"), d.get("orgao"), d.get("infracao"),
             notif, (int(dias) if dias else None), prazo,
             d.get("valor_servico"), d.get("status_pgto"), d.get("obs"), pid] + params)
        if cur.rowcount == 0:
            return jsonify({"erro": "Não encontrado"}), 404
        _andamento(cur, pid, "Dados do processo atualizados")
    return jsonify({"ok": True})

@app.route("/api/processos/<int:pid>/protocolar", methods=["POST"])
@login_required
def api_proc_protocolar(pid):
    """Registra o protocolo: o processo sai do alerta de prazo."""
    d = request.get_json() or {}
    protocolo = (d.get("protocolo") or "").strip()
    quando    = _data_iso(d.get("data_protocolo")) or date.today()
    if not protocolo:
        return jsonify({"erro": "Informe o número do protocolo."}), 400
    cond, params = _escopo_proc()
    with db(commit=True) as cur:
        cur.execute("""UPDATE processos SET protocolo=%s, data_protocolo=%s,
                       status='protocolado', atualizado=NOW()
                       WHERE id=%s""" + cond, [protocolo, quando, pid] + params)
        if cur.rowcount == 0:
            return jsonify({"erro": "Não encontrado"}), 404
        _andamento(cur, pid, "Protocolado em %s sob nº %s" %
                   (quando.strftime("%d/%m/%Y"), protocolo))
    return jsonify({"ok": True})

@app.route("/api/processos/<int:pid>/resultado", methods=["POST"])
@login_required
def api_proc_resultado(pid):
    """Registra o julgamento. Se indeferido, pode abrir a fase seguinte."""
    d = request.get_json() or {}
    novo = d.get("status")
    if novo not in ('deferido', 'indeferido', 'arquivado'):
        return jsonify({"erro": "Resultado inválido."}), 400
    cond, params = _escopo_proc()
    with db(commit=True) as cur:
        cur.execute("SELECT fase FROM processos WHERE id=%s" + cond, [pid] + params)
        row = cur.fetchone()
        if not row:
            return jsonify({"erro": "Não encontrado"}), 404
        fase_atual = row['fase']

        cur.execute("""UPDATE processos SET status=%s, resultado=COALESCE(%s,resultado),
                       atualizado=NOW() WHERE id=%s""" + cond,
                    [novo, d.get("resultado"), pid] + params)
        _andamento(cur, pid, "%s em %s — %s" % (STATUS[novo], FASES.get(fase_atual, fase_atual),
                                                d.get("resultado") or "sem observação"))

        # Indeferido + pedido de avanço -> abre a próxima instância
        if novo == 'indeferido' and d.get("avancar"):
            i = ORDEM_FASES.index(fase_atual) if fase_atual in ORDEM_FASES else -1
            if i < 0 or i + 1 >= len(ORDEM_FASES):
                return jsonify({"ok": True, "aviso": "Não há instância seguinte nesta esfera."})
            prox   = ORDEM_FASES[i + 1]
            notif  = _data_iso(d.get("data_notificacao")) or date.today()
            dias   = int(d.get("prazo_dias") or 30)
            prazo  = _calcular_prazo(notif, dias)
            cur.execute("""UPDATE processos SET fase=%s, status='a_protocolar',
                           data_notificacao=%s, prazo_dias=%s, prazo_final=%s,
                           protocolo='', data_protocolo=NULL, atualizado=NOW()
                           WHERE id=%s""" + cond, [prox, notif, dias, prazo, pid] + params)
            _andamento(cur, pid, "Avançou para %s — novo prazo até %s" %
                       (FASES[prox], prazo.strftime("%d/%m/%Y")))
    return jsonify({"ok": True})

@app.route("/api/processos/<int:pid>/andamentos", methods=["POST"])
@login_required
def api_proc_andamento(pid):
    d = request.get_json() or {}
    texto = (d.get("descricao") or "").strip()
    if not texto:
        return jsonify({"erro": "Escreva o andamento."}), 400
    cond, params = _escopo_proc()
    with db(commit=True) as cur:
        cur.execute("SELECT 1 FROM processos WHERE id=%s" + cond, [pid] + params)
        if not cur.fetchone():
            return jsonify({"erro": "Não encontrado"}), 404
        _andamento(cur, pid, texto)
    return jsonify({"ok": True})

@app.route("/api/processos/<int:pid>", methods=["DELETE"])
@login_required
def api_proc_del(pid):
    cond, params = _escopo_proc()
    with db(commit=True) as cur:
        cur.execute("DELETE FROM processos WHERE id=%s" + cond, [pid] + params)
        if cur.rowcount == 0:
            return jsonify({"erro": "Não encontrado"}), 404
    return jsonify({"ok": True})

# ── ALERTA DIÁRIO DE PRAZOS (Telegram) ────────────────────────
def _telegram(texto):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False, "Telegram não configurado (falta TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID)."
    url = "https://api.telegram.org/bot%s/sendMessage" % TELEGRAM_TOKEN
    corpo = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": texto,
                        "parse_mode": "HTML", "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(url, data=corpo, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        return True, "enviado"
    except Exception as e:
        return False, "Falha ao enviar no Telegram: %s" % e

def _monta_alerta():
    with db() as cur:
        cur.execute("""SELECT id, cliente_nome, placa, ait, tipo, fase, prazo_final,
                              (prazo_final - CURRENT_DATE) AS dias
                       FROM processos
                       WHERE status = 'a_protocolar' AND prazo_final IS NOT NULL
                         AND prazo_final <= CURRENT_DATE + 7
                       ORDER BY prazo_final ASC""")
        linhas = [dict(r) for r in cur.fetchall()]
    if not linhas:
        return None, 0

    grupos = {"🔴 VENCIDOS": [], "🟠 VENCE HOJE": [], "🟡 PRÓXIMOS 3 DIAS": [], "🔵 ESTA SEMANA": []}
    for r in linhas:
        dias = r['dias']
        if   dias <  0: g = "🔴 VENCIDOS"
        elif dias == 0: g = "🟠 VENCE HOJE"
        elif dias <= 3: g = "🟡 PRÓXIMOS 3 DIAS"
        else:           g = "🔵 ESTA SEMANA"
        ident = " · ".join(x for x in [r['placa'], ("AIT " + r['ait']) if r['ait'] else ""] if x)
        quando = r['prazo_final'].strftime("%d/%m")
        if   dias <  0: obs = "venceu há %d dia(s)" % abs(dias)
        elif dias == 0: obs = "vence HOJE"
        else:           obs = "faltam %d dia(s)" % dias
        grupos[g].append("• <b>%s</b>%s\n   %s — %s (%s)" % (
            r['cliente_nome'], (" — " + ident) if ident else "",
            FASES.get(r['fase'], r['fase']), quando, obs))

    partes = ["<b>⚖️ PRAZOS DE RECURSO</b>", date.today().strftime("%d/%m/%Y"), ""]
    for titulo, itens in grupos.items():
        if itens:
            partes.append("<b>%s (%d)</b>" % (titulo, len(itens)))
            partes.extend(itens)
            partes.append("")
    return "\n".join(partes).strip(), len(linhas)

@app.route("/api/alerta-prazos", methods=["GET", "POST"])
def api_alerta_prazos():
    """Disparado por um agendador diário. Protegido por chave."""
    if ALERTA_CHAVE:
        if (request.args.get("chave") or "") != ALERTA_CHAVE:
            return jsonify({"erro": "Chave inválida"}), 403
    elif 'user_id' not in session:
        return jsonify({"erro": "Não autorizado"}), 401

    texto, quantos = _monta_alerta()
    if not texto:
        return jsonify({"ok": True, "enviado": False, "motivo": "Nenhum prazo nos próximos 7 dias."})
    ok, detalhe = _telegram(texto)
    return jsonify({"ok": ok, "enviado": ok, "processos": quantos, "detalhe": detalhe})

@app.route("/api/alerta-teste", methods=["POST"])
@login_required
def api_alerta_teste():
    """Botão 'testar alerta' dentro do sistema."""
    if not so_admin():
        return jsonify({"erro": "Sem permissão"}), 403
    texto, quantos = _monta_alerta()
    if not texto:
        texto, quantos = "<b>⚖️ Teste do alerta de prazos</b>\nNenhum prazo vencendo nos próximos 7 dias.", 0
    ok, detalhe = _telegram(texto)
    return jsonify({"ok": ok, "processos": quantos, "detalhe": detalhe})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
