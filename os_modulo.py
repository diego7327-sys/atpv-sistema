# -*- coding: utf-8 -*-
"""
MÓDULO ORDEM DE SERVIÇO (modelo BitDesp)
-----------------------------------------
A OS é o centro: cliente, veículo, itens (taxas/serviços com valor e custo),
honorário, recebimentos, ocorrências (histórico de status), pendências com
data limite, observações e documentos ficam pendurados nela.

Financeiro mínimo: contas, formas de pagamento, centros de valores e
lançamentos. Todo recebimento da OS gera sozinho um crédito em lancamentos.

Valores em NUMERIC(12,2). Total/pago/devedor são calculados na consulta.

Registrado no app.py com:  from os_modulo import registrar; registrar(app, db, login_required)
"""
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
import re
import json

from flask import request, jsonify, session

SCHEMA_OS = """
CREATE TABLE IF NOT EXISTS clientes (
    id BIGSERIAL PRIMARY KEY,
    cpf_cnpj TEXT DEFAULT '', nome TEXT NOT NULL,
    nasc TEXT DEFAULT '', rg TEXT DEFAULT '', rg_org TEXT DEFAULT '', cnh TEXT DEFAULT '',
    ecivil TEXT DEFAULT '',
    cep TEXT DEFAULT '', endereco TEXT DEFAULT '', numero TEXT DEFAULT '', complemento TEXT DEFAULT '',
    bairro TEXT DEFAULT '', cidade TEXT DEFAULT '',
    fone TEXT DEFAULT '', cel TEXT DEFAULT '', email TEXT DEFAULT '',
    tipo TEXT DEFAULT 'pf',
    forma_pgto_padrao TEXT DEFAULT '',
    obs TEXT DEFAULT '',
    empresa_id TEXT,
    criado TIMESTAMPTZ DEFAULT NOW(), atualizado TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS clientes_doc_uniq ON clientes (cpf_cnpj) WHERE cpf_cnpj <> '';
CREATE INDEX IF NOT EXISTS clientes_nome_idx ON clientes (lower(nome));

ALTER TABLE veiculos ADD COLUMN IF NOT EXISTS renavam TEXT DEFAULT '';
ALTER TABLE veiculos ADD COLUMN IF NOT EXISTS ano_fab TEXT DEFAULT '';
ALTER TABLE veiculos ADD COLUMN IF NOT EXISTS ano_mod TEXT DEFAULT '';
ALTER TABLE veiculos ADD COLUMN IF NOT EXISTS cor TEXT DEFAULT '';
ALTER TABLE veiculos ADD COLUMN IF NOT EXISTS combustivel TEXT DEFAULT '';
ALTER TABLE veiculos ADD COLUMN IF NOT EXISTS categoria TEXT DEFAULT '';
ALTER TABLE veiculos ADD COLUMN IF NOT EXISTS municipio TEXT DEFAULT '';
ALTER TABLE veiculos ADD COLUMN IF NOT EXISTS proprietario_id BIGINT REFERENCES clientes(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS veiculos_renavam_idx ON veiculos (renavam);

CREATE TABLE IF NOT EXISTS contas (
    id BIGSERIAL PRIMARY KEY, nome TEXT NOT NULL, saldo_inicial NUMERIC(12,2) DEFAULT 0,
    ativo BOOLEAN DEFAULT TRUE);
CREATE TABLE IF NOT EXISTS centros_valor (
    id BIGSERIAL PRIMARY KEY, nome TEXT NOT NULL, ativo BOOLEAN DEFAULT TRUE);
CREATE TABLE IF NOT EXISTS formas_pgto (
    id BIGSERIAL PRIMARY KEY, nome TEXT NOT NULL, taxa_pct NUMERIC(5,2) DEFAULT 0,
    ativo BOOLEAN DEFAULT TRUE);

CREATE TABLE IF NOT EXISTS servicos (
    id BIGSERIAL PRIMARY KEY, nome TEXT NOT NULL,
    valor_padrao NUMERIC(12,2) DEFAULT 0,
    custo_padrao NUMERIC(12,2) DEFAULT 0,
    centro_id BIGINT REFERENCES centros_valor(id) ON DELETE SET NULL,
    ativo BOOLEAN DEFAULT TRUE, empresa_id TEXT);

CREATE TABLE IF NOT EXISTS ordens_servico (
    id BIGSERIAL PRIMARY KEY,
    numero BIGINT UNIQUE NOT NULL,
    tipo TEXT DEFAULT 'os',
    data_abertura TIMESTAMPTZ DEFAULT NOW(),
    validade DATE,
    cliente_id BIGINT REFERENCES clientes(id),
    responsavel_id BIGINT REFERENCES clientes(id),
    veiculo_id BIGINT REFERENCES veiculos(id),
    despachante TEXT DEFAULT '',
    user_id TEXT DEFAULT '', user_nome TEXT DEFAULT '',
    status TEXT DEFAULT 'andamento',
    codigo_web TEXT DEFAULT '', protocolo TEXT DEFAULT '',
    data_nf_crv DATE, valor_nf_crv NUMERIC(12,2),
    proprietario_anterior TEXT DEFAULT '',
    restricao_financeira TEXT DEFAULT '', financeira TEXT DEFAULT '',
    honorario NUMERIC(12,2) DEFAULT 0,
    obs TEXT DEFAULT '',
    arquivada BOOLEAN DEFAULT FALSE,
    excluida_em TIMESTAMPTZ, excluida_por TEXT DEFAULT '',
    atendimento_id BIGINT,
    empresa_id TEXT,
    atualizado TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS os_status_idx  ON ordens_servico (status, data_abertura);
CREATE INDEX IF NOT EXISTS os_cliente_idx ON ordens_servico (cliente_id);
CREATE INDEX IF NOT EXISTS os_veiculo_idx ON ordens_servico (veiculo_id);

CREATE TABLE IF NOT EXISTS os_itens (
    id BIGSERIAL PRIMARY KEY,
    os_id BIGINT REFERENCES ordens_servico(id) ON DELETE CASCADE,
    servico_id BIGINT REFERENCES servicos(id) ON DELETE SET NULL,
    descricao TEXT DEFAULT '',
    qtd NUMERIC(10,2) DEFAULT 1,
    valor NUMERIC(12,2) DEFAULT 0,
    custo NUMERIC(12,2) DEFAULT 0,
    criado TIMESTAMPTZ DEFAULT NOW(), user_nome TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS os_itens_os_idx ON os_itens (os_id);

CREATE TABLE IF NOT EXISTS lancamentos (
    id BIGSERIAL PRIMARY KEY,
    natureza TEXT NOT NULL,
    vencimento DATE, pago_em TIMESTAMPTZ,
    descricao TEXT DEFAULT '', favorecido TEXT DEFAULT '', documento TEXT DEFAULT '',
    valor NUMERIC(12,2) NOT NULL, valor_pago NUMERIC(12,2) DEFAULT 0,
    conta_id BIGINT REFERENCES contas(id),
    conta_destino_id BIGINT REFERENCES contas(id),
    centro_id BIGINT REFERENCES centros_valor(id),
    forma_pgto_id BIGINT REFERENCES formas_pgto(id),
    os_id BIGINT REFERENCES ordens_servico(id) ON DELETE SET NULL,
    obs TEXT DEFAULT '',
    user_nome TEXT DEFAULT '', empresa_id TEXT,
    criado TIMESTAMPTZ DEFAULT NOW());
CREATE INDEX IF NOT EXISTS lanc_pago_idx ON lancamentos (pago_em);

CREATE TABLE IF NOT EXISTS os_recebimentos (
    id BIGSERIAL PRIMARY KEY,
    os_id BIGINT REFERENCES ordens_servico(id) ON DELETE CASCADE,
    quando TIMESTAMPTZ DEFAULT NOW(),
    valor NUMERIC(12,2) NOT NULL,
    forma_pgto_id BIGINT REFERENCES formas_pgto(id),
    conta_id BIGINT REFERENCES contas(id),
    centro_id BIGINT REFERENCES centros_valor(id),
    obs TEXT DEFAULT '', user_nome TEXT DEFAULT '',
    lancamento_id BIGINT REFERENCES lancamentos(id) ON DELETE SET NULL);
CREATE INDEX IF NOT EXISTS os_receb_os_idx ON os_recebimentos (os_id);

CREATE TABLE IF NOT EXISTS os_ocorrencias (
    id BIGSERIAL PRIMARY KEY,
    os_id BIGINT REFERENCES ordens_servico(id) ON DELETE CASCADE,
    quando TIMESTAMPTZ DEFAULT NOW(),
    tipo TEXT DEFAULT 'outras',
    descricao TEXT DEFAULT '', obs TEXT DEFAULT '', user_nome TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS os_ocor_os_idx ON os_ocorrencias (os_id, id);

CREATE TABLE IF NOT EXISTS pendencia_tipos (
    id BIGSERIAL PRIMARY KEY, nome TEXT NOT NULL, ativo BOOLEAN DEFAULT TRUE);
CREATE TABLE IF NOT EXISTS os_pendencias (
    id BIGSERIAL PRIMARY KEY,
    os_id BIGINT REFERENCES ordens_servico(id) ON DELETE CASCADE,
    tipo_id BIGINT REFERENCES pendencia_tipos(id) ON DELETE SET NULL,
    lancado TIMESTAMPTZ DEFAULT NOW(),
    limite DATE,
    responsavel TEXT DEFAULT '', descricao TEXT DEFAULT '',
    resolvida BOOLEAN DEFAULT FALSE, resolvida_em TIMESTAMPTZ, resolvida_por TEXT DEFAULT '',
    user_nome TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS pend_aberta_idx ON os_pendencias (resolvida, limite);

CREATE TABLE IF NOT EXISTS os_documentos (
    id BIGSERIAL PRIMARY KEY,
    os_id BIGINT REFERENCES ordens_servico(id) ON DELETE CASCADE,
    nome TEXT DEFAULT '', url TEXT DEFAULT '',
    enviado TIMESTAMPTZ DEFAULT NOW(), user_nome TEXT DEFAULT '');

CREATE TABLE IF NOT EXISTS processo_tipos (
    id BIGSERIAL PRIMARY KEY, nome TEXT NOT NULL, ativo BOOLEAN DEFAULT TRUE);
ALTER TABLE ordens_servico ADD COLUMN IF NOT EXISTS processo_tipo_id BIGINT REFERENCES processo_tipos(id) ON DELETE SET NULL;
ALTER TABLE servicos       ADD COLUMN IF NOT EXISTS processo_tipo_id BIGINT REFERENCES processo_tipos(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS os_ptipo_idx ON ordens_servico (processo_tipo_id);
ALTER TABLE ordens_servico ADD COLUMN IF NOT EXISTS desconto NUMERIC(12,2) DEFAULT 0;
ALTER TABLE ordens_servico ADD COLUMN IF NOT EXISTS obs_cliente TEXT DEFAULT '';
CREATE TABLE IF NOT EXISTS servico_pacotes (
    id BIGSERIAL PRIMARY KEY, nome TEXT NOT NULL,
    servicos JSONB DEFAULT '[]'::jsonb,
    ordem INT DEFAULT 0, ativo BOOLEAN DEFAULT TRUE);

ALTER TABLE IF EXISTS processos ADD COLUMN IF NOT EXISTS os_id BIGINT REFERENCES ordens_servico(id) ON DELETE SET NULL;
ALTER TABLE IF EXISTS usuarios  ADD COLUMN IF NOT EXISTS conta_padrao_id BIGINT;
ALTER TABLE IF EXISTS usuarios  ADD COLUMN IF NOT EXISTS ver_lucro BOOLEAN DEFAULT FALSE;
ALTER TABLE IF EXISTS usuarios  ADD COLUMN IF NOT EXISTS dar_baixa BOOLEAN DEFAULT FALSE;
ALTER TABLE IF EXISTS usuarios  ADD COLUMN IF NOT EXISTS ver_pend_todos BOOLEAN DEFAULT FALSE;
ALTER TABLE os_pendencias ADD COLUMN IF NOT EXISTS user_id TEXT DEFAULT '';
ALTER TABLE os_recebimentos ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'confirmado';
ALTER TABLE os_recebimentos ADD COLUMN IF NOT EXISTS baixa_por TEXT DEFAULT '';
ALTER TABLE os_recebimentos ADD COLUMN IF NOT EXISTS baixa_em TIMESTAMPTZ;
ALTER TABLE os_recebimentos ADD COLUMN IF NOT EXISTS recusa_motivo TEXT DEFAULT '';
CREATE INDEX IF NOT EXISTS os_receb_status_idx ON os_recebimentos (status);
ALTER TABLE IF EXISTS usuarios  ADD COLUMN IF NOT EXISTS forma_padrao_id BIGINT;
"""

# Cadastros iniciais — tirados das telas do BitDesp (levantamento de 13/11/2026)
SEED_CONTAS = ["SICRED", "BRADESCO", "CAIXA"]
SEED_FORMAS = ["PIX", "DINHEIRO", "DÉBITO", "PARCELADO"]
SEED_CENTROS = [
    "ATPV", "COMUNICADO DE VENDA PELO DENATRAN", "OUTROS", "PAGAMENTO SEM MULTAS",
    "PAGAMENTO TAXAS/DÉBITOS", "PAGAMENTOS DE TAXAS/DÉBITOS E SERVIÇOS PRESTADOS",
    "PARCELAMENTO DÉBITOS CARTÃO", "PLACA VINDA SÃO PAULO", "PONTUAÇÃO",
    "PROTOCOLO EM GERAL E SERVIÇO DESPACHANTE", "PROTOCOLO TRANSFERÊNCIA DE PONTUAÇÃO",
    "RECURSO DE INFRAÇÃO E SERVIÇO DESPACHANTE", "SERVIÇOS PRESTADOS", "SUSPENSÃO CNH",
    "TAXAS DETRAN", "TRANSFERÊNCIA DE PROPRIEDADE",
]
SEED_SERVICOS = [  # (nome, valor, custo, centro)
    ("TRANSFERÊNCIA NOME", "333.00", "332.00", "TRANSFERÊNCIA DE PROPRIEDADE"),
    ("VISTORIA", "108.00", "108.00", "TAXAS DETRAN"),
    ("AGENDAMENTO VISTORIA", "38.00", "2.00", "SERVIÇOS PRESTADOS"),
    ("ATPV", "50.00", "10.00", "ATPV"),
    ("MUDANÇA CATEGORIA", "188.00", "135.00", "SERVIÇOS PRESTADOS"),
    ("CANCELAR COMUNICADO SP", "120.00", "50.00", "SERVIÇOS PRESTADOS"),
]
# Tipo de processo da OS (para puxar depois). Transferência de nome e de município = TRANSFERÊNCIA.
SEED_TIPOS_PROCESSO = ["TRANSFERÊNCIA", "ALTERAÇÃO DE CARACTERÍSTICA", "LEILÃO", "ATPV",
                       "COMUNICAÇÃO DE VENDA", "SUSPENSÃO DE CNH", "RECURSO DE MULTA",
                       "CADASTRO ANTT", "REGULARIZAÇÃO DE REBAIXADO", "OUTROS"]
SEED_SERVICO_TIPO = {"TRANSFERÊNCIA NOME": "TRANSFERÊNCIA", "MUDANÇA CATEGORIA": "ALTERAÇÃO DE CARACTERÍSTICA",
                     "ATPV": "ATPV", "CANCELAR COMUNICADO SP": "COMUNICAÇÃO DE VENDA"}
SEED_PENDENCIAS = ["PONTUAÇÃO", "SUSPENSÃO", "SUSPENSÃO CNH", "RECEBER",
                   "PROCESSO JUDICIAL", "ALT IMETRO"]

# Dados da empresa que saem no orçamento enviado ao cliente (Financeiro → Cadastros)
PEND_ATALHOS = ("OLHAR SE FINALIZOU PROCESSO", "VER SE PAGOU MULTA", "MANDAR DIGITAL CLIENTE", "FINALIZAR INCLUIR NA ANTT")
CFG_EMPRESA = ("empresa_nome", "empresa_fone", "empresa_endereco", "empresa_cidade", "empresa_email",
               "pix_chave", "pix_nome", "pix_cidade", "pix_banco")

EMPRESA_PADRAO = {"empresa_nome": "Diego Despachante", "empresa_fone": "(62) 99110-1506 · (62) 99267-3252",
                  "empresa_endereco": "Av. Brasil, 464 - Vila Jussara", "empresa_cidade": "Anápolis-GO",
                  "empresa_email": "diego7327@hotmail.com"}

STATUS_OS = {
    'orcamento':  'Orçamento',
    'andamento':  'Em andamento',
    'detran':     'No Detran',
    'disponivel': 'Disponível p/ entrega',
    'entregue':   'Entregue',
    'concluida':  'Concluída',
    'cancelada':  'Cancelada',
}

CAMPOS_CLIENTE = ("cpf_cnpj", "nome", "nasc", "rg", "rg_org", "cnh", "ecivil", "cep",
                  "endereco", "numero", "complemento", "bairro", "cidade", "fone", "cel",
                  "email", "tipo", "forma_pgto_padrao", "obs")
CAMPOS_VEICULO = ("placa", "renavam", "chassi", "modelo", "ano_fab", "ano_mod", "cor",
                  "combustivel", "categoria", "municipio")
CAMPOS_OS_EDIT = ("obs_cliente", "despachante", "codigo_web", "protocolo", "proprietario_anterior",
                  "restricao_financeira", "financeira", "obs")


# ── utilidades ────────────────────────────────────────────────
BRT = timezone(timedelta(hours=-3))          # Brasília (sem horário de verão desde 2019)
HOJE_SQL = "(NOW() AT TIME ZONE 'America/Sao_Paulo')::date"

def _agora():
    return datetime.now(BRT)

def _hoje():
    return _agora().date()

def _num(v, padrao=Decimal('0')):
    """Aceita 1.234,56 | 1234,56 | 1234.56 | número. Devolve Decimal."""
    if v is None or v == '':
        return padrao
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v)).quantize(Decimal('0.01'))
    s = str(v).strip().replace('R$', '').replace(' ', '')
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    try:
        return Decimal(s).quantize(Decimal('0.01'))
    except InvalidOperation:
        return padrao

def _f(v):
    return float(v) if v is not None else 0.0

def _data(v):
    if not v:
        return None
    if isinstance(v, date):
        return v
    s = str(v).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None

def _dt(v):
    if not v:
        return ''
    if getattr(v, 'tzinfo', None):
        v = v.astimezone(BRT)
    return v.strftime('%d/%m/%Y %H:%M')

def _d(v):
    return v.isoformat() if v else ''

def _so_dig(s):
    return re.sub(r'\D', '', s or '')

def _fmt_doc(s):
    d = _so_dig(s)
    if len(d) == 11:
        return "%s.%s.%s-%s" % (d[:3], d[3:6], d[6:9], d[9:])
    if len(d) == 14:
        return "%s.%s.%s/%s-%s" % (d[:2], d[2:5], d[5:8], d[8:12], d[12:])
    return (s or '').strip()

def _eu():
    return session.get('user_nome') or ''

def _admin():
    return session.get('perfil') == 'admin'


def registrar(app, db, login_required):
    """Cria as tabelas, roda as migrações e registra as rotas do módulo OS."""

    # ── banco ─────────────────────────────────────────────────
    def _init():
        with db(commit=True) as cur:
            cur.execute("SELECT pg_advisory_xact_lock(918273646)")
            cur.execute(SCHEMA_OS)
            cur.execute("SELECT 1 FROM migracoes WHERE nome = 'os_seed_v1'")
            if not cur.fetchone():
                for n in SEED_CONTAS:
                    cur.execute("INSERT INTO contas (nome) VALUES (%s)", (n,))
                for n in SEED_FORMAS:
                    cur.execute("INSERT INTO formas_pgto (nome) VALUES (%s)", (n,))
                for n in SEED_CENTROS:
                    cur.execute("INSERT INTO centros_valor (nome) VALUES (%s)", (n,))
                for n, v, c, cen in SEED_SERVICOS:
                    cur.execute("""INSERT INTO servicos (nome, valor_padrao, custo_padrao, centro_id)
                                   VALUES (%s,%s,%s,(SELECT id FROM centros_valor WHERE nome=%s LIMIT 1))""",
                                (n, v, c, cen))
                for n in SEED_PENDENCIAS:
                    cur.execute("INSERT INTO pendencia_tipos (nome) VALUES (%s)", (n,))
                cur.execute("INSERT INTO migracoes (nome) VALUES ('os_seed_v1')")
            cur.execute("SELECT 1 FROM migracoes WHERE nome = 'os_tipos_v1'")
            if not cur.fetchone():
                cur.execute("SELECT COUNT(*) AS n FROM processo_tipos")
                if cur.fetchone()['n'] == 0:
                    for n in SEED_TIPOS_PROCESSO:
                        cur.execute("INSERT INTO processo_tipos (nome) VALUES (%s)", (n,))
                for sv, tp in SEED_SERVICO_TIPO.items():
                    cur.execute("""UPDATE servicos SET processo_tipo_id =
                                     (SELECT id FROM processo_tipos WHERE nome = %s LIMIT 1)
                                   WHERE nome = %s AND processo_tipo_id IS NULL""", (tp, sv))
                cur.execute("INSERT INTO migracoes (nome) VALUES ('os_tipos_v1')")
            cur.execute("SELECT 1 FROM migracoes WHERE nome = 'os_pacotes_v1'")
            if not cur.fetchone():
                cur.execute("SELECT COUNT(*) AS n FROM servico_pacotes")
                if cur.fetchone()['n'] == 0:
                    cur.execute("""SELECT id, nome FROM servicos WHERE nome = ANY(%s)""",
                                (["TRANSFERÊNCIA NOME", "VISTORIA", "AGENDAMENTO VISTORIA"],))
                    ids = {r['nome']: r['id'] for r in cur.fetchall()}
                    if len(ids) == 3:
                        cur.execute("INSERT INTO servico_pacotes (nome, servicos, ordem) VALUES (%s, %s::jsonb, 1)",
                                    ("Transferência", json.dumps([ids["TRANSFERÊNCIA NOME"], ids["VISTORIA"],
                                                                   ids["AGENDAMENTO VISTORIA"]])))
                cur.execute("INSERT INTO migracoes (nome) VALUES ('os_pacotes_v1')")
            cur.execute("SELECT 1 FROM migracoes WHERE nome = 'os_pend_atalhos_v1'")
            if not cur.fetchone():
                for n in PEND_ATALHOS:
                    cur.execute("SELECT 1 FROM pendencia_tipos WHERE upper(nome) = upper(%s)", (n,))
                    if not cur.fetchone():
                        cur.execute("INSERT INTO pendencia_tipos (nome) VALUES (%s)", (n,))
                cur.execute("INSERT INTO migracoes (nome) VALUES ('os_pend_atalhos_v1')")
            cur.execute("SELECT 1 FROM migracoes WHERE nome = 'os_pend_atalhos_v2'")
            if not cur.fetchone():
                # pontuação / suspensão / processo judicial ficam na aba Agenda de Prazos, não nos atalhos da OS
                cur.execute("UPDATE pendencia_tipos SET ativo = FALSE WHERE upper(nome) = ANY(%s)",
                            (["PONTUAÇÃO", "SUSPENSÃO", "SUSPENSÃO CNH", "PROCESSO JUDICIAL"],))
                cur.execute("INSERT INTO migracoes (nome) VALUES ('os_pend_atalhos_v2')")
            _sincronizar_clientes(cur)

    def _sincronizar_clientes(cur, filtro_sql="", filtro_params=None):
        """Copia para clientes as pessoas e contratantes (do ATPV) que ainda não
        estão lá. Não apaga nem altera nada nas tabelas antigas."""
        fp = filtro_params or []
        cur.execute("""
            INSERT INTO clientes (cpf_cnpj, nome, nasc, rg, rg_org, ecivil, endereco, bairro,
                                  cidade, cep, cel, email, tipo)
            SELECT DISTINCT ON (regexp_replace(p.cpf,'\\D','','g')) p.cpf, p.nome, p.nasc, p.rg, p.rg_org, p.ecivil, p.endereco,
                   p.bairro, p.cidade, p.cep, p.cel, p.email,
                   CASE WHEN length(regexp_replace(p.cpf,'\\D','','g')) = 14 THEN 'pj' ELSE 'pf' END
            FROM pessoas p
            WHERE p.cpf <> '' AND p.nome <> ''
              AND NOT EXISTS (SELECT 1 FROM clientes c
                              WHERE regexp_replace(c.cpf_cnpj,'\\D','','g') = regexp_replace(p.cpf,'\\D','','g'))""" +
            filtro_sql.replace('{t}', 'p'), fp)
        cur.execute("""
            INSERT INTO clientes (cpf_cnpj, nome, cel, tipo, forma_pgto_padrao)
            SELECT DISTINCT ON (regexp_replace(t.cpf,'\\D','','g')) t.cpf, t.nome, t.tel,
                   CASE WHEN t.tipo ~* '(garag|revend|loja|concession|empresa)' THEN 'revenda'
                        WHEN length(regexp_replace(t.cpf,'\\D','','g')) = 14 THEN 'pj' ELSE 'pf' END,
                   t.pgto
            FROM contratantes t
            WHERE t.cpf <> '' AND t.nome <> ''
              AND NOT EXISTS (SELECT 1 FROM clientes c
                              WHERE regexp_replace(c.cpf_cnpj,'\\D','','g') = regexp_replace(t.cpf,'\\D','','g'))""" +
            filtro_sql.replace('{t}', 't'), fp)

    try:
        _init()
        print("Módulo OS pronto.")
    except Exception as e:
        print("Erro ao inicializar módulo OS: %s" % e)

    # ── permissões ────────────────────────────────────────────
    def equipe(f):
        """OS e financeiro: só admin e funcionário (empresa/garagem não entra)."""
        @wraps(f)
        def dec(*a, **k):
            if 'user_id' not in session:
                return jsonify({"erro": "Não autorizado"}), 401
            if session.get('perfil') not in ('admin', 'funcionario'):
                return jsonify({"erro": "Sem permissão"}), 403
            return f(*a, **k)
        return dec

    def _perms(cur=None):
        """ver_lucro / dar_baixa / ver_pend_todos: admin sempre; outros só se o admin marcar."""
        if _admin():
            return {"ver_lucro": True, "dar_baixa": True, "ver_pend_todos": True, "admin": True}
        def busca(c):
            c.execute("SELECT ver_lucro, dar_baixa, ver_pend_todos FROM usuarios WHERE id = %s", (str(session.get('user_id')),))
            return c.fetchone() or {}
        u = busca(cur) if cur is not None else None
        if u is None:
            with db() as c2:
                u = busca(c2)
        return {"ver_lucro": bool(u.get('ver_lucro')), "dar_baixa": bool(u.get('dar_baixa')),
                "ver_pend_todos": bool(u.get('ver_pend_todos')), "admin": False}

    def _pend_filtro(cur, alias='p'):
        """Pendências: cada um vê só as que marcou; admin (ou quem ele liberar) vê de todos."""
        if _perms(cur)['ver_pend_todos']:
            return "", ()
        return (" AND ({a}.user_id = %s OR (COALESCE({a}.user_id,'') = '' AND {a}.user_nome = %s))".format(a=alias),
                (str(session.get('user_id') or ''), _eu()))

    CAMPOS_LUCRO = ('custo', 'lucro', 'lucro_terceiros', 'taxas', 'honorarios')

    def _sem_lucro_os(o):
        for k in CAMPOS_LUCRO:
            o.pop(k, None)
        return o

    def _os_por_numero(cur, numero, incluir_excluida=False):
        cur.execute("SELECT * FROM ordens_servico WHERE numero = %s" +
                    ("" if incluir_excluida else " AND excluida_em IS NULL"), (numero,))
        return cur.fetchone()

    def _ocorrencia(cur, os_id, tipo, descricao, obs=''):
        cur.execute("""INSERT INTO os_ocorrencias (os_id, tipo, descricao, obs, user_nome)
                       VALUES (%s,%s,%s,%s,%s)""", (os_id, tipo, descricao, obs, _eu()))

    def _toca(cur, os_id):
        cur.execute("UPDATE ordens_servico SET atualizado = NOW() WHERE id = %s", (os_id,))

    def _cliente_saida(r):
        if not r:
            return None
        d = dict(r)
        for k in ('criado', 'atualizado'):
            d[k] = _dt(d.get(k))
        return d

    def _veiculo_saida(r):
        if not r:
            return None
        d = dict(r)
        d.pop('atualizado', None)
        return d

    # Totais calculados (nunca gravados)
    SQL_TOTAIS = """
        COALESCE((SELECT SUM(i.valor*i.qtd) FROM os_itens i WHERE i.os_id = o.id),0) AS itens_valor,
        COALESCE((SELECT SUM(i.custo*i.qtd) FROM os_itens i WHERE i.os_id = o.id),0) AS itens_custo,
        COALESCE((SELECT SUM(r.valor) FROM os_recebimentos r WHERE r.os_id = o.id AND r.status = 'confirmado'),0) AS pago,
        COALESCE((SELECT SUM(r.valor) FROM os_recebimentos r WHERE r.os_id = o.id AND r.status = 'pendente'),0) AS aguardando,
        COALESCE((SELECT COUNT(*) FROM os_pendencias p WHERE p.os_id = o.id AND NOT p.resolvida),0) AS pend_abertas
    """

    def _os_saida(r):
        d = dict(r)
        itens_valor = _f(d.pop('itens_valor', 0))
        itens_custo = _f(d.pop('itens_custo', 0))
        honor = _f(d.get('honorario'))
        pago = _f(d.pop('pago', 0))
        aguardando = _f(d.pop('aguardando', 0))
        desc = _f(d.get('desconto'))
        total = round(itens_valor + honor - desc, 2)
        # orçamento e OS cancelada não geram saldo a receber
        cobravel = d.get('status') not in ('orcamento', 'cancelada')
        d.update({
            'honorario': honor,
            'valor_nf_crv': _f(d.get('valor_nf_crv')) if d.get('valor_nf_crv') is not None else None,
            'itens_valor': round(itens_valor, 2), 'custo': round(itens_custo, 2),
            'total': total, 'pago': round(pago, 2), 'devedor': round(total - pago, 2) if cobravel else 0.0,
            'lucro_terceiros': round(itens_valor - itens_custo, 2),
            'lucro': round(honor + itens_valor - itens_custo - desc, 2),
            'desconto': desc,
            'aguardando_baixa': round(aguardando, 2),
            'taxas': round(itens_custo, 2),
            'honorarios': round(honor + itens_valor - itens_custo, 2),
            'status_label': STATUS_OS.get(d.get('status'), d.get('status')),
            'data_abertura': _dt(d.get('data_abertura')),
            'data_abertura_iso': d['data_abertura'].astimezone(BRT).date().isoformat() if r.get('data_abertura') else '',
            'atualizado': _dt(d.get('atualizado')),
            'excluida_em': _dt(d.get('excluida_em')),
            'validade': _d(d.get('validade')),
            'data_nf_crv': _d(d.get('data_nf_crv')),
        })
        return d

    def _proximo_numero(cur):
        cur.execute("SELECT pg_advisory_xact_lock(55001)")
        cur.execute("SELECT COALESCE(MAX(numero),0) AS m FROM ordens_servico")
        maior = cur.fetchone()['m']
        cur.execute("SELECT valor FROM config WHERE chave = 'os_numero_inicial'")
        row = cur.fetchone()
        try:
            inicial = int(row['valor']) if row and row['valor'] else 1
        except ValueError:
            inicial = 1
        return max(maior + 1, inicial)

    # ── CLIENTES ──────────────────────────────────────────────
    @app.route("/api/clientes", methods=["GET"])
    @equipe
    def os_clientes_get():
        q = (request.args.get("q") or "").strip().lower()
        dig = _so_dig(q)
        with db(commit=True) as cur:
            if q:
                # traz na hora quem só existe no cadastro antigo do ATPV
                filtro = (" AND (lower({t}.nome) LIKE %s OR regexp_replace({t}.cpf,'\\D','','g') LIKE %s)")
                _sincronizar_clientes(cur, filtro, ['%' + q + '%', '%' + (dig or q) + '%'])
                cur.execute("""SELECT * FROM clientes
                               WHERE lower(nome) LIKE %s OR regexp_replace(cpf_cnpj,'\\D','','g') LIKE %s
                                  OR regexp_replace(cel,'\\D','','g') LIKE %s
                               ORDER BY (lower(nome) LIKE %s) DESC, nome LIMIT 30""",
                            ('%' + q + '%', '%' + (dig or q) + '%', '%' + (dig or '#') + '%', q + '%'))
            else:
                cur.execute("SELECT * FROM clientes ORDER BY atualizado DESC LIMIT 50")
            return jsonify([_cliente_saida(r) for r in cur.fetchall()])

    @app.route("/api/clientes/<int:cid>", methods=["GET"])
    @equipe
    def os_cliente_um(cid):
        with db() as cur:
            cur.execute("SELECT * FROM clientes WHERE id = %s", (cid,))
            c = cur.fetchone()
            if not c:
                return jsonify({"erro": "Cliente não encontrado"}), 404
            cur.execute("""SELECT o.*, """ + SQL_TOTAIS + """ FROM ordens_servico o
                           WHERE (o.cliente_id = %s OR o.responsavel_id = %s) AND o.excluida_em IS NULL
                           ORDER BY o.numero DESC LIMIT 100""", (cid, cid))
            oss = [_os_saida(r) for r in cur.fetchall()]
            if not _perms(cur)['ver_lucro']:
                oss = [_sem_lucro_os(x) for x in oss]
            cur.execute("SELECT * FROM veiculos WHERE proprietario_id = %s ORDER BY placa", (cid,))
            veics = [_veiculo_saida(r) for r in cur.fetchall()]
        return jsonify({"cliente": _cliente_saida(c), "os": oss, "veiculos": veics})

    @app.route("/api/clientes", methods=["POST"])
    @equipe
    def os_cliente_salvar():
        d = request.get_json() or {}
        nome = (d.get("nome") or "").strip().upper()
        if not nome:
            return jsonify({"erro": "Informe o nome do cliente."}), 400
        vals = {k: (d.get(k) or "").strip() for k in CAMPOS_CLIENTE}
        vals['nome'] = nome
        vals['cpf_cnpj'] = _fmt_doc(vals['cpf_cnpj'])
        if vals['tipo'] not in ('pf', 'pj', 'revenda'):
            vals['tipo'] = 'pj' if len(_so_dig(vals['cpf_cnpj'])) == 14 else 'pf'
        cid = d.get("id")
        with db(commit=True) as cur:
            if vals['cpf_cnpj']:
                cur.execute("SELECT id FROM clientes WHERE regexp_replace(cpf_cnpj,'\\D','','g') = %s",
                            (_so_dig(vals['cpf_cnpj']) or vals['cpf_cnpj'],))
                ex = cur.fetchone()
                if ex and str(ex['id']) != str(cid or ''):
                    if cid:
                        return jsonify({"erro": "Já existe outro cliente com este CPF/CNPJ."}), 400
                    cid = ex['id']  # mesmo documento: atualiza o cadastro existente
            cols = list(CAMPOS_CLIENTE)
            if cid:
                # só altera o que veio na tela (não apaga campos que a tela não mostra)
                cols = [c for c in CAMPOS_CLIENTE if c in d or c == 'nome']
                if 'tipo' not in d and 'cpf_cnpj' not in d and 'tipo' in cols:
                    cols.remove('tipo')
                cur.execute("UPDATE clientes SET " + ", ".join(c + "=%s" for c in cols) +
                            ", atualizado = NOW() WHERE id = %s RETURNING id",
                            [vals[c] for c in cols] + [cid])
                row = cur.fetchone()
                if not row:
                    return jsonify({"erro": "Cliente não encontrado"}), 404
            else:
                cur.execute("INSERT INTO clientes (" + ", ".join(cols) + ", empresa_id) VALUES (" +
                            ", ".join(["%s"] * len(cols)) + ", %s) RETURNING id",
                            [vals[c] for c in cols] + [session.get('empresa_id')])
                row = cur.fetchone()
            cur.execute("SELECT * FROM clientes WHERE id = %s", (row['id'],))
            return jsonify({"ok": True, "cliente": _cliente_saida(cur.fetchone())})

    # ── VEÍCULOS (cadastro completo; a tabela é a mesma do ATPV) ─
    @app.route("/api/os-veiculos", methods=["GET"])
    @equipe
    def os_veiculos_get():
        q = (request.args.get("q") or "").strip().lower()
        with db() as cur:
            base = """SELECT v.*, c.nome AS proprietario_nome, c.cpf_cnpj AS proprietario_doc
                      FROM veiculos v LEFT JOIN clientes c ON c.id = v.proprietario_id"""
            if q:
                qq = q.replace('-', '')
                cur.execute(base + """ WHERE replace(lower(v.placa),'-','') LIKE %s OR lower(v.renavam) LIKE %s
                               OR lower(v.chassi) LIKE %s OR lower(v.modelo) LIKE %s
                               ORDER BY v.placa LIMIT 30""",
                            ('%' + qq + '%', '%' + q + '%', '%' + q + '%', '%' + q + '%'))
            else:
                cur.execute(base + " ORDER BY v.id DESC LIMIT 50")
            return jsonify([_veiculo_saida(r) for r in cur.fetchall()])

    @app.route("/api/os-veiculos/<int:vid>", methods=["GET"])
    @equipe
    def os_veiculo_um(vid):
        with db() as cur:
            cur.execute("""SELECT v.*, c.nome AS proprietario_nome, c.cpf_cnpj AS proprietario_doc
                           FROM veiculos v LEFT JOIN clientes c ON c.id = v.proprietario_id
                           WHERE v.id = %s""", (vid,))
            v = cur.fetchone()
        if not v:
            return jsonify({"erro": "Veículo não encontrado"}), 404
        return jsonify({"veiculo": _veiculo_saida(v)})

    @app.route("/api/os-veiculos", methods=["POST"])
    @equipe
    def os_veiculo_salvar():
        d = request.get_json() or {}
        vals = {k: (d.get(k) or "").strip().upper() for k in CAMPOS_VEICULO}
        vals['placa'] = vals['placa'].replace('-', '').replace(' ', '')
        if not vals['placa']:
            return jsonify({"erro": "Informe a placa."}), 400
        prop = d.get("proprietario_id") or None
        ano = "/".join(x for x in (vals['ano_fab'], vals['ano_mod']) if x)
        vid = d.get("id")
        with db(commit=True) as cur:
            cur.execute("SELECT id FROM veiculos WHERE upper(replace(placa,'-','')) = %s", (vals['placa'],))
            ex = cur.fetchone()
            if ex and str(ex['id']) != str(vid or ''):
                if vid:
                    return jsonify({"erro": "Já existe outro veículo com esta placa."}), 400
                vid = ex['id']
            cols = list(CAMPOS_VEICULO)
            if vid:
                cols = [c for c in CAMPOS_VEICULO if c in d or c == 'placa']
                extra, ev = "", []
                if 'proprietario_id' in d:
                    extra += ", proprietario_id=%s"; ev.append(prop)
                cur.execute("UPDATE veiculos SET " + ", ".join(c + "=%s" for c in cols) + extra +
                            ", ano = CASE WHEN %s <> '' THEN %s ELSE ano END,"
                            " atualizado=%s WHERE id = %s RETURNING id",
                            [vals[c] for c in cols] + ev + [ano, ano,
                             _agora().strftime("%d/%m/%Y %H:%M"), vid])
                row = cur.fetchone()
                if not row:
                    return jsonify({"erro": "Veículo não encontrado"}), 404
            else:
                cur.execute("INSERT INTO veiculos (" + ", ".join(cols) +
                            ", proprietario_id, ano, atualizado) VALUES (" +
                            ", ".join(["%s"] * len(cols)) + ", %s, %s, %s) RETURNING id",
                            [vals[c] for c in cols] + [prop, ano,
                             _agora().strftime("%d/%m/%Y %H:%M")])
                row = cur.fetchone()
            cur.execute("""SELECT v.*, c.nome AS proprietario_nome, c.cpf_cnpj AS proprietario_doc
                           FROM veiculos v LEFT JOIN clientes c ON c.id = v.proprietario_id
                           WHERE v.id = %s""", (row['id'],))
            return jsonify({"ok": True, "veiculo": _veiculo_saida(cur.fetchone())})

    # ── TABELA DE SERVIÇOS ────────────────────────────────────
    @app.route("/api/servicos", methods=["GET"])
    @equipe
    def os_servicos_get():
        todos = request.args.get("todos") == "1"
        with db() as cur:
            vl = _perms(cur)['ver_lucro']
            cur.execute("""SELECT s.*, c.nome AS centro_nome, pt.nome AS processo_tipo FROM servicos s
                           LEFT JOIN centros_valor c ON c.id = s.centro_id
                           LEFT JOIN processo_tipos pt ON pt.id = s.processo_tipo_id""" +
                        ("" if todos else " WHERE s.ativo") + " ORDER BY s.ativo DESC, s.nome")
            out = []
            for r in cur.fetchall():
                x = dict(r)
                x['valor_padrao'] = _f(x['valor_padrao'])
                x['custo_padrao'] = _f(x['custo_padrao'])
                if not vl:
                    x.pop('custo_padrao', None)
                out.append(x)
        return jsonify(out)

    @app.route("/api/servicos", methods=["POST"])
    @equipe
    def os_servico_salvar():
        if not _admin():
            return jsonify({"erro": "Só o administrador altera a tabela de serviços."}), 403
        d = request.get_json() or {}
        nome = (d.get("nome") or "").strip().upper()
        if not nome:
            return jsonify({"erro": "Informe o nome do serviço."}), 400
        vals = (nome, _num(d.get("valor_padrao")), _num(d.get("custo_padrao")),
                d.get("centro_id") or None, _sim(d.get("ativo"), True), d.get("processo_tipo_id") or None)
        with db(commit=True) as cur:
            if d.get("id"):
                cur.execute("""UPDATE servicos SET nome=%s, valor_padrao=%s, custo_padrao=%s,
                               centro_id=%s, ativo=%s, processo_tipo_id=%s WHERE id=%s""", vals + (d["id"],))
            else:
                cur.execute("""INSERT INTO servicos (nome, valor_padrao, custo_padrao, centro_id, ativo, processo_tipo_id)
                               VALUES (%s,%s,%s,%s,%s,%s)""", vals)
        return jsonify({"ok": True})

    # ── CADASTROS DO FINANCEIRO + TIPOS DE PENDÊNCIA ───────────
    TABELAS_CAD = {'tipos': 'processo_tipos', 'contas': 'contas', 'formas': 'formas_pgto', 'centros': 'centros_valor',
                   'pendencias': 'pendencia_tipos'}

    @app.route("/api/fin/cadastros", methods=["GET"])
    @equipe
    def os_fin_cadastros():
        out = {}
        with db() as cur:
            for k, t in TABELAS_CAD.items():
                cur.execute("SELECT * FROM " + t + " ORDER BY ativo DESC, nome")
                lst = []
                for r in cur.fetchall():
                    x = dict(r)
                    for c in ('saldo_inicial', 'taxa_pct'):
                        if c in x:
                            x[c] = _f(x[c])
                    lst.append(x)
                out[k] = lst
            cur.execute("SELECT conta_padrao_id, forma_padrao_id FROM usuarios WHERE id = %s",
                        (str(session.get('user_id')),))
            u = cur.fetchone() or {}
            out['meus_padroes'] = {"conta_id": u.get('conta_padrao_id'), "forma_id": u.get('forma_padrao_id')}
            cur.execute("SELECT valor FROM config WHERE chave = 'os_numero_inicial'")
            row = cur.fetchone()
            out['os_numero_inicial'] = row['valor'] if row else ''
            cur.execute("SELECT chave, valor FROM config WHERE chave = ANY(%s)", (list(CFG_EMPRESA),))
            emp = {k: '' for k in CFG_EMPRESA}
            emp.update(EMPRESA_PADRAO)  # vale enquanto não for alterado em Financeiro > Cadastros
            for r in cur.fetchall():
                if r['valor'] is not None:
                    emp[r['chave']] = r['valor']
            out['empresa'] = emp
            cur.execute("SELECT * FROM servico_pacotes WHERE ativo ORDER BY ordem, nome")
            out['pacotes'] = [dict(r) for r in cur.fetchall()]
            out['proximo_numero'] = None
        with db(commit=False) as cur:
            cur.execute("SELECT COALESCE(MAX(numero),0) AS m FROM ordens_servico")
            m = cur.fetchone()['m']
            try:
                ini = int(out['os_numero_inicial'] or 1)
            except ValueError:
                ini = 1
            out['proximo_numero'] = max(m + 1, ini)
        return jsonify(out)

    @app.route("/api/fin/<tipo>", methods=["POST"])
    @equipe
    def os_fin_cad_salvar(tipo):
        if tipo not in TABELAS_CAD:
            return jsonify({"erro": "Cadastro inválido"}), 404
        if not _admin():
            return jsonify({"erro": "Só o administrador altera estes cadastros."}), 403
        d = request.get_json() or {}
        nome = (d.get("nome") or "").strip().upper()
        if not nome:
            return jsonify({"erro": "Informe o nome."}), 400
        t = TABELAS_CAD[tipo]
        ativo = _sim(d.get("ativo"), True)
        with db(commit=True) as cur:
            if d.get("id"):
                cur.execute("UPDATE " + t + " SET nome=%s, ativo=%s WHERE id=%s", (nome, ativo, d["id"]))
                if tipo == 'contas' and d.get("saldo_inicial") is not None:
                    cur.execute("UPDATE contas SET saldo_inicial=%s WHERE id=%s",
                                (_num(d.get("saldo_inicial")), d["id"]))
            else:
                cur.execute("INSERT INTO " + t + " (nome) VALUES (%s) RETURNING id", (nome,))
                nid = cur.fetchone()['id']
                if tipo == 'contas':
                    cur.execute("UPDATE contas SET saldo_inicial=%s WHERE id=%s",
                                (_num(d.get("saldo_inicial")), nid))
        return jsonify({"ok": True})

    @app.route("/api/fin/meus-padroes", methods=["PUT"])
    @equipe
    def os_fin_meus_padroes():
        d = request.get_json() or {}
        with db(commit=True) as cur:
            cur.execute("UPDATE usuarios SET conta_padrao_id=%s, forma_padrao_id=%s WHERE id=%s",
                        (d.get("conta_id") or None, d.get("forma_id") or None, str(session.get('user_id'))))
        return jsonify({"ok": True})

    @app.route("/api/os-config", methods=["POST"])
    @equipe
    def os_config_salvar():
        if not _admin():
            return jsonify({"erro": "Sem permissão"}), 403
        d = request.get_json() or {}
        with db(commit=True) as cur:
            if "os_numero_inicial" in d:
                ini = _so_dig(str(d.get("os_numero_inicial") or ""))
                cur.execute("""INSERT INTO config (chave, valor) VALUES ('os_numero_inicial', %s)
                               ON CONFLICT (chave) DO UPDATE SET valor = EXCLUDED.valor, atualizado = NOW()""",
                            (ini,))
            for k in CFG_EMPRESA:
                if k in d:
                    cur.execute("""INSERT INTO config (chave, valor) VALUES (%s, %s)
                                   ON CONFLICT (chave) DO UPDATE SET valor = EXCLUDED.valor, atualizado = NOW()""",
                                (k, (d.get(k) or "").strip()))
        return jsonify({"ok": True})

    # ── PACOTES (botões que lançam vários serviços de uma vez) ──
    @app.route("/api/pacotes", methods=["GET"])
    @equipe
    def os_pacotes_get():
        with db() as cur:
            cur.execute("SELECT * FROM servico_pacotes ORDER BY ativo DESC, ordem, nome")
            return jsonify([dict(r) for r in cur.fetchall()])

    @app.route("/api/pacotes", methods=["POST"])
    @equipe
    def os_pacote_salvar():
        if not _admin():
            return jsonify({"erro": "Só o administrador altera os pacotes."}), 403
        d = request.get_json() or {}
        nome = (d.get("nome") or "").strip()
        sv = [int(x) for x in (d.get("servicos") or []) if str(x).isdigit()]
        if not nome or not sv:
            return jsonify({"erro": "Informe o nome e escolha os serviços do pacote."}), 400
        with db(commit=True) as cur:
            if d.get("id"):
                cur.execute("UPDATE servico_pacotes SET nome=%s, servicos=%s::jsonb, ativo=%s WHERE id=%s",
                            (nome, json.dumps(sv), _sim(d.get("ativo"), True), d["id"]))
            else:
                cur.execute("INSERT INTO servico_pacotes (nome, servicos) VALUES (%s, %s::jsonb)",
                            (nome, json.dumps(sv)))
        return jsonify({"ok": True})

    @app.route("/api/pacotes/<int:pid>", methods=["DELETE"])
    @equipe
    def os_pacote_del(pid):
        if not _admin():
            return jsonify({"erro": "Sem permissão"}), 403
        with db(commit=True) as cur:
            cur.execute("DELETE FROM servico_pacotes WHERE id=%s", (pid,))
        return jsonify({"ok": True})

    # ── ORDEM DE SERVIÇO: lista / painel ───────────────────────
    @app.route("/api/os", methods=["GET"])
    @equipe
    def os_lista():
        a = request.args
        q = (a.get("q") or "").strip().lower()
        status = (a.get("status") or "").strip()
        de, ate = _data(a.get("de")), _data(a.get("ate"))
        cond, params = [], []
        if a.get("lixeira") == "1":
            cond.append("o.excluida_em IS NOT NULL")
        else:
            cond.append("o.excluida_em IS NULL")
        if status == 'abertas':
            cond.append("o.status IN ('andamento','detran','disponivel')")
        elif status:
            cond.append("o.status = %s"); params.append(status)
        if a.get("tipo_id"):
            if a.get("tipo_id") == "sem":
                cond.append("o.processo_tipo_id IS NULL")
            else:
                cond.append("o.processo_tipo_id = %s"); params.append(a.get("tipo_id"))
        if de:
            cond.append("o.data_abertura >= %s"); params.append(datetime.combine(de, datetime.min.time(), BRT))
        if ate:
            cond.append("o.data_abertura < %s")
            params.append(datetime.combine(ate + timedelta(days=1), datetime.min.time(), BRT))
        if q:
            dig = _so_dig(q)
            sub = ["lower(c.nome) LIKE %s", "lower(r.nome) LIKE %s", "replace(lower(v.placa),'-','') LIKE %s",
                   "lower(v.chassi) LIKE %s", "lower(o.protocolo) LIKE %s"]
            params += ['%' + q + '%', '%' + q + '%', '%' + q.replace('-', '') + '%',
                       '%' + q + '%', '%' + q + '%']
            if dig:
                sub += ["o.numero::text = %s", "regexp_replace(c.cpf_cnpj,'\\D','','g') LIKE %s",
                        "v.renavam LIKE %s"]
                params += [dig, '%' + dig + '%', '%' + dig + '%']
            cond.append("(" + " OR ".join(sub) + ")")
        if q:
            sub_tipo = ("EXISTS (SELECT 1 FROM processo_tipos pt WHERE pt.id = o.processo_tipo_id AND lower(pt.nome) LIKE %s)"
                        " OR EXISTS (SELECT 1 FROM os_itens i WHERE i.os_id = o.id AND lower(i.descricao) LIKE %s)")
            cond[-1] = cond[-1][:-1] + " OR " + sub_tipo + ")"
            params += ['%' + q + '%', '%' + q + '%']
        sql = ("""SELECT o.*, c.nome AS cliente_nome, c.cpf_cnpj AS cliente_doc,
                         r.nome AS responsavel_nome, v.placa, v.modelo, v.renavam,
                         (SELECT nome FROM processo_tipos pt WHERE pt.id = o.processo_tipo_id) AS processo_tipo,
                         (SELECT string_agg(i.descricao, ' + ' ORDER BY i.id) FROM os_itens i
                           WHERE i.os_id = o.id) AS servicos, """ + SQL_TOTAIS + """
                  FROM ordens_servico o
                  LEFT JOIN clientes c ON c.id = o.cliente_id
                  LEFT JOIN clientes r ON r.id = o.responsavel_id
                  LEFT JOIN veiculos v ON v.id = o.veiculo_id
                  WHERE """ + " AND ".join(cond) + " ORDER BY o.numero DESC LIMIT 300")
        with db() as cur:
            cur.execute(sql, params)
            itens = [_os_saida(r) for r in cur.fetchall()]
        if a.get("devedor") == "1":
            itens = [x for x in itens if x['devedor'] > 0.004]
        soma = {k: round(sum(x[k] for x in itens), 2) for k in ('total', 'pago', 'devedor', 'custo', 'honorario', 'lucro')}
        if not _perms()['ver_lucro']:
            for x in itens:
                _sem_lucro_os(x)
            for k in ('custo', 'lucro'):
                soma.pop(k, None)
        return jsonify({"itens": itens, "total": len(itens), "soma": soma})

    @app.route("/api/os/painel", methods=["GET"])
    @equipe
    def os_painel():
        with db() as cur:
            cur.execute("""SELECT status, COUNT(*) AS n FROM ordens_servico
                           WHERE excluida_em IS NULL GROUP BY status""")
            por_status = {r['status']: r['n'] for r in cur.fetchall()}
            cur.execute("""SELECT o.processo_tipo_id AS id, COALESCE(pt.nome, 'SEM TIPO') AS nome, COUNT(*) AS n
                           FROM ordens_servico o LEFT JOIN processo_tipos pt ON pt.id = o.processo_tipo_id
                           WHERE o.excluida_em IS NULL AND o.status IN ('andamento','detran','disponivel')
                           GROUP BY 1, 2 ORDER BY 3 DESC, 2""")
            por_tipo = [dict(r) for r in cur.fetchall()]
            pf_sql, pf_args = _pend_filtro(cur)
            cur.execute("""SELECT p.id, p.limite, p.lancado, p.descricao, p.responsavel, p.user_nome,
                                  t.nome AS tipo, o.numero, c.nome AS cliente_nome, v.placa
                           FROM os_pendencias p
                           JOIN ordens_servico o ON o.id = p.os_id AND o.excluida_em IS NULL
                           LEFT JOIN pendencia_tipos t ON t.id = p.tipo_id
                           LEFT JOIN clientes c ON c.id = o.cliente_id
                           LEFT JOIN veiculos v ON v.id = o.veiculo_id
                           WHERE NOT p.resolvida AND p.limite IS NOT NULL
                             AND p.limite <= """ + HOJE_SQL + """ + 7""" + pf_sql + """
                           ORDER BY p.limite LIMIT 100""", pf_args)
            hoje = _hoje()
            pend = []
            for r in cur.fetchall():
                x = dict(r)
                x['dias'] = (x['limite'] - hoje).days
                x['limite'] = _d(x['limite'])
                x['lancado'] = _dt(x['lancado'])
                pend.append(x)
            cur.execute("""SELECT COALESCE(SUM(t.total - t.pago),0) AS dev, COUNT(*) FILTER (WHERE t.total - t.pago > 0.004) AS n
                           FROM (SELECT o.honorario - COALESCE(o.desconto,0) +
                                   COALESCE((SELECT SUM(i.valor*i.qtd) FROM os_itens i WHERE i.os_id=o.id),0) AS total,
                                   COALESCE((SELECT SUM(r.valor) FROM os_recebimentos r WHERE r.os_id=o.id AND r.status='confirmado'),0) AS pago
                                 FROM ordens_servico o
                                 WHERE o.excluida_em IS NULL AND o.status NOT IN ('orcamento','cancelada')) t
                           WHERE t.total - t.pago > 0.004""")
            dv = cur.fetchone()
            cur.execute("""SELECT COALESCE(SUM(valor),0) AS v FROM os_recebimentos
                           WHERE status = 'confirmado' AND (quando AT TIME ZONE 'America/Sao_Paulo')::date = """ + HOJE_SQL)
            recebido_hoje = _f(cur.fetchone()['v'])
            cur.execute("SELECT COUNT(*) AS n, COALESCE(SUM(valor),0) AS v FROM os_recebimentos WHERE status = 'pendente'")
            pb = cur.fetchone()
        return jsonify({"por_status": por_status, "por_tipo": por_tipo, "pendencias": pend,
                        "devedor_total": _f(dv['dev']), "devedor_qtd": dv['n'],
                        "recebido_hoje": recebido_hoje,
                        "baixa_pendente_qtd": pb['n'], "baixa_pendente_valor": _f(pb['v'])})

    # ── ORDEM DE SERVIÇO: uma ──────────────────────────────────
    def _os_completa(cur, numero, incluir_excluida=False):
        cur.execute("""SELECT o.*, """ + SQL_TOTAIS + """ FROM ordens_servico o WHERE o.numero = %s""" +
                    ("" if incluir_excluida else " AND o.excluida_em IS NULL"), (numero,))
        r = cur.fetchone()
        if not r:
            return None
        o = _os_saida(r)
        oid = r['id']
        cur.execute("SELECT nome FROM processo_tipos WHERE id = %s", (r['processo_tipo_id'],))
        pt = cur.fetchone()
        o['processo_tipo'] = pt['nome'] if pt else None
        cur.execute("SELECT * FROM clientes WHERE id = %s", (r['cliente_id'],))
        cli = _cliente_saida(cur.fetchone())
        cur.execute("SELECT * FROM clientes WHERE id = %s", (r['responsavel_id'],))
        resp = _cliente_saida(cur.fetchone())
        cur.execute("SELECT * FROM veiculos WHERE id = %s", (r['veiculo_id'],))
        vei = _veiculo_saida(cur.fetchone())
        cur.execute("""SELECT i.*, s.centro_id FROM os_itens i LEFT JOIN servicos s ON s.id = i.servico_id
                       WHERE i.os_id = %s ORDER BY i.id""", (oid,))
        itens = []
        for x in cur.fetchall():
            x = dict(x)
            for k in ('valor', 'custo', 'qtd'):
                x[k] = _f(x[k])
            x['criado'] = _dt(x['criado'])
            itens.append(x)
        cur.execute("""SELECT r.*, f.nome AS forma, c.nome AS conta, cv.nome AS centro
                       FROM os_recebimentos r
                       LEFT JOIN formas_pgto f ON f.id = r.forma_pgto_id
                       LEFT JOIN contas c ON c.id = r.conta_id
                       LEFT JOIN centros_valor cv ON cv.id = r.centro_id
                       WHERE r.os_id = %s ORDER BY r.quando, r.id""", (oid,))
        receb = []
        for x in cur.fetchall():
            x = dict(x)
            x['valor'] = _f(x['valor'])
            x['quando'] = _dt(x['quando'])
            x['baixa_em'] = _dt(x.get('baixa_em'))
            receb.append(x)
        cur.execute("SELECT * FROM os_ocorrencias WHERE os_id = %s ORDER BY id DESC", (oid,))
        ocor = [dict(x, quando=_dt(x['quando'])) for x in cur.fetchall()]
        pf_sql, pf_args = _pend_filtro(cur)
        cur.execute("""SELECT p.*, t.nome AS tipo FROM os_pendencias p
                       LEFT JOIN pendencia_tipos t ON t.id = p.tipo_id
                       WHERE p.os_id = %s""" + pf_sql + """ ORDER BY p.resolvida, p.limite NULLS LAST, p.id""", (oid,) + pf_args)
        hoje = _hoje()
        pend = []
        for x in cur.fetchall():
            x = dict(x)
            x['dias'] = (x['limite'] - hoje).days if x['limite'] else None
            x['limite'] = _d(x['limite'])
            x['lancado'] = _dt(x['lancado'])
            x['resolvida_em'] = _dt(x['resolvida_em'])
            pend.append(x)
        cur.execute("SELECT * FROM os_documentos WHERE os_id = %s ORDER BY id", (oid,))
        docs = [dict(x, enviado=_dt(x['enviado'])) for x in cur.fetchall()]
        procs = []
        cur.execute("SELECT to_regclass('public.processos') AS t")
        if cur.fetchone()['t']:
            cur.execute("""SELECT id, tipo, fase, status, ait, prazo_final FROM processos
                           WHERE os_id = %s ORDER BY id""", (oid,))
            procs = [dict(x, prazo_final=_d(x['prazo_final'])) for x in cur.fetchall()]
        return {"os": o, "cliente": cli, "responsavel": resp, "veiculo": vei, "itens": itens,
                "recebimentos": receb, "ocorrencias": ocor, "pendencias": pend,
                "documentos": docs, "processos": procs}

    @app.route("/api/os/<int:numero>", methods=["GET"])
    @equipe
    def os_uma(numero):
        with db() as cur:
            d = _os_completa(cur, numero, incluir_excluida=True)
        if not d:
            return jsonify({"erro": "OS não encontrada"}), 404
        pm = _perms()
        if not pm['ver_lucro']:
            _sem_lucro_os(d['os'])
            for it in d['itens']:
                it.pop('custo', None)
        d['perm'] = pm
        return jsonify(d)

    @app.route("/api/os", methods=["POST"])
    @equipe
    def os_criar():
        d = request.get_json() or {}
        tipo = 'orcamento' if d.get("tipo") == 'orcamento' else 'os'
        if not d.get("cliente_id"):
            return jsonify({"erro": "Escolha o cliente (proprietário)."}), 400
        with db(commit=True) as cur:
            numero = _proximo_numero(cur)
            cur.execute("""INSERT INTO ordens_servico
                (numero, tipo, cliente_id, responsavel_id, veiculo_id, despachante, user_id, user_nome,
                 status, honorario, obs, validade, empresa_id, atendimento_id, processo_tipo_id, desconto, obs_cliente)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (numero, tipo, d.get("cliente_id"), d.get("responsavel_id") or None,
                 d.get("veiculo_id") or None, (d.get("despachante") or "").strip(),
                 str(session.get('user_id') or ''), _eu(),
                 'orcamento' if tipo == 'orcamento' else 'andamento',
                 _num(d.get("honorario")), (d.get("obs") or "").strip(),
                 _data(d.get("validade")) or (_hoje() + timedelta(days=7) if tipo == 'orcamento' else None),
                 session.get('empresa_id'), d.get("atendimento_id") or None, d.get("processo_tipo_id") or None,
                 _num(d.get("desconto")), (d.get("obs_cliente") or "").strip()))
            oid = cur.fetchone()['id']
            _ocorrencia(cur, oid, 'outras', ('Orçamento criado' if tipo == 'orcamento' else 'OS aberta') +
                        ' por ' + _eu())
            for it in (d.get("itens") or []):
                _add_item(cur, oid, it)
        return jsonify({"ok": True, "numero": numero})

    @app.route("/api/os/<int:numero>", methods=["PUT"])
    @equipe
    def os_editar(numero):
        d = request.get_json() or {}
        with db(commit=True) as cur:
            o = _os_por_numero(cur, numero)
            if not o:
                return jsonify({"erro": "OS não encontrada"}), 404
            sets, vals, mudou = [], [], []
            for k in CAMPOS_OS_EDIT:
                if k in d:
                    v = (d.get(k) or "").strip()
                    if v != (o.get(k) or ''):
                        sets.append(k + "=%s"); vals.append(v)
                        if k not in ('obs', 'obs_cliente'):
                            mudou.append(k)
            if 'processo_tipo_id' in d:
                v = d.get('processo_tipo_id') or None
                if str(v or '') != str(o.get('processo_tipo_id') or ''):
                    cur.execute("SELECT nome FROM processo_tipos WHERE id = %s", (v,))
                    pn = (cur.fetchone() or {}).get('nome', 'sem tipo')
                    sets.append("processo_tipo_id=%s"); vals.append(v); mudou.append('tipo de processo → ' + pn)
            for k in ('cliente_id', 'responsavel_id', 'veiculo_id'):
                if k in d:
                    v = d.get(k) or None
                    if str(v or '') != str(o.get(k) or ''):
                        if k == 'cliente_id' and not v:
                            return jsonify({"erro": "A OS precisa de um cliente."}), 400
                        sets.append(k + "=%s"); vals.append(v); mudou.append(k.replace('_id', ''))
            if 'desconto' in d:
                dsc = _num(d.get('desconto'))
                if dsc != (o.get('desconto') or Decimal('0')):
                    sets.append("desconto=%s"); vals.append(dsc)
                    mudou.append('desconto R$ %s → R$ %s' % (_br(o.get('desconto')), _br(dsc)))
            if 'honorario' in d:
                h = _num(d.get('honorario'))
                if h != (o.get('honorario') or Decimal('0')):
                    sets.append("honorario=%s"); vals.append(h)
                    mudou.append('honorário R$ %s → R$ %s' % (_br(o.get('honorario')), _br(h)))
            if 'valor_nf_crv' in d:
                sets.append("valor_nf_crv=%s"); vals.append(_num(d.get('valor_nf_crv'), None))
            for k in ('data_nf_crv', 'validade'):
                if k in d:
                    sets.append(k + "=%s"); vals.append(_data(d.get(k)))
            if sets:
                cur.execute("UPDATE ordens_servico SET " + ", ".join(sets) +
                            ", atualizado = NOW() WHERE id = %s", vals + [o['id']])
                if mudou:
                    _ocorrencia(cur, o['id'], 'outras', 'Cadastro alterado: ' + ', '.join(mudou))
        return jsonify({"ok": True})

    @app.route("/api/os/<int:numero>/status", methods=["POST"])
    @equipe
    def os_status(numero):
        d = request.get_json() or {}
        st = d.get("status")
        if st not in STATUS_OS or st == 'orcamento':
            return jsonify({"erro": "Status inválido"}), 400
        with db(commit=True) as cur:
            o = _os_por_numero(cur, numero)
            if not o:
                return jsonify({"erro": "OS não encontrada"}), 404
            if o['status'] == st:
                return jsonify({"ok": True})
            cur.execute("UPDATE ordens_servico SET status=%s, tipo='os', atualizado=NOW() WHERE id=%s",
                        (st, o['id']))
            tipo_oc = {'detran': 'detran', 'disponivel': 'disponivel', 'entregue': 'entregue'}.get(st, 'outras')
            desc = STATUS_OS.get(o['status'], o['status']) + ' → ' + STATUS_OS[st]
            _ocorrencia(cur, o['id'], tipo_oc, desc, (d.get("obs") or "").strip())
        return jsonify({"ok": True})

    @app.route("/api/os/<int:numero>/converter", methods=["POST"])
    @equipe
    def os_converter(numero):
        with db(commit=True) as cur:
            o = _os_por_numero(cur, numero)
            if not o:
                return jsonify({"erro": "OS não encontrada"}), 404
            if o['status'] != 'orcamento':
                return jsonify({"erro": "Esta OS não é um orçamento."}), 400
            cur.execute("""UPDATE ordens_servico SET tipo='os', status='andamento',
                           data_abertura=NOW(), atualizado=NOW() WHERE id=%s""", (o['id'],))
            _ocorrencia(cur, o['id'], 'outras', 'Orçamento aprovado — virou OS (Em andamento)')
        return jsonify({"ok": True})

    @app.route("/api/os/<int:numero>", methods=["DELETE"])
    @equipe
    def os_excluir(numero):
        if not _admin():
            return jsonify({"erro": "Só o administrador exclui OS."}), 403
        with db(commit=True) as cur:
            o = _os_por_numero(cur, numero)
            if not o:
                return jsonify({"erro": "OS não encontrada"}), 404
            cur.execute("UPDATE ordens_servico SET excluida_em=NOW(), excluida_por=%s WHERE id=%s",
                        (_eu(), o['id']))
            _ocorrencia(cur, o['id'], 'outras', 'OS enviada para a lixeira')
        return jsonify({"ok": True})

    @app.route("/api/os/<int:numero>/restaurar", methods=["POST"])
    @equipe
    def os_restaurar(numero):
        if not _admin():
            return jsonify({"erro": "Sem permissão"}), 403
        with db(commit=True) as cur:
            o = _os_por_numero(cur, numero, incluir_excluida=True)
            if not o:
                return jsonify({"erro": "OS não encontrada"}), 404
            cur.execute("UPDATE ordens_servico SET excluida_em=NULL, excluida_por='' WHERE id=%s", (o['id'],))
            _ocorrencia(cur, o['id'], 'outras', 'OS restaurada da lixeira')
        return jsonify({"ok": True})

    # ── itens ──────────────────────────────────────────────────
    def _add_item(cur, oid, it):
        sid = it.get("servico_id") or None
        if not _perms(cur)['ver_lucro'] and it.get("tipo_item") in ('taxa', 'hon'):
            # funcionário escolhe só se o item é taxa (repasse) ou honorário; o custo é calculado aqui
            it = dict(it)
            if sid:
                it.pop("custo", None)
                if it.get("tipo_item") == 'hon':
                    it["custo"] = "0"
            else:
                it["custo"] = it.get("valor") if it.get("tipo_item") == 'taxa' else "0"
        desc = (it.get("descricao") or "").strip().upper()
        valor, custo = it.get("valor"), it.get("custo")
        if sid:
            cur.execute("SELECT * FROM servicos WHERE id = %s", (sid,))
            s = cur.fetchone()
            if s:
                desc = desc or s['nome']
                if valor in (None, ''):
                    valor = s['valor_padrao']
                if custo in (None, ''):
                    custo = s['custo_padrao']
        if not desc:
            raise ValueError("Informe a descrição do item.")
        qtd = _num(it.get("qtd"), Decimal('1')) or Decimal('1')
        cur.execute("""INSERT INTO os_itens (os_id, servico_id, descricao, qtd, valor, custo, user_nome)
                       VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (oid, sid, desc, qtd, _num(valor), _num(custo), _eu()))
        iid = cur.fetchone()['id']
        if sid:  # OS ainda sem tipo de processo herda o do serviço lançado
            cur.execute("""UPDATE ordens_servico SET processo_tipo_id =
                             (SELECT processo_tipo_id FROM servicos WHERE id = %s)
                           WHERE id = %s AND processo_tipo_id IS NULL""", (sid, oid))
        return iid

    @app.route("/api/os/<int:numero>/itens", methods=["POST"])
    @equipe
    def os_item_add(numero):
        d = request.get_json() or {}
        with db(commit=True) as cur:
            o = _os_por_numero(cur, numero)
            if not o:
                return jsonify({"erro": "OS não encontrada"}), 404
            try:
                iid = _add_item(cur, o['id'], d)
            except ValueError as e:
                return jsonify({"erro": str(e)}), 400
            cur.execute("SELECT descricao, qtd, valor, custo FROM os_itens WHERE id=%s", (iid,))
            it = cur.fetchone()
            _ocorrencia(cur, o['id'], 'outras', 'Item lançado: %s — R$ %s' % (it['descricao'], _br(it['valor'] * it['qtd'])))
            pg = d.get("pago_agora") or {}
            if pg.get("conta_id"):
                if not _perms(cur)['dar_baixa']:
                    return jsonify({"erro": "Só quem dá baixa pode lançar saída do caixa."}), 403
                valor = (it['custo'] or it['valor']) * it['qtd']
                agora = _agora()
                cur.execute("""INSERT INTO lancamentos (natureza, vencimento, pago_em, descricao, favorecido, documento,
                                   valor, valor_pago, conta_id, centro_id, forma_pgto_id, os_id, obs, user_nome, empresa_id)
                               VALUES ('pagar', %s, %s, %s, %s, %s, %s, %s, %s, NULL, %s, %s, %s, %s, %s)""",
                            (agora.date(), agora, "PAGAMENTO: %s — O.S. Nº %s" % (it['descricao'], numero),
                             (pg.get("favorecido") or "").strip(), str(numero), valor, valor, pg["conta_id"],
                             pg.get("forma_id") or None, o['id'], '', _eu(), session.get('empresa_id')))
                _ocorrencia(cur, o['id'], 'outras', 'Despesa paga pelo escritório: %s — R$ %s (saiu do caixa)'
                            % (it['descricao'], _br(valor)))
            _toca(cur, o['id'])
        return jsonify({"ok": True})

    @app.route("/api/os/<int:numero>/itens/<int:iid>", methods=["PUT"])
    @equipe
    def os_item_edit(numero, iid):
        d = request.get_json() or {}
        with db(commit=True) as cur:
            o = _os_por_numero(cur, numero)
            if not o:
                return jsonify({"erro": "OS não encontrada"}), 404
            if "custo" in d and _perms(cur)['ver_lucro']:
                cur.execute("""UPDATE os_itens SET descricao=%s, qtd=%s, valor=%s, custo=%s
                               WHERE id=%s AND os_id=%s""",
                            ((d.get("descricao") or "").strip().upper(), _num(d.get("qtd"), Decimal('1')) or Decimal('1'),
                             _num(d.get("valor")), _num(d.get("custo")), iid, o['id']))
            else:  # sem ver lucro: mantém o custo; se o valor ficar menor que o custo, o custo acompanha
                v = _num(d.get("valor"))
                cur.execute("""UPDATE os_itens SET descricao=%s, qtd=%s, valor=%s, custo=LEAST(custo, %s)
                               WHERE id=%s AND os_id=%s""",
                            ((d.get("descricao") or "").strip().upper(), _num(d.get("qtd"), Decimal('1')) or Decimal('1'),
                             v, v, iid, o['id']))
            _toca(cur, o['id'])
        return jsonify({"ok": True})

    @app.route("/api/os/<int:numero>/itens/<int:iid>", methods=["DELETE"])
    @equipe
    def os_item_del(numero, iid):
        with db(commit=True) as cur:
            o = _os_por_numero(cur, numero)
            if not o:
                return jsonify({"erro": "OS não encontrada"}), 404
            cur.execute("DELETE FROM os_itens WHERE id=%s AND os_id=%s RETURNING descricao, valor",
                        (iid, o['id']))
            r = cur.fetchone()
            if r:
                _ocorrencia(cur, o['id'], 'outras', 'Item removido: %s (R$ %s)' % (r['descricao'], _br(r['valor'])))
            _toca(cur, o['id'])
        return jsonify({"ok": True})

    # ── recebimentos (gera o crédito sozinho) ─────────────────
    def _gerar_lancamento(cur, os_id, numero, quando, valor, conta_id, centro, forma_id, obs, fav, quem):
        cur.execute("""INSERT INTO lancamentos (natureza, vencimento, pago_em, descricao, favorecido,
                           documento, valor, valor_pago, conta_id, centro_id, forma_pgto_id, os_id,
                           obs, user_nome, empresa_id)
                       VALUES ('receber', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       RETURNING id""",
                    (quando.date(), quando, "PAGAMENTO DE SERVIÇO CONFORME O.S. Nº %s" % numero, fav, str(numero),
                     valor, valor, conta_id, centro, forma_id, os_id, obs, quem, session.get('empresa_id')))
        return cur.fetchone()['id']

    @app.route("/api/os/<int:numero>/recebimentos", methods=["POST"])
    @equipe
    def os_receber(numero):
        d = request.get_json() or {}
        valor = _num(d.get("valor"))
        if valor <= 0:
            return jsonify({"erro": "Informe o valor recebido."}), 400
        if not d.get("forma_pgto_id"):
            return jsonify({"erro": "Escolha a forma de pagamento."}), 400
        if not d.get("conta_id"):
            return jsonify({"erro": "Escolha a conta."}), 400
        with db(commit=True) as cur:
            r = _os_completa(cur, numero)
            if not r:
                return jsonify({"erro": "OS não encontrada"}), 404
            o = r['os']
            livre = o['devedor'] - o.get('aguardando_baixa', 0)
            if float(valor) > livre + 0.004:
                msg = "Valor maior que o saldo devedor (R$ %s)." % _br(o['devedor'])
                if o.get('aguardando_baixa'):
                    msg += " Já há R$ %s informado aguardando baixa." % _br(o['aguardando_baixa'])
                return jsonify({"erro": msg}), 400
            centro = d.get("centro_id") or None
            if not centro:  # centro = serviço principal da OS
                for it in r['itens']:
                    if it.get('centro_id'):
                        centro = it['centro_id']; break
            quando = _agora()
            if d.get("data"):
                dd = _data(d.get("data"))
                if dd and dd != quando.date():
                    quando = datetime.combine(dd, quando.timetz())
            fav = (r['responsavel'] or r['cliente'] or {}).get('nome', '')
            obs = (d.get("obs") or "").strip()
            baixa = _perms(cur)['dar_baixa']
            lid = None
            if baixa:
                lid = _gerar_lancamento(cur, o['id'], numero, quando, valor, d["conta_id"], centro,
                                        d["forma_pgto_id"], obs, fav, _eu())
            cur.execute("""INSERT INTO os_recebimentos (os_id, quando, valor, forma_pgto_id, conta_id,
                               centro_id, obs, user_nome, lancamento_id, status, baixa_por, baixa_em)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (o['id'], quando, valor, d["forma_pgto_id"], d["conta_id"], centro, obs, _eu(), lid,
                         'confirmado' if baixa else 'pendente', _eu() if baixa else '', _agora() if baixa else None))
            cur.execute("SELECT nome FROM formas_pgto WHERE id=%s", (d["forma_pgto_id"],))
            fn = (cur.fetchone() or {}).get('nome', '')
            if baixa:
                _ocorrencia(cur, o['id'], 'outras', 'Recebido R$ %s (%s) — baixa por %s' % (_br(valor), fn, _eu()))
            else:
                _ocorrencia(cur, o['id'], 'outras', 'Recebimento de R$ %s (%s) informado por %s — AGUARDANDO BAIXA'
                            % (_br(valor), fn, _eu()))
            _toca(cur, o['id'])
        return jsonify({"ok": True, "status": 'confirmado' if baixa else 'pendente'})

    @app.route("/api/os-recebimentos/pendentes", methods=["GET"])
    @equipe
    def os_receb_pendentes():
        with db() as cur:
            cur.execute("""SELECT r.*, o.numero, f.nome AS forma, c.nome AS conta, cl.nome AS cliente_nome, v.placa
                           FROM os_recebimentos r
                           JOIN ordens_servico o ON o.id = r.os_id
                           LEFT JOIN formas_pgto f ON f.id = r.forma_pgto_id
                           LEFT JOIN contas c ON c.id = r.conta_id
                           LEFT JOIN clientes cl ON cl.id = o.cliente_id
                           LEFT JOIN veiculos v ON v.id = o.veiculo_id
                           WHERE r.status = 'pendente' ORDER BY r.quando""")
            out = [dict(x, valor=_f(x['valor']), quando=_dt(x['quando']), baixa_em=_dt(x['baixa_em']))
                   for x in cur.fetchall()]
            pm = _perms(cur)
        return jsonify({"itens": out, "pode_dar_baixa": pm['dar_baixa']})

    @app.route("/api/os-recebimentos/<int:rid>/baixa", methods=["POST"])
    @equipe
    def os_receb_baixa(rid):
        d = request.get_json() or {}
        aceitar = d.get("acao") != 'recusar'
        with db(commit=True) as cur:
            if not _perms(cur)['dar_baixa']:
                return jsonify({"erro": "Só quem tem permissão dá baixa em recebimento."}), 403
            cur.execute("""SELECT r.*, o.numero, o.id AS oid FROM os_recebimentos r
                           JOIN ordens_servico o ON o.id = r.os_id WHERE r.id = %s FOR UPDATE""", (rid,))
            r = cur.fetchone()
            if not r or r['status'] != 'pendente':
                return jsonify({"erro": "Este recebimento não está aguardando baixa."}), 400
            if aceitar:
                full = _os_completa(cur, r['numero'], incluir_excluida=True)
                if float(r['valor']) > full['os']['devedor'] + 0.004:
                    return jsonify({"erro": "Valor maior que o saldo devedor atual (R$ %s)." % _br(full['os']['devedor'])}), 400
                fav = (full['responsavel'] or full['cliente'] or {}).get('nome', '')
                lid = _gerar_lancamento(cur, r['oid'], r['numero'], r['quando'], r['valor'], r['conta_id'],
                                        r['centro_id'], r['forma_pgto_id'], r['obs'], fav, r['user_nome'])
                cur.execute("""UPDATE os_recebimentos SET status='confirmado', lancamento_id=%s, baixa_por=%s,
                               baixa_em=NOW() WHERE id=%s""", (lid, _eu(), rid))
                _ocorrencia(cur, r['oid'], 'outras', 'Baixa confirmada por %s: R$ %s (informado por %s)'
                            % (_eu(), _br(r['valor']), r['user_nome']))
            else:
                motivo = (d.get("motivo") or "").strip()
                cur.execute("""UPDATE os_recebimentos SET status='recusado', baixa_por=%s, baixa_em=NOW(),
                               recusa_motivo=%s WHERE id=%s""", (_eu(), motivo, rid))
                _ocorrencia(cur, r['oid'], 'outras', 'Recebimento de R$ %s informado por %s foi RECUSADO por %s%s'
                            % (_br(r['valor']), r['user_nome'], _eu(), (' — ' + motivo) if motivo else ''))
            _toca(cur, r['oid'])
        return jsonify({"ok": True})

    @app.route("/api/os/<int:numero>/recebimentos/<int:rid>", methods=["DELETE"])
    @equipe
    def os_receb_del(numero, rid):
        with db(commit=True) as cur:
            o = _os_por_numero(cur, numero)
            if not o:
                return jsonify({"erro": "OS não encontrada"}), 404
            cur.execute("SELECT status, user_nome FROM os_recebimentos WHERE id=%s AND os_id=%s", (rid, o['id']))
            x = cur.fetchone()
            if not x:
                return jsonify({"ok": True})
            proprio_pendente = x['status'] == 'pendente' and x['user_nome'] == _eu()
            if not _admin() and not proprio_pendente:
                return jsonify({"erro": "Só o administrador exclui recebimento com baixa."}), 403
            cur.execute("DELETE FROM os_recebimentos WHERE id=%s AND os_id=%s RETURNING valor, lancamento_id",
                        (rid, o['id']))
            r = cur.fetchone()
            if r:
                if r['lancamento_id']:
                    cur.execute("DELETE FROM lancamentos WHERE id=%s", (r['lancamento_id'],))
                _ocorrencia(cur, o['id'], 'outras', 'Recebimento excluído: R$ %s' % _br(r['valor']))
            _toca(cur, o['id'])
        return jsonify({"ok": True})

    # ── permissões: quem vê lucro e quem dá baixa ─────────────
    @app.route("/api/os/minhas-permissoes", methods=["GET"])
    @equipe
    def os_minhas_perms():
        return jsonify(_perms())

    @app.route("/api/os/permissoes", methods=["GET"])
    @equipe
    def os_perms_lista():
        if not _admin():
            return jsonify({"erro": "Sem permissão"}), 403
        with db() as cur:
            cur.execute("""SELECT id, nome, login, perfil, COALESCE(ver_lucro,FALSE) AS ver_lucro,
                                  COALESCE(dar_baixa,FALSE) AS dar_baixa, COALESCE(ver_pend_todos,FALSE) AS ver_pend_todos
                           FROM usuarios WHERE ativo AND perfil IN ('admin','funcionario') ORDER BY nome""")
            return jsonify([dict(r) for r in cur.fetchall()])

    @app.route("/api/os/permissoes", methods=["PUT"])
    @equipe
    def os_perms_salvar():
        if not _admin():
            return jsonify({"erro": "Sem permissão"}), 403
        d = request.get_json() or {}
        with db(commit=True) as cur:
            cur.execute("UPDATE usuarios SET ver_lucro=%s, dar_baixa=%s, ver_pend_todos=%s WHERE id=%s",
                        (_sim(d.get("ver_lucro"), False), _sim(d.get("dar_baixa"), False),
                         _sim(d.get("ver_pend_todos"), False), str(d.get("id"))))
        return jsonify({"ok": True})

    # ── ocorrências, pendências, documentos ────────────────────
    @app.route("/api/os/<int:numero>/ocorrencias", methods=["POST"])
    @equipe
    def os_ocor_add(numero):
        d = request.get_json() or {}
        desc = (d.get("descricao") or "").strip()
        tipo = d.get("tipo") if d.get("tipo") in ('outras', 'protocolo', 'detran', 'disponivel', 'entregue') else 'outras'
        if not desc:
            return jsonify({"erro": "Descreva a ocorrência."}), 400
        with db(commit=True) as cur:
            o = _os_por_numero(cur, numero)
            if not o:
                return jsonify({"erro": "OS não encontrada"}), 404
            _ocorrencia(cur, o['id'], tipo, desc, (d.get("obs") or "").strip())
            if tipo == 'protocolo' and d.get("protocolo"):
                cur.execute("UPDATE ordens_servico SET protocolo=%s WHERE id=%s",
                            (d["protocolo"].strip(), o['id']))
            # tipos que mudam o status, igual ao F6 do BitDesp
            novo = {'detran': 'detran', 'disponivel': 'disponivel', 'entregue': 'entregue'}.get(tipo)
            if novo and o['status'] != novo:
                cur.execute("UPDATE ordens_servico SET status=%s WHERE id=%s", (novo, o['id']))
            _toca(cur, o['id'])
        return jsonify({"ok": True})

    @app.route("/api/os/<int:numero>/pendencias", methods=["POST"])
    @equipe
    def os_pend_add(numero):
        d = request.get_json() or {}
        if not (d.get("descricao") or "").strip() and not d.get("tipo_id"):
            return jsonify({"erro": "Digite o que é a pendência."}), 400
        with db(commit=True) as cur:
            o = _os_por_numero(cur, numero)
            if not o:
                return jsonify({"erro": "OS não encontrada"}), 404
            cur.execute("""INSERT INTO os_pendencias (os_id, tipo_id, limite, responsavel, descricao, user_nome, user_id)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                        (o['id'], d.get("tipo_id") or None, _data(d.get("limite")),
                         (d.get("responsavel") or _eu()).strip(), (d.get("descricao") or "").strip(), _eu(),
                         str(session.get('user_id') or '')))
            _toca(cur, o['id'])
        return jsonify({"ok": True})

    def _pend_minha(cur, pid):
        pf_sql, pf_args = _pend_filtro(cur)
        cur.execute("SELECT 1 FROM os_pendencias p WHERE p.id = %s" + pf_sql, (pid,) + pf_args)
        return bool(cur.fetchone())

    @app.route("/api/os-pendencias/<int:pid>", methods=["PUT"])
    @equipe
    def os_pend_resolver(pid):
        d = request.get_json() or {}
        resolv = _sim(d.get("resolvida"), True)
        with db(commit=True) as cur:
            if not _pend_minha(cur, pid):
                return jsonify({"erro": "Essa pendência não é sua."}), 403
            cur.execute("""UPDATE os_pendencias SET resolvida=%s,
                             resolvida_em = CASE WHEN %s THEN NOW() ELSE NULL END,
                             resolvida_por = CASE WHEN %s THEN %s ELSE '' END
                           WHERE id=%s RETURNING os_id, descricao,
                             (SELECT nome FROM pendencia_tipos t WHERE t.id = tipo_id) AS tipo""",
                        (resolv, resolv, resolv, _eu(), pid))
            r = cur.fetchone()
            if r:
                _ocorrencia(cur, r['os_id'], 'outras', ('Pendência resolvida: ' if resolv else 'Pendência reaberta: ') +
                            (r['tipo'] or r['descricao'] or ''))
                _toca(cur, r['os_id'])
        return jsonify({"ok": True})

    @app.route("/api/os-pendencias/<int:pid>", methods=["DELETE"])
    @equipe
    def os_pend_del(pid):
        with db(commit=True) as cur:
            if not _pend_minha(cur, pid):
                return jsonify({"erro": "Essa pendência não é sua."}), 403
            cur.execute("DELETE FROM os_pendencias WHERE id=%s RETURNING os_id", (pid,))
            r = cur.fetchone()
            if r:
                _toca(cur, r['os_id'])
        return jsonify({"ok": True})

    @app.route("/api/os/<int:numero>/documentos", methods=["POST"])
    @equipe
    def os_doc_add(numero):
        d = request.get_json() or {}
        url = (d.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            return jsonify({"erro": "Cole o link do documento (Google Drive, ZapSign...)."}), 400
        with db(commit=True) as cur:
            o = _os_por_numero(cur, numero)
            if not o:
                return jsonify({"erro": "OS não encontrada"}), 404
            cur.execute("INSERT INTO os_documentos (os_id, nome, url, user_nome) VALUES (%s,%s,%s,%s)",
                        (o['id'], (d.get("nome") or "Documento").strip(), url, _eu()))
            _toca(cur, o['id'])
        return jsonify({"ok": True})

    @app.route("/api/os/<int:numero>/documentos/<int:did>", methods=["DELETE"])
    @equipe
    def os_doc_del(numero, did):
        with db(commit=True) as cur:
            o = _os_por_numero(cur, numero)
            if not o:
                return jsonify({"erro": "OS não encontrada"}), 404
            cur.execute("DELETE FROM os_documentos WHERE id=%s AND os_id=%s", (did, o['id']))
        return jsonify({"ok": True})

    # ── extrato de lançamentos ─────────────────────────────────
    @app.route("/api/fin/extrato", methods=["GET"])
    @equipe
    def os_fin_extrato():
        if not _admin():
            return jsonify({"erro": "Só o administrador vê o extrato."}), 403
        a = request.args
        de = _data(a.get("de")) or _hoje().replace(day=1)
        ate = _data(a.get("ate")) or _hoje()
        cond = ["l.pago_em >= %s", "l.pago_em < %s"]
        params = [datetime.combine(de, datetime.min.time(), BRT),
                  datetime.combine(ate + timedelta(days=1), datetime.min.time(), BRT)]
        for k, col in (('conta_id', 'l.conta_id'), ('centro_id', 'l.centro_id'), ('forma_id', 'l.forma_pgto_id')):
            if a.get(k):
                cond.append(col + " = %s"); params.append(a.get(k))
        with db() as cur:
            cur.execute("""SELECT l.*, c.nome AS conta, cv.nome AS centro, f.nome AS forma, o.numero AS os_numero
                           FROM lancamentos l
                           LEFT JOIN contas c ON c.id = l.conta_id
                           LEFT JOIN centros_valor cv ON cv.id = l.centro_id
                           LEFT JOIN formas_pgto f ON f.id = l.forma_pgto_id
                           LEFT JOIN ordens_servico o ON o.id = l.os_id
                           WHERE """ + " AND ".join(cond) + " ORDER BY l.pago_em, l.id", params)
            itens = []
            cred = deb = Decimal('0')
            for r in cur.fetchall():
                x = dict(r)
                v = x['valor_pago'] or Decimal('0')
                x['credito'] = _f(v) if x['natureza'] == 'receber' else 0
                x['debito'] = _f(v) if x['natureza'] == 'pagar' else 0
                cred += v if x['natureza'] == 'receber' else 0
                deb += v if x['natureza'] == 'pagar' else 0
                x['pago_em'] = _dt(x['pago_em'])
                for k in ('valor', 'valor_pago'):
                    x[k] = _f(x[k])
                x['criado'] = _dt(x['criado'])
                x['vencimento'] = _d(x['vencimento'])
                itens.append(x)
            # resumo por centro (o "sintético" do BitDesp)
            cur.execute("""SELECT COALESCE(cv.nome,'(sem centro)') AS centro, SUM(l.valor_pago) AS total
                           FROM lancamentos l LEFT JOIN centros_valor cv ON cv.id = l.centro_id
                           WHERE l.natureza = 'receber' AND """ + " AND ".join(cond) +
                        " GROUP BY 1 ORDER BY 2 DESC", params)
            por_centro = [{"centro": r['centro'], "total": _f(r['total'])} for r in cur.fetchall()]
            cur.execute("""SELECT COALESCE(f.nome,'(sem forma)') AS forma, SUM(l.valor_pago) AS total
                           FROM lancamentos l LEFT JOIN formas_pgto f ON f.id = l.forma_pgto_id
                           WHERE l.natureza = 'receber' AND """ + " AND ".join(cond) +
                        " GROUP BY 1 ORDER BY 2 DESC", params)
            por_forma = [{"forma": r['forma'], "total": _f(r['total'])} for r in cur.fetchall()]
        return jsonify({"itens": itens, "creditos": _f(cred), "debitos": _f(deb),
                        "saldo": _f(cred - deb), "por_centro": por_centro, "por_forma": por_forma,
                        "de": de.isoformat(), "ate": ate.isoformat()})


def _sim(v, padrao=True):
    if isinstance(v, bool):
        return v
    if v is None:
        return padrao
    return str(v).lower() in ('true', '1', 'sim')

def _br(v):
    try:
        v = Decimal(str(v or 0)).quantize(Decimal('0.01'))
    except InvalidOperation:
        return str(v)
    s = "{:,.2f}".format(v)
    return s.replace(",", "X").replace(".", ",").replace("X", ".")
