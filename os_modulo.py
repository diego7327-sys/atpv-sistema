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

-- FISCAL: cada item é REPASSE (taxa/débito pago a terceiro, reembolso) ou HONORÁRIO (receita do escritório)
ALTER TABLE os_itens ADD COLUMN IF NOT EXISTS natureza  TEXT DEFAULT '';
ALTER TABLE os_itens ADD COLUMN IF NOT EXISTS categoria TEXT DEFAULT '';
ALTER TABLE os_itens ADD COLUMN IF NOT EXISTS orgao     TEXT DEFAULT '';
ALTER TABLE os_itens ADD COLUMN IF NOT EXISTS documento TEXT DEFAULT '';
ALTER TABLE servicos ADD COLUMN IF NOT EXISTS natureza  TEXT DEFAULT '';
ALTER TABLE servicos ADD COLUMN IF NOT EXISTS categoria TEXT DEFAULT '';
-- recebimento no cartão: maquininha, parcelas e NSU/autorização
ALTER TABLE os_recebimentos ADD COLUMN IF NOT EXISTS maquininha TEXT DEFAULT '';
ALTER TABLE os_recebimentos ADD COLUMN IF NOT EXISTS parcelas   INT DEFAULT 1;
ALTER TABLE os_recebimentos ADD COLUMN IF NOT EXISTS nsu        TEXT DEFAULT '';
-- arquivos (comprovantes em PDF/foto) guardados no próprio banco
CREATE TABLE IF NOT EXISTS arquivos (
    id BIGSERIAL PRIMARY KEY, nome TEXT DEFAULT '', mime TEXT DEFAULT '', tamanho INT DEFAULT 0,
    dados BYTEA, os_id BIGINT REFERENCES ordens_servico(id) ON DELETE SET NULL,
    criado TIMESTAMPTZ DEFAULT NOW(), user_nome TEXT DEFAULT '');
-- pagamento do repasse (saída do caixa com comprovante)
CREATE TABLE IF NOT EXISTS os_repasse_pagtos (
    id BIGSERIAL PRIMARY KEY,
    os_id BIGINT REFERENCES ordens_servico(id) ON DELETE CASCADE,
    item_id BIGINT REFERENCES os_itens(id) ON DELETE SET NULL,
    data DATE NOT NULL,
    conta_id BIGINT REFERENCES contas(id),
    valor NUMERIC(12,2) NOT NULL,
    orgao TEXT DEFAULT '', documento TEXT DEFAULT '',
    arquivo_id BIGINT REFERENCES arquivos(id) ON DELETE SET NULL,
    lancamento_id BIGINT REFERENCES lancamentos(id) ON DELETE SET NULL,
    obs TEXT DEFAULT '', user_nome TEXT DEFAULT '', criado TIMESTAMPTZ DEFAULT NOW());
CREATE INDEX IF NOT EXISTS os_repasse_os_idx ON os_repasse_pagtos (os_id);
-- origem do item: '' (normal) | 'acrescimo' (acréscimo do parcelamento no cartão)
ALTER TABLE os_itens ADD COLUMN IF NOT EXISTS origem TEXT DEFAULT '';
-- honorário zero só com motivo
ALTER TABLE ordens_servico ADD COLUMN IF NOT EXISTS hon_zero_motivo TEXT DEFAULT '';
-- parcelamento de débitos no cartão (um por OS)
CREATE TABLE IF NOT EXISTS os_parcelamentos (
    id BIGSERIAL PRIMARY KEY,
    os_id BIGINT UNIQUE REFERENCES ordens_servico(id) ON DELETE CASCADE,
    data DATE, valor_cartao NUMERIC(12,2) DEFAULT 0,
    maquininha TEXT DEFAULT '', parcelas INT DEFAULT 1, nsu TEXT DEFAULT '',
    forma_pgto_id BIGINT REFERENCES formas_pgto(id), conta_id BIGINT REFERENCES contas(id),
    retorno_tipo TEXT DEFAULT '', retorno_valor NUMERIC(12,2) DEFAULT 0,
    custo_maquininha NUMERIC(12,2) DEFAULT 0, hon_no_cartao BOOLEAN DEFAULT TRUE,
    recebimento_id BIGINT REFERENCES os_recebimentos(id) ON DELETE SET NULL,
    user_nome TEXT DEFAULT '', criado TIMESTAMPTZ DEFAULT NOW(), atualizado TIMESTAMPTZ DEFAULT NOW());
-- nota fiscal de serviço (NFS-e) do honorário: pendente | emitida | dispensada
ALTER TABLE ordens_servico ADD COLUMN IF NOT EXISTS nf_status TEXT DEFAULT 'pendente';
ALTER TABLE ordens_servico ADD COLUMN IF NOT EXISTS nf_numero TEXT DEFAULT '';
ALTER TABLE ordens_servico ADD COLUMN IF NOT EXISTS nf_data DATE;
ALTER TABLE ordens_servico ADD COLUMN IF NOT EXISTS nf_valor NUMERIC(12,2);
ALTER TABLE ordens_servico ADD COLUMN IF NOT EXISTS nf_obs TEXT DEFAULT '';
-- data em que a OS foi entregue/concluída (competência do honorário quando não há nota)
ALTER TABLE ordens_servico ADD COLUMN IF NOT EXISTS concluida_em TIMESTAMPTZ;
CREATE OR REPLACE FUNCTION os_marca_conclusao() RETURNS trigger AS $$
BEGIN
  IF NEW.status IN ('entregue','concluida') THEN
    IF NEW.concluida_em IS NULL THEN NEW.concluida_em := NOW(); END IF;
  ELSE
    NEW.concluida_em := NULL;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS os_conclusao_trg ON ordens_servico;
CREATE TRIGGER os_conclusao_trg BEFORE INSERT OR UPDATE OF status ON ordens_servico
  FOR EACH ROW EXECUTE FUNCTION os_marca_conclusao();
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
                  "empresa_endereco": "Av. Brasil, 464, Sala 01 - Centro - CEP 75020-000", "empresa_cidade": "Anápolis-GO",
                  "empresa_email": "diego7327@hotmail.com"}

# Fiscal: categorias de repasse, maquininhas e tipo da forma de pagamento
CATEGORIAS_REPASSE = [("taxa_detran", "TAXA DETRAN"), ("ipva", "IPVA"), ("licenciamento", "LICENCIAMENTO"),
                      ("multa", "MULTA"), ("vistoria", "VISTORIA"), ("placa", "PLACA"), ("outros", "OUTROS")]
CAT_REPASSE = dict(CATEGORIAS_REPASSE)
MAQUININHAS = ["STONE", "SICREDI", "LISTO"]
# conta onde cai cada maquininha (busca pelo nome da conta)
MAQ_CONTA = {"STONE": "STONE", "SICREDI": "SICRED", "LISTO": "BRADESCO"}
REGIMES = {"competencia": "Competência — honorário entra na data da nota (ou da conclusão da OS)",
           "caixa": "Caixa — honorário entra na data em que o cliente pagou"}
TIPO_PARCELAMENTO = "PAGAMENTO/PARCELAMENTO DE DÉBITOS"
TIPO_AVULSO = "ATENDIMENTO AVULSO"
MOTIVOS_HON_ZERO = ["CORTESIA", "RETORNO (SERVIÇO REFEITO)", "CLIENTE PARCEIRO", "ERRO DO ESCRITÓRIO", "OUTRO"]
NF_CRITERIOS = {"conservador": "Conservador — honorário + tudo cobrado no cartão acima dos débitos",
                "retorno": "Só retorno — honorário + retorno da maquininha"}
NF_STATUS = {"pendente": "PENDENTE", "emitida": "EMITIDA", "dispensada": "DISPENSADA"}
AVULSO_SERVICOS = ["CONSULTA", "AGENDAMENTO", "CONSULTA DE DÉBITOS", "IMPRESSÃO DE DOCUMENTO", "SERVIÇO DESPACHANTE"]
ARQ_MIMES = ("application/pdf", "image/jpeg", "image/png", "image/webp")
ARQ_MAX = 6 * 1024 * 1024

def _cat_palpite(desc):
    """Categoria do repasse pelo nome do item (o usuário pode trocar)."""
    d = (desc or '').upper()
    for chave, cat in (("IPVA", "ipva"), ("LICENC", "licenciamento"), ("MULTA", "multa"), ("INFRA", "multa"),
                       ("VISTORIA", "vistoria"), ("PLACA", "placa"), ("LACRE", "placa")):
        if chave in d:
            return cat
    for chave in ("TAXA", "DETRAN", "TRANSFER", "CRV", "CRLV", "DUA", "2ª VIA", "2 VIA", "ATPV", "CATEGORIA", "ALTERA"):
        if chave in d:
            return "taxa_detran"
    return "outros"

class _Rollback(Exception):
    """Erro de validação no meio de uma gravação: desfaz tudo e devolve a mensagem."""

def xlsx_contador(r, m, ini, fim):
    """Planilha do contador (bytes .xlsx) a partir do relatório já calculado."""
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    rs = r['resumo']
    NAVY, FUNDO = "1F3864", "F3F5F9"
    hfont, hfill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor=NAVY)
    borda = Border(bottom=Side(style="thin", color="D0D5DD"))
    moeda = '#,##0.00;[Red]-#,##0.00'
    wb = Workbook()
    ws = wb.active; ws.title = "Resumo"
    mes_txt = "%s/%s" % (m[5:], m[:4])
    ws["A1"] = "CAETANO DESPACHANTE LTDA — CNPJ 08.965.960/0001-06"; ws["A1"].font = Font(bold=True, size=13, color=NAVY)
    ws["A2"] = "Relatório mensal para o contador — %s (%s a %s)" % (mes_txt, ini.strftime('%d/%m/%Y'), fim.strftime('%d/%m/%Y'))
    ws["A2"].font = Font(italic=True, color="555555")
    ws["A3"] = "Honorários pelo regime de " + ("CAIXA (data do recebimento)" if rs.get('regime') == 'caixa' else "COMPETÊNCIA (data da NFS-e ou da conclusão da OS)")
    ws["A3"].font = Font(bold=True, color="B08A4E")
    linhas = [("RECEITA DO ESCRITÓRIO — " + ("OS com recebimento no mês" if rs.get('regime') == 'caixa' else "OS com nota ou concluídas no mês"), None, True),
              ("Quantidade de OS", rs['os_qtd'], False), ("Total cobrado dos clientes", rs['os_total'], False),
              ("(−) Repasses / taxas e débitos de terceiros", rs['repasses_os'], False),
              ("(=) Honorários (receita)", rs['honorarios'], False),
              ("   dos quais: acréscimos de parcelamento no cartão", rs['acrescimos'], False),
              ("Retorno das maquininhas (parcelamentos)", rs['retornos'], False),
              ("Custo das maquininhas (parcelamentos)", rs['custo_maquininha'], False),
              ("Valor sugerido para notas fiscais", rs['nota_sugerida'], False),
              ("", None, False),
              ("NOTAS FISCAIS (NFS-e)", None, True),
              ("NFS-e emitidas no mês — quantidade", rs['nfs_emitidas_qtd'], False),
              ("NFS-e emitidas no mês — valor", rs['nfs_emitidas_valor'], False),
              ("OS com honorário sem nota — quantidade", rs['sem_nota_qtd'], False),
              ("OS com honorário sem nota — valor", rs['sem_nota_valor'], False),
              ("OS com honorário zero", rs['hon_zero_qtd'], False),
              ("", None, False),
              ("CONFERÊNCIA DIMP (cartão por maquininha)", None, True)]
    dm = r.get('dimp') or {"maquininhas": [], "total": {}}
    for g in dm['maquininhas'] + ([dm['total']] if dm.get('total') else []):
        linhas.append(("   %s — bruto no cartão" % g['maquininha'], g['bruto'], False))
        linhas.append(("      repasse documentado (DUA/comprovante)", g['repasse_doc'], False))
        linhas.append(("      receita com NFS-e", g['receita_nota'], False))
        linhas.append(("      SEM EXPLICAÇÃO", g['sem_explicacao'], False))
    linhas += [("", None, False),
              ("RECEBIDO NO MÊS (por data do recebimento)", None, True)]
    linhas += [("   " + k, v, False) for k, v in rs['recebido_por_forma'].items()]
    linhas += [("Total recebido (confirmado)", rs['recebido'], False),
               ("Informado e aguardando baixa", rs['aguardando_baixa'], False), ("", None, False),
               ("REPASSES PAGOS NO MÊS (DUA/guias)", None, True)]
    linhas += [("   " + k, v, False) for k, v in rs['repasses_por_categoria'].items()]
    linhas += [("Total de repasses pagos", rs['repasses_pagos'], False),
               ("Pagamentos sem comprovante anexado", rs['repasses_sem_comprovante'], False)]
    qtds = ("Quantidade de OS", "NFS-e emitidas no mês — quantidade", "OS com honorário sem nota — quantidade",
            "OS com honorário zero", "Pagamentos sem comprovante anexado")
    lin = 4
    for rot, v, tit in linhas:
        ws.cell(lin, 1, rot)
        if tit:
            for col in (1, 2):
                ws.cell(lin, col).fill = hfill; ws.cell(lin, col).font = hfont
        elif v is not None:
            c = ws.cell(lin, 2, v)
            if rot.strip() == "SEM EXPLICAÇÃO" and (v or 0) > 0.004:
                ws.cell(lin, 1).font = Font(bold=True, color="C00000"); c.font = Font(bold=True, color="C00000")
            c.number_format = '0' if rot in qtds else moeda
            if rot.startswith("(=)") or rot.startswith("Total"):
                ws.cell(lin, 1).font = Font(bold=True); c.font = Font(bold=True)
        lin += 1
    ws.column_dimensions['A'].width = 58; ws.column_dimensions['B'].width = 18
    
    def aba(nome, cols, dados):
        w = wb.create_sheet(nome)
        for j, (tit, _k, _w, _f2) in enumerate(cols, 1):
            c = w.cell(1, j, tit); c.font = hfont; c.fill = hfill; c.alignment = Alignment(vertical="center", wrap_text=True)
            w.column_dimensions[get_column_letter(j)].width = _w
        for i, x in enumerate(dados, 2):
            for j, (_t, k, _w, fmt) in enumerate(cols, 1):
                v = x.get(k)
                if isinstance(v, bool):
                    v = "SIM" if v else "NÃO"
                if k in ('data', 'nf_data', 'conclusao', 'data_base') and v:
                    v = datetime.strptime(v[:10], "%Y-%m-%d").date()
                c = w.cell(i, j, v)
                if fmt == 'm': c.number_format = moeda
                elif fmt == 'd': c.number_format = 'DD/MM/YYYY'
                c.border = borda
                if i % 2 == 1: c.fill = PatternFill("solid", fgColor=FUNDO)
        if dados and any(f2 == 'm' for *_x, f2 in cols):
            t = len(dados) + 2
            w.cell(t, 1, "TOTAL").font = Font(bold=True)
            for j, (_t, k, _w, fmt) in enumerate(cols, 1):
                if fmt == 'm':
                    c = w.cell(t, j, "=SUM(%s2:%s%d)" % (get_column_letter(j), get_column_letter(j), t - 1))
                    c.number_format = moeda; c.font = Font(bold=True)
        w.freeze_panes = "A2"
        if dados:
            w.auto_filter.ref = "A1:%s%d" % (get_column_letter(len(cols)), len(dados) + 1)
    aba("OS do mês", [("OS", "os", 8, ''), ("Abertura", "data", 11, 'd'), ("Conclusão", "conclusao", 11, 'd'), ("Data base", "data_base", 11, 'd'), ("Cliente", "cliente", 30, ''), ("CPF/CNPJ", "cpf_cnpj", 17, ''),
                      ("Placa", "placa", 9, ''), ("Tipo", "tipo", 24, ''), ("Situação", "status", 14, ''),
                      ("Total", "total", 12, 'm'), ("Repasse", "repasse", 12, 'm'), ("Honorário (receita)", "receita", 13, 'm'),
                      ("Acréscimo parc.", "acrescimo", 12, 'm'), ("Retorno maq.", "retorno", 11, 'm'),
                      ("Nota sugerida", "nota_sugerida", 12, 'm'), ("NFS-e", "nf_status", 11, ''), ("Nº NFS-e", "nf_numero", 10, ''),
                      ("Valor NFS-e", "nf_valor", 12, 'm'), ("Recebido no mês", "recebido_mes", 12, 'm'), ("Recebido (total)", "recebido", 12, 'm'), ("Em aberto", "devedor", 12, 'm'),
                      ("Motivo hon. zero", "hon_zero_motivo", 22, '')], r['os'])
    aba("Conferência DIMP", [("Maquininha", "maquininha", 16, ''), ("Pagamentos", "qtd", 11, ''), ("Bruto no cartão", "bruto", 15, 'm'),
                             ("Repasse documentado", "repasse_doc", 17, 'm'), ("Receita com NFS-e", "receita_nota", 16, 'm'),
                             ("Sem explicação", "sem_explicacao", 15, 'm')], dm['maquininhas'])
    wd = wb["Conferência DIMP"]
    for row in wd.iter_rows(min_row=2, min_col=6, max_col=6):
        for c in row:
            if isinstance(c.value, (int, float)) and c.value > 0.004 or (isinstance(c.value, str) and c.value.startswith('=')):
                c.font = Font(bold=True, color="C00000")
    if dm.get('os'):
        base = wd.max_row + 3
        wd.cell(base - 1, 1, "OS com valor no cartão sem explicação").font = Font(bold=True, color=NAVY)
        for j, t in enumerate(("OS", "Cliente", "Maquininha", "Cartão", "Repasse doc.", "Com nota", "Sem explicação", "Motivo"), 1):
            c = wd.cell(base, j, t); c.font = hfont; c.fill = hfill
        for i2, e in enumerate(dm['os'], base + 1):
            for j, k in enumerate(("os", "cliente", "maquininha", "cartao", "repasse_doc", "receita_nota", "sem_explicacao", "motivo"), 1):
                c = wd.cell(i2, j, e[k])
                if k in ("cartao", "repasse_doc", "receita_nota", "sem_explicacao"): c.number_format = moeda
                if k == "sem_explicacao": c.font = Font(bold=True, color="C00000")
        wd.column_dimensions['H'].width = 46
    aba("Recebimentos", [("Data", "data", 11, 'd'), ("OS", "os", 8, ''), ("Cliente", "cliente", 30, ''), ("Forma", "forma", 14, ''),
                         ("Grupo", "grupo", 26, ''), ("Maquininha", "maquininha", 11, ''), ("Parcelas", "parcelas", 8, ''),
                         ("NSU", "nsu", 12, ''), ("Conta", "conta", 12, ''), ("Valor", "valor", 12, 'm'),
                         ("Situação", "situacao", 17, '')], r['recebimentos'])
    aba("Repasses pagos", [("Data", "data", 11, 'd'), ("OS", "os", 8, ''), ("Cliente", "cliente", 28, ''), ("Item", "item", 28, ''),
                           ("Categoria", "categoria", 14, ''), ("Órgão", "orgao", 14, ''), ("DUA/Guia", "documento", 16, ''),
                           ("Conta de saída", "conta", 13, ''), ("Valor", "valor", 12, 'm'), ("Comprovante", "comprovante", 12, '')], r['repasses'])
    aba("NFS-e emitidas", [("Data", "data", 11, 'd'), ("OS", "os", 8, ''), ("Cliente", "cliente", 32, ''),
                           ("Nº NFS-e", "nf_numero", 12, ''), ("Valor", "valor", 12, 'm')], r['notas'])
    aba("Sem nota", [("OS", "os", 8, ''), ("Data", "data", 11, 'd'), ("Cliente", "cliente", 32, ''), ("CPF/CNPJ", "cpf_cnpj", 17, ''),
                     ("Honorário", "receita", 12, 'm'), ("Nota sugerida", "nota_sugerida", 13, 'm'), ("Recebido", "recebido", 12, 'm')], r['sem_nota'])
    aba("Honorário zero", [("OS", "os", 8, ''), ("Data", "data", 11, 'd'), ("Cliente", "cliente", 32, ''), ("Tipo", "tipo", 24, ''),
                           ("Total", "total", 12, 'm'), ("Motivo", "hon_zero_motivo", 26, '')], r['hon_zero'])
    bio = BytesIO(); wb.save(bio)
    return bio.getvalue()

def _forma_tipo(nome):
    n = (nome or '').upper()
    if 'PIX' in n: return 'pix'
    if 'DINHEIRO' in n or 'ESPÉCIE' in n or 'ESPECIE' in n: return 'dinheiro'
    if 'DÉBITO' in n or 'DEBITO' in n: return 'debito'
    if 'CRÉDITO' in n or 'CREDITO' in n or 'PARCEL' in n or 'CARTÃO' in n or 'CARTAO' in n: return 'credito'
    return 'outro'

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

def _brl(v):
    return ("%.2f" % _f(v)).replace('.', ',')

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
            cur.execute("SELECT 1 FROM migracoes WHERE nome = 'os_fiscal_v1'")
            if not cur.fetchone():
                # itens antigos: com custo = repasse; sem custo = honorário
                cur.execute("SELECT id, descricao, custo FROM os_itens WHERE COALESCE(natureza,'') = ''")
                for r in cur.fetchall():
                    nat = 'repasse' if (r['custo'] or 0) > 0 else 'honorario'
                    cur.execute("UPDATE os_itens SET natureza=%s, categoria=%s WHERE id=%s",
                                (nat, _cat_palpite(r['descricao']) if nat == 'repasse' else '', r['id']))
                cur.execute("SELECT id, nome, custo_padrao FROM servicos WHERE COALESCE(natureza,'') = ''")
                for r in cur.fetchall():
                    nat = 'repasse' if (r['custo_padrao'] or 0) > 0 else 'honorario'
                    cur.execute("UPDATE servicos SET natureza=%s, categoria=%s WHERE id=%s",
                                (nat, _cat_palpite(r['nome']) if nat == 'repasse' else '', r['id']))
                # formas: cartão de crédito (o antigo "PARCELADO")
                cur.execute("SELECT id, nome FROM formas_pgto")
                fs = cur.fetchall()
                if not any(_forma_tipo(f['nome']) == 'credito' and 'CR' in f['nome'].upper() for f in fs):
                    par = [f for f in fs if f['nome'].upper() == 'PARCELADO']
                    if par:
                        cur.execute("UPDATE formas_pgto SET nome='CRÉDITO' WHERE id=%s", (par[0]['id'],))
                    else:
                        cur.execute("INSERT INTO formas_pgto (nome) VALUES ('CRÉDITO')")
                for nome in ("PIX", "DINHEIRO", "DÉBITO"):
                    if not any(_forma_tipo(f['nome']) == _forma_tipo(nome) for f in fs):
                        cur.execute("INSERT INTO formas_pgto (nome) VALUES (%s)", (nome,))
                # contas onde o dinheiro cai / de onde sai: Sicredi, Caixa, Stone
                cur.execute("SELECT nome FROM contas")
                cs = [c['nome'].upper() for c in cur.fetchall()]
                for chave, nome in (("SICRED", "SICREDI"), ("CAIXA", "CAIXA"), ("STONE", "STONE")):
                    if not any(chave in c for c in cs):
                        cur.execute("INSERT INTO contas (nome) VALUES (%s)", (nome,))
                cur.execute("INSERT INTO migracoes (nome) VALUES ('os_fiscal_v1')")
            cur.execute("SELECT 1 FROM migracoes WHERE nome = 'os_fiscal_v2'")
            if not cur.fetchone():
                for n in (TIPO_PARCELAMENTO, TIPO_AVULSO):
                    cur.execute("SELECT 1 FROM processo_tipos WHERE upper(nome) = upper(%s)", (n,))
                    if not cur.fetchone():
                        cur.execute("INSERT INTO processo_tipos (nome) VALUES (%s)", (n,))
                cur.execute("INSERT INTO migracoes (nome) VALUES ('os_fiscal_v2')")
            cur.execute("SELECT 1 FROM migracoes WHERE nome = 'os_fiscal_v3'")
            if not cur.fetchone():
                # OS já entregues/concluídas: data da conclusão pela ocorrência (ou última atualização)
                cur.execute("""UPDATE ordens_servico o SET concluida_em = COALESCE(
                                 (SELECT MAX(x.quando) FROM os_ocorrencias x WHERE x.os_id = o.id
                                   AND (x.tipo = 'entregue' OR x.descricao ILIKE '%%conclu%%')), o.atualizado, o.data_abertura)
                               WHERE o.status IN ('entregue','concluida') AND o.concluida_em IS NULL""", ())
                cur.execute("SELECT nome FROM contas")
                if not any('BRADESCO' in (c['nome'] or '').upper() for c in cur.fetchall()):
                    cur.execute("INSERT INTO contas (nome) VALUES ('BRADESCO')")
                cur.execute("INSERT INTO migracoes (nome) VALUES ('os_fiscal_v3')")
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

    CAMPOS_LUCRO = ('custo', 'lucro', 'lucro_terceiros', 'taxas', 'honorarios', 'repasse_total', 'repasse_pago',
                    'repasse_a_pagar', 'receita', 'nota_valor')

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
        COALESCE((SELECT SUM(i.custo*i.qtd) FROM os_itens i WHERE i.os_id = o.id AND i.natureza = 'repasse'),0) AS repasse_total,
        COALESCE((SELECT SUM(p.valor) FROM os_repasse_pagtos p WHERE p.os_id = o.id),0) AS repasse_pago,
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
        rep_total = _f(d.pop('repasse_total', 0))
        rep_pago = _f(d.pop('repasse_pago', 0))
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
            # fiscal: repasse = reembolso de taxas/débitos; receita = total − repasse (honorário + diferença cobrada − desconto)
            'repasse_total': round(rep_total, 2), 'repasse_pago': round(rep_pago, 2),
            'repasse_a_pagar': round(max(rep_total - rep_pago, 0), 2),
            'receita': round(total - rep_total, 2),
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
        nat = _natureza(d) or ('repasse' if _num(d.get("custo_padrao")) > 0 else 'honorario')
        cat = (d.get("categoria") or "").lower() if nat == 'repasse' else ''
        if nat == 'repasse' and cat not in CAT_REPASSE:
            cat = _cat_palpite(nome)
        custo = _num(d.get("custo_padrao")) if nat == 'repasse' else Decimal('0')
        vals = (nome, _num(d.get("valor_padrao")), custo,
                d.get("centro_id") or None, _sim(d.get("ativo"), True), d.get("processo_tipo_id") or None, nat, cat)
        with db(commit=True) as cur:
            if d.get("id"):
                cur.execute("""UPDATE servicos SET nome=%s, valor_padrao=%s, custo_padrao=%s,
                               centro_id=%s, ativo=%s, processo_tipo_id=%s, natureza=%s, categoria=%s WHERE id=%s""", vals + (d["id"],))
            else:
                cur.execute("""INSERT INTO servicos (nome, valor_padrao, custo_padrao, centro_id, ativo, processo_tipo_id,
                                                     natureza, categoria)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", vals)
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
            out['categorias_repasse'] = [{"id": k, "nome": v} for k, v in CATEGORIAS_REPASSE]
            out['nf_criterio'] = _nf_criterio(cur)
            out['nf_criterios'] = [{"id": k, "nome": v} for k, v in NF_CRITERIOS.items()]
            out['regime'] = _regime(cur)
            out['regimes'] = [{"id": k, "nome": v} for k, v in REGIMES.items()]
            out['maq_conta'] = MAQ_CONTA
            out['motivos_hon_zero'] = MOTIVOS_HON_ZERO
            out['avulso_servicos'] = AVULSO_SERVICOS
            out['maquininhas'] = MAQUININHAS
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
            if "nf_criterio" in d:
                v = d.get("nf_criterio") if d.get("nf_criterio") in NF_CRITERIOS else "conservador"
                cur.execute("""INSERT INTO config (chave, valor) VALUES ('nf_criterio', %s)
                               ON CONFLICT (chave) DO UPDATE SET valor = EXCLUDED.valor, atualizado = NOW()""", (v,))
            if "regime" in d:
                v = d.get("regime") if d.get("regime") in REGIMES else "competencia"
                cur.execute("""INSERT INTO config (chave, valor) VALUES ('regime_honorarios', %s)
                               ON CONFLICT (chave) DO UPDATE SET valor = EXCLUDED.valor, atualizado = NOW()""", (v,))
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
        cur.execute("""SELECT p.*, c.nome AS conta, a.nome AS arquivo_nome, i.descricao AS item_desc
                       FROM os_repasse_pagtos p
                       LEFT JOIN contas c ON c.id = p.conta_id
                       LEFT JOIN arquivos a ON a.id = p.arquivo_id
                       LEFT JOIN os_itens i ON i.id = p.item_id
                       WHERE p.os_id = %s ORDER BY p.data, p.id""", (oid,))
        reps = []
        pago_item = {}
        for x in cur.fetchall():
            x = dict(x)
            x['valor'] = _f(x['valor']); x['data'] = _d(x['data']); x['criado'] = _dt(x['criado'])
            if x['item_id']:
                pago_item[x['item_id']] = pago_item.get(x['item_id'], 0) + x['valor']
            reps.append(x)
        for it in itens:
            if it.get('natureza') == 'repasse':
                it['repasse_pago'] = round(pago_item.get(it['id'], 0), 2)
                it['repasse_quitado'] = it['repasse_pago'] + 0.004 >= it['custo'] * it['qtd']
        cur.execute("SELECT * FROM os_parcelamentos WHERE os_id = %s", (oid,))
        pr = cur.fetchone()
        parc = None
        if pr:
            parc = dict(pr)
            for k in ('valor_cartao', 'retorno_valor', 'custo_maquininha'):
                parc[k] = _f(parc[k])
            parc['data'] = _d(parc['data']); parc['criado'] = _dt(parc['criado']); parc['atualizado'] = _dt(parc['atualizado'])
            parc['calc'] = _parc_calc(cur, oid, pr)
        # valor da nota fiscal do honorário: receita; no parcelamento segue o critério das Configurações
        o['nota_valor'] = parc['calc']['nota'] if parc else o['receita']
        o['nf_data'] = _d(r.get('nf_data')); o['nf_valor'] = _f(r['nf_valor']) if r.get('nf_valor') is not None else None
        o['nf_status'] = o.get('nf_status') or 'pendente'
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
                "recebimentos": receb, "ocorrencias": ocor, "pendencias": pend, "repasses": reps, "parcelamento": parc,
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
                if not pm['dar_baixa']:
                    it.pop('repasse_pago', None)
            if not pm['dar_baixa']:
                d['repasses'] = []
            if d.get('parcelamento'):   # retorno, custo da maquininha e nota: só quem vê lucro
                pc = d['parcelamento']
                for k in ('retorno_tipo', 'retorno_valor', 'custo_maquininha'):
                    pc.pop(k, None)
                pc['calc'] = {k: pc['calc'][k] for k in ('debitos', 'acrescimo', 'valor_cartao')}
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
            erro = _hon_zero_checa(cur, o, st, d.get("hon_zero_motivo"))
            if erro:
                return jsonify(erro), 400
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

    # ── honorário zero: só finaliza com motivo ────────────────
    def _receita_os(cur, numero):
        r = _os_completa(cur, numero, incluir_excluida=True)
        return r['os']['receita'] if r else 0

    def _hon_zero_checa(cur, o, novo_status, motivo):
        """Ao finalizar (entregue/concluída) OS com honorário R$ 0,00, exige um motivo. Devolve dict de erro ou None."""
        if novo_status not in ('entregue', 'concluida'):
            return None
        if _receita_os(cur, o['numero']) > 0.004 or (o.get('hon_zero_motivo') or '').strip():
            return None
        cur.execute("SELECT retorno_valor FROM os_parcelamentos WHERE os_id=%s", (o['id'],))
        pr = cur.fetchone()
        if pr and (pr['retorno_valor'] or 0) > 0:     # parcelamento: o ganho é o retorno da maquininha
            return None
        motivo = (motivo or '').strip().upper()
        base = motivo.split(':')[0].strip()
        if not motivo or base not in MOTIVOS_HON_ZERO or (base == 'OUTRO' and len(motivo) < 8):
            return {"erro": "Esta OS está com honorário R$ 0,00. Para finalizar, escolha o motivo.",
                    "codigo": "honorario_zero", "motivos": MOTIVOS_HON_ZERO}
        cur.execute("UPDATE ordens_servico SET hon_zero_motivo=%s WHERE id=%s", (motivo, o['id']))
        _ocorrencia(cur, o['id'], 'outras', 'Finalizada com honorário R$ 0,00 — motivo: %s' % motivo)
        return None

    # ── parcelamento de débitos no cartão ─────────────────────
    def _regime(cur):
        cur.execute("SELECT valor FROM config WHERE chave = 'regime_honorarios'")
        r = cur.fetchone()
        return r['valor'] if r and r['valor'] in REGIMES else 'competencia'

    def _nf_criterio(cur):
        cur.execute("SELECT valor FROM config WHERE chave = 'nf_criterio'")
        r = cur.fetchone()
        return r['valor'] if r and r['valor'] in NF_CRITERIOS else 'conservador'

    def _parc_calc(cur, oid, p, hon_no_cartao=None, honorario=None):
        """Débitos (repasse), honorário, acréscimo do parcelamento e valor da nota pelos dois critérios."""
        cur.execute("""SELECT
              COALESCE(SUM(CASE WHEN natureza = 'repasse' THEN custo*qtd END),0) AS debitos,
              COALESCE(SUM(CASE WHEN origem <> 'acrescimo' THEN valor*qtd END),0) AS itens_sem_acr
            FROM os_itens WHERE os_id = %s""", (oid,))
        x = cur.fetchone()
        cur.execute("SELECT honorario, desconto FROM ordens_servico WHERE id=%s", (oid,))
        o = cur.fetchone()
        debitos = x['debitos']
        hon_os = o['honorario'] or 0 if honorario is None else honorario
        hon = (x['itens_sem_acr'] + hon_os - (o['desconto'] or 0)) - debitos
        no_cartao = p['hon_no_cartao'] if hon_no_cartao is None else hon_no_cartao
        cartao = _num(p['valor_cartao']) if p else Decimal('0')
        acr = max(Decimal('0'), cartao - debitos - (hon if no_cartao else 0))
        ret = _num(p.get('retorno_valor')) if p else Decimal('0')
        crit = _nf_criterio(cur)
        nc, nr = hon + acr, hon + ret
        return {"debitos": _f(debitos), "honorario": _f(hon), "acrescimo": _f(acr), "valor_cartao": _f(cartao),
                "nota_conservador": _f(nc), "nota_retorno": _f(nr), "criterio": crit,
                "nota": _f(nr if crit == 'retorno' else nc)}

    @app.route("/api/os/<int:numero>/parcelamento", methods=["POST"])
    @equipe
    def os_parcelamento(numero):
        d = request.get_json() or {}
        with db(commit=True) as cur:
            o = _os_por_numero(cur, numero)
            if not o:
                return jsonify({"erro": "OS não encontrada"}), 404
            vl = _perms(cur)['ver_lucro']
            sim = _sim(d.get("simular"), False)
            cartao = _num(d.get("valor_cartao"))
            if cartao <= 0 and not sim:
                return jsonify({"erro": "Informe o valor total passado no cartão."}), 400
            maq = (d.get("maquininha") or "").strip().upper()
            if maq not in MAQUININHAS and not sim:
                return jsonify({"erro": "Escolha a maquininha (Stone, Sicredi ou Listo)."}), 400
            try:
                parc = int(d.get("parcelas") or 1)
            except (TypeError, ValueError):
                parc = 1
            if not 1 <= parc <= 24:
                return jsonify({"erro": "Parcelas: de 1 a 24."}), 400
            cur.execute("SELECT COUNT(*) AS n FROM os_itens WHERE os_id=%s AND natureza='repasse'", (o['id'],))
            if not cur.fetchone()['n'] and not sim:
                return jsonify({"erro": "Lance primeiro os débitos pagos (IPVA, licenciamento, multas...)."}), 400
            cur.execute("SELECT * FROM os_parcelamentos WHERE os_id=%s", (o['id'],))
            atual = cur.fetchone()
            cur.execute("SELECT id, nome FROM formas_pgto WHERE ativo ORDER BY id")
            fcred = [f['id'] for f in cur.fetchall() if _forma_tipo(f['nome']) == 'credito']
            forma = d.get("forma_pgto_id") or (fcred[0] if fcred else None)
            conta = d.get("conta_id")
            if not conta:
                cur.execute("SELECT id FROM contas WHERE ativo AND upper(nome) LIKE %s ORDER BY id LIMIT 1",
                            ('%' + MAQ_CONTA.get(maq, 'SICRED') + '%',))
                c_ = cur.fetchone()
                conta = c_['id'] if c_ else None
            if not conta and not sim:
                return jsonify({"erro": "Escolha a conta onde cai o cartão."}), 400
            p = {"data": _data(d.get("data")) or _hoje(), "valor_cartao": cartao, "maquininha": maq, "parcelas": parc,
                 "nsu": re.sub(r'\s+', '', (d.get("nsu") or ""))[:30].upper(), "forma_pgto_id": forma, "conta_id": conta,
                 "hon_no_cartao": _sim(d.get("hon_no_cartao"), True),
                 # retorno e custo da maquininha: só quem vê lucro informa (os outros mantêm o que já estava)
                 "retorno_tipo": ((d.get("retorno_tipo") or "").strip().upper()[:10] if vl else (atual or {}).get('retorno_tipo', '')),
                 "retorno_valor": (_num(d.get("retorno_valor")) if vl else (atual or {}).get('retorno_valor') or 0),
                 "custo_maquininha": (_num(d.get("custo_maquininha")) if vl else (atual or {}).get('custo_maquininha') or 0)}
            hon_novo = _num(d.get("honorario")) if d.get("honorario") not in (None, '') else None
            calc = _parc_calc(cur, o['id'], p, honorario=hon_novo)
            if _sim(d.get("simular"), False):      # só calcula (tela mostra ao vivo), não grava nada
                if not vl:
                    calc = {k: calc[k] for k in ('debitos', 'acrescimo', 'valor_cartao')}
                return jsonify({"ok": True, "calc": calc})
            acr = _num(calc['acrescimo'])
            if hon_novo is not None and hon_novo != (o['honorario'] or 0):
                cur.execute("UPDATE ordens_servico SET honorario=%s WHERE id=%s", (hon_novo, o['id']))
                _ocorrencia(cur, o['id'], 'outras', 'Honorário do parcelamento: R$ %s' % _br(hon_novo))
            # acréscimo do parcelamento: item separado (receita), fora do repasse
            cur.execute("SELECT id FROM os_itens WHERE os_id=%s AND origem='acrescimo'", (o['id'],))
            ia = cur.fetchone()
            desc_acr = "ACRÉSCIMO PARCELAMENTO NO CARTÃO (%dx)" % parc
            if acr > 0 and ia:
                cur.execute("UPDATE os_itens SET valor=%s, custo=0, qtd=1, descricao=%s WHERE id=%s", (acr, desc_acr, ia['id']))
            elif acr > 0:
                cur.execute("""INSERT INTO os_itens (os_id, descricao, qtd, valor, custo, user_nome, natureza, categoria, origem)
                               VALUES (%s,%s,1,%s,0,%s,'honorario','','acrescimo')""", (o['id'], desc_acr, acr, _eu()))
            elif ia:
                cur.execute("DELETE FROM os_itens WHERE id=%s", (ia['id'],))
            cols = ("data", "valor_cartao", "maquininha", "parcelas", "nsu", "forma_pgto_id", "conta_id", "hon_no_cartao",
                    "retorno_tipo", "retorno_valor", "custo_maquininha")
            if atual:
                cur.execute("UPDATE os_parcelamentos SET " + ", ".join(c + "=%s" for c in cols) +
                            ", atualizado=NOW(), user_nome=%s WHERE id=%s", tuple(p[c] for c in cols) + (_eu(), atual['id']))
                pid, rec_id = atual['id'], atual['recebimento_id']
            else:
                cur.execute("INSERT INTO os_parcelamentos (os_id, " + ", ".join(cols) + ", user_nome) VALUES (%s," +
                            ",".join(["%s"] * len(cols)) + ",%s) RETURNING id", (o['id'],) + tuple(p[c] for c in cols) + (_eu(),))
                pid, rec_id = cur.fetchone()['id'], None
            cur.execute("""UPDATE ordens_servico SET processo_tipo_id = COALESCE(processo_tipo_id,
                             (SELECT id FROM processo_tipos WHERE upper(nome) = upper(%s) LIMIT 1)) WHERE id=%s""",
                        (TIPO_PARCELAMENTO, o['id']))
            _ocorrencia(cur, o['id'], 'outras', 'Parcelamento no cartão: R$ %s em %dx na %s — débitos R$ %s, acréscimo R$ %s'
                        % (_br(cartao), parc, maq, _br(calc['debitos']), _br(acr)))
            msg_rec = ''
            if not rec_id and _sim(d.get("lancar_recebimento"), True):
                try:
                    rec_id, st = _receber(cur, numero, {"valor": str(cartao), "forma_pgto_id": forma, "conta_id": conta,
                                                        "maquininha": maq, "parcelas": parc, "nsu": p['nsu'],
                                                        "data": p['data'].isoformat(), "obs": "Parcelamento de débitos no cartão"})
                    cur.execute("UPDATE os_parcelamentos SET recebimento_id=%s WHERE id=%s", (rec_id, pid))
                    msg_rec = 'pendente' if st == 'pendente' else 'ok'
                except ValueError as e:
                    msg_rec = str(e)
            _toca(cur, o['id'])
        return jsonify({"ok": True, "calc": calc, "recebimento": msg_rec})

    @app.route("/api/os/<int:numero>/parcelamento", methods=["DELETE"])
    @equipe
    def os_parcelamento_del(numero):
        if not _admin():
            return jsonify({"erro": "Só o administrador desfaz o parcelamento."}), 403
        with db(commit=True) as cur:
            o = _os_por_numero(cur, numero)
            if not o:
                return jsonify({"erro": "OS não encontrada"}), 404
            cur.execute("DELETE FROM os_parcelamentos WHERE os_id=%s", (o['id'],))
            cur.execute("DELETE FROM os_itens WHERE os_id=%s AND origem='acrescimo'", (o['id'],))
            _ocorrencia(cur, o['id'], 'outras', 'Dados do parcelamento no cartão apagados (o recebimento continua na aba Recebimentos)')
            _toca(cur, o['id'])
        return jsonify({"ok": True})

    # ── atendimento avulso rápido (sem placa, sempre com honorário) ──
    @app.route("/api/os/avulso", methods=["POST"])
    @equipe
    def os_avulso():
        d = request.get_json() or {}
        servico = (d.get("servico") or "").strip().upper()
        valor = _num(d.get("valor"))
        if not servico:
            return jsonify({"erro": "Diga qual foi o serviço (consulta, agendamento...)."}), 400
        if valor <= 0:
            return jsonify({"erro": "Atendimento avulso sempre tem honorário: informe o valor."}), 400
        try:
            return _avulso_grava(d, servico, valor)
        except _Rollback as e:
            return jsonify({"erro": str(e)}), 400

    def _avulso_grava(d, servico, valor):
        with db(commit=True) as cur:
            cid = d.get("cliente_id")
            if not cid:
                nome = (d.get("nome") or "").strip().upper()
                if not nome:
                    raise _Rollback("Informe o nome do cliente.")
                doc = _so_dig(d.get("cpf_cnpj"))
                if doc:
                    cur.execute("SELECT id FROM clientes WHERE regexp_replace(cpf_cnpj,'\\D','','g') = %s LIMIT 1", (doc,))
                    c_ = cur.fetchone()
                    cid = c_['id'] if c_ else None
                if not cid:
                    cur.execute("""INSERT INTO clientes (cpf_cnpj, nome, cel, tipo) VALUES (%s,%s,%s,%s) RETURNING id""",
                                (_fmt_doc(doc) if doc else '', nome, (d.get("cel") or "").strip(),
                                 'pj' if len(doc) == 14 else 'pf'))
                    cid = cur.fetchone()['id']
            vid = None
            placa = re.sub(r'[^A-Z0-9]', '', (d.get("placa") or "").upper())
            if placa:
                cur.execute("SELECT id FROM veiculos WHERE upper(regexp_replace(placa,'[^A-Za-z0-9]','','g')) = %s LIMIT 1", (placa,))
                v_ = cur.fetchone()
                if v_:
                    vid = v_['id']
                else:
                    cur.execute("INSERT INTO veiculos (placa, proprietario_id) VALUES (%s,%s) RETURNING id", (placa, cid))
                    vid = cur.fetchone()['id']
            numero = _proximo_numero(cur)
            cur.execute("""INSERT INTO ordens_servico (numero, tipo, cliente_id, veiculo_id, user_id, user_nome, status,
                               honorario, obs, empresa_id, processo_tipo_id)
                           VALUES (%s,'os',%s,%s,%s,%s,'andamento',0,%s,%s,
                                   (SELECT id FROM processo_tipos WHERE upper(nome) = upper(%s) LIMIT 1)) RETURNING id""",
                        (numero, cid, vid, str(session.get('user_id') or ''), _eu(), (d.get("obs") or "").strip(),
                         session.get('empresa_id'), TIPO_AVULSO))
            oid = cur.fetchone()['id']
            _ocorrencia(cur, oid, 'outras', 'Atendimento avulso aberto por %s' % _eu())
            _add_item(cur, oid, {"descricao": servico, "valor": str(valor), "natureza": "honorario"})
            st = None
            rec = d.get("recebimento") or {}
            if rec.get("forma_pgto_id"):
                rec = dict(rec, valor=str(valor), obs=rec.get("obs") or 'Atendimento avulso')
                try:
                    _, st = _receber(cur, numero, rec)
                except ValueError as e:
                    raise _Rollback(str(e))
                if st == 'confirmado':
                    cur.execute("UPDATE ordens_servico SET status='concluida' WHERE id=%s", (oid,))
                    _ocorrencia(cur, oid, 'outras', 'Em andamento → Concluída (atendimento avulso pago na hora)')
        return jsonify({"ok": True, "numero": numero, "recebimento": st})

    # ── itens ──────────────────────────────────────────────────
    def _natureza(it):
        nat = (it.get("natureza") or "").strip().lower()
        if nat in ('repasse', 'honorario'):
            return nat
        tp = it.get("tipo_item") or it.get("tipo")
        return 'honorario' if tp == 'hon' else ('repasse' if tp == 'taxa' else '')

    def _add_item(cur, oid, it):
        """Item da OS. REPASSE: custo = valor que vai para o órgão (DUA/boleto); o que for cobrado acima
        disso é receita. HONORÁRIO: custo 0, tudo é receita."""
        sid = it.get("servico_id") or None
        vl = _perms(cur)['ver_lucro']
        desc = (it.get("descricao") or "").strip().upper()
        valor, custo = it.get("valor"), (it.get("custo") if vl else None)
        nat, cat = _natureza(it), (it.get("categoria") or "").strip().lower()
        s_ = None
        if sid:
            cur.execute("SELECT * FROM servicos WHERE id = %s", (sid,))
            s_ = cur.fetchone()
            if s_:
                desc = desc or s_['nome']
                if valor in (None, ''):
                    valor = s_['valor_padrao']
                nat = nat or s_.get('natureza') or ('repasse' if (s_['custo_padrao'] or 0) > 0 else 'honorario')
                cat = cat or (s_.get('categoria') or '')
        if not desc:
            raise ValueError("Informe a descrição do item.")
        nat = nat or 'repasse'
        valor = _num(valor)
        if nat == 'honorario':
            custo, cat = Decimal('0'), ''
        else:
            if custo in (None, ''):
                custo = min(_num(s_['custo_padrao']), valor) if (s_ and (s_['custo_padrao'] or 0) > 0) else valor
            custo = _num(custo)
            if cat not in CAT_REPASSE:
                cat = _cat_palpite(desc)
        qtd = _num(it.get("qtd"), Decimal('1')) or Decimal('1')
        cur.execute("""INSERT INTO os_itens (os_id, servico_id, descricao, qtd, valor, custo, user_nome,
                           natureza, categoria, orgao, documento)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (oid, sid, desc, qtd, valor, custo, _eu(), nat, cat,
                     (it.get("orgao") or "").strip().upper() if nat == 'repasse' else '',
                     (it.get("documento") or "").strip().upper() if nat == 'repasse' else ''))
        iid = cur.fetchone()['id']
        if sid:  # OS ainda sem tipo de processo herda o do serviço lançado
            cur.execute("""UPDATE ordens_servico SET processo_tipo_id =
                             (SELECT processo_tipo_id FROM servicos WHERE id = %s)
                           WHERE id = %s AND processo_tipo_id IS NULL""", (sid, oid))
        return iid

    # ── arquivos (comprovantes) ────────────────────────────────
    def _salvar_arquivo(cur, oid, arq):
        """arq = {nome, mime, dados(base64)} → id em arquivos."""
        if not arq or not arq.get("dados"):
            return None
        import base64
        mime = (arq.get("mime") or "").lower()
        if mime not in ARQ_MIMES:
            raise ValueError("Comprovante tem que ser PDF ou foto (JPG/PNG).")
        b64 = arq["dados"].split(",", 1)[-1]
        try:
            dados = base64.b64decode(b64, validate=False)
        except Exception:
            raise ValueError("Arquivo do comprovante inválido.")
        if len(dados) > ARQ_MAX:
            raise ValueError("Comprovante muito grande (máx. 6 MB).")
        cur.execute("""INSERT INTO arquivos (nome, mime, tamanho, dados, os_id, user_nome)
                       VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                    ((arq.get("nome") or "comprovante")[:120], mime, len(dados), dados, oid, _eu()))
        return cur.fetchone()['id']

    @app.route("/api/arquivos/<int:aid>", methods=["GET"])
    @equipe
    def arquivo_ver(aid):
        from flask import Response
        with db() as cur:
            pm = _perms(cur)
            if not (pm['ver_lucro'] or pm['dar_baixa']):
                return jsonify({"erro": "Sem permissão para ver comprovantes."}), 403
            cur.execute("SELECT nome, mime, dados FROM arquivos WHERE id = %s", (aid,))
            a = cur.fetchone()
        if not a:
            return jsonify({"erro": "Arquivo não encontrado"}), 404
        nome = re.sub(r'[^A-Za-z0-9._ -]', '_', a['nome'] or 'comprovante')
        return Response(bytes(a['dados']), mimetype=a['mime'],
                        headers={"Content-Disposition": 'inline; filename="%s"' % nome})

    # ── pagamento do repasse (sai do caixa, com comprovante) ───
    def _registrar_repasse(cur, o, d):
        if not _perms(cur)['dar_baixa']:
            raise PermissionError("Só quem dá baixa registra pagamento de repasse (saída do caixa).")
        valor = _num(d.get("valor"))
        if valor <= 0:
            raise ValueError("Informe o valor pago.")
        if not d.get("conta_id"):
            raise ValueError("Escolha de qual conta saiu o pagamento.")
        dia = _data(d.get("data")) or _hoje()
        item = None
        if d.get("item_id"):
            cur.execute("SELECT * FROM os_itens WHERE id=%s AND os_id=%s", (d["item_id"], o['id']))
            item = cur.fetchone()
            if not item or item['natureza'] != 'repasse':
                raise ValueError("Item de repasse não encontrado nesta OS.")
        orgao = (d.get("orgao") or (item['orgao'] if item else '') or '').strip().upper()
        docto = (d.get("documento") or (item['documento'] if item else '') or '').strip().upper()
        if item and ((orgao and not item['orgao']) or (docto and not item['documento'])):
            cur.execute("""UPDATE os_itens SET orgao = CASE WHEN orgao = '' THEN %s ELSE orgao END,
                                               documento = CASE WHEN documento = '' THEN %s ELSE documento END
                           WHERE id = %s""", (orgao, docto, item['id']))
        aid = _salvar_arquivo(cur, o['id'], d.get("arquivo"))
        desc_it = item['descricao'] if item else 'REPASSE'
        quando = datetime.combine(dia, _agora().timetz())
        cur.execute("""INSERT INTO lancamentos (natureza, vencimento, pago_em, descricao, favorecido, documento,
                           valor, valor_pago, conta_id, os_id, obs, user_nome, empresa_id)
                       VALUES ('pagar', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                    (dia, quando, "REPASSE: %s — O.S. Nº %s" % (desc_it, o['numero']), orgao, docto,
                     valor, valor, d["conta_id"], o['id'], (d.get("obs") or "").strip(), _eu(), session.get('empresa_id')))
        lid = cur.fetchone()['id']
        cur.execute("""INSERT INTO os_repasse_pagtos (os_id, item_id, data, conta_id, valor, orgao, documento,
                           arquivo_id, lancamento_id, obs, user_nome)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (o['id'], item['id'] if item else None, dia, d["conta_id"], valor, orgao, docto, aid, lid,
                     (d.get("obs") or "").strip(), _eu()))
        pid = cur.fetchone()['id']
        cur.execute("SELECT nome FROM contas WHERE id=%s", (d["conta_id"],))
        cn = (cur.fetchone() or {}).get('nome', '')
        _ocorrencia(cur, o['id'], 'outras', 'Repasse pago: %s — R$ %s (saiu da %s em %s)%s%s'
                    % (desc_it, _br(valor), cn, dia.strftime('%d/%m/%Y'), (' · DUA/boleto ' + docto) if docto else '',
                       ' · comprovante anexado' if aid else ' · SEM COMPROVANTE'))
        return pid

    @app.route("/api/os/<int:numero>/repasses", methods=["POST"])
    @equipe
    def os_repasse_add(numero):
        d = request.get_json() or {}
        with db(commit=True) as cur:
            o = _os_por_numero(cur, numero)
            if not o:
                return jsonify({"erro": "OS não encontrada"}), 404
            try:
                pid = _registrar_repasse(cur, o, d)
            except PermissionError as e:
                return jsonify({"erro": str(e)}), 403
            except ValueError as e:
                return jsonify({"erro": str(e)}), 400
            _toca(cur, o['id'])
        return jsonify({"ok": True, "id": pid})

    @app.route("/api/os-repasses/<int:pid>/comprovante", methods=["POST"])
    @equipe
    def os_repasse_comprovante(pid):
        d = request.get_json() or {}
        with db(commit=True) as cur:
            if not _perms(cur)['dar_baixa']:
                return jsonify({"erro": "Sem permissão."}), 403
            cur.execute("SELECT * FROM os_repasse_pagtos WHERE id=%s", (pid,))
            p_ = cur.fetchone()
            if not p_:
                return jsonify({"erro": "Pagamento não encontrado"}), 404
            try:
                aid = _salvar_arquivo(cur, p_['os_id'], d.get("arquivo"))
            except ValueError as e:
                return jsonify({"erro": str(e)}), 400
            if not aid:
                return jsonify({"erro": "Escolha o arquivo do comprovante."}), 400
            cur.execute("UPDATE os_repasse_pagtos SET arquivo_id=%s WHERE id=%s", (aid, pid))
            _ocorrencia(cur, p_['os_id'], 'outras', 'Comprovante anexado ao repasse de R$ %s' % _br(p_['valor']))
            _toca(cur, p_['os_id'])
        return jsonify({"ok": True})

    @app.route("/api/os/<int:numero>/repasses/<int:pid>", methods=["DELETE"])
    @equipe
    def os_repasse_del(numero, pid):
        if not _admin():
            return jsonify({"erro": "Só o administrador exclui pagamento de repasse."}), 403
        with db(commit=True) as cur:
            o = _os_por_numero(cur, numero)
            if not o:
                return jsonify({"erro": "OS não encontrada"}), 404
            cur.execute("DELETE FROM os_repasse_pagtos WHERE id=%s AND os_id=%s RETURNING valor, lancamento_id, arquivo_id",
                        (pid, o['id']))
            r = cur.fetchone()
            if r:
                if r['lancamento_id']:
                    cur.execute("DELETE FROM lancamentos WHERE id=%s", (r['lancamento_id'],))
                if r['arquivo_id']:
                    cur.execute("DELETE FROM arquivos WHERE id=%s", (r['arquivo_id'],))
                _ocorrencia(cur, o['id'], 'outras', 'Pagamento de repasse excluído: R$ %s' % _br(r['valor']))
            _toca(cur, o['id'])
        return jsonify({"ok": True})

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
                cur.execute("SELECT natureza, custo, valor, qtd FROM os_itens WHERE id=%s", (iid,))
                x = cur.fetchone()
                if x['natureza'] != 'repasse':
                    return jsonify({"erro": "Só item de repasse tem pagamento a terceiro."}), 400
                pg = dict(pg, item_id=iid, valor=pg.get("valor") or str((x['custo'] or x['valor']) * x['qtd']),
                          orgao=pg.get("orgao") or d.get("orgao"), documento=pg.get("documento") or d.get("documento"))
                try:
                    _registrar_repasse(cur, o, pg)
                except PermissionError as e:
                    return jsonify({"erro": str(e)}), 403
                except ValueError as e:
                    return jsonify({"erro": str(e)}), 400
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
            cur.execute("SELECT * FROM os_itens WHERE id=%s AND os_id=%s", (iid, o['id']))
            it = cur.fetchone()
            if not it:
                return jsonify({"erro": "Item não encontrado"}), 404
            nat = _natureza(d) or it['natureza'] or 'repasse'
            valor = _num(d.get("valor")) if d.get("valor") not in (None, '') else it['valor']
            qtd = _num(d.get("qtd"), Decimal('1')) or Decimal('1') if d.get("qtd") not in (None, '') else it['qtd']
            if nat == 'honorario':
                custo = Decimal('0')
            elif "custo" in d and _perms(cur)['ver_lucro'] and d.get("custo") not in (None, ''):
                custo = _num(d.get("custo"))
            elif it['natureza'] != 'repasse' or not (it['custo'] or 0) > 0:
                custo = valor                         # virou repasse agora: repasse = valor cobrado
            else:
                custo = min(it['custo'], valor)        # sem ver lucro: mantém o custo (nunca acima do valor)
            cat = (d.get("categoria") or it['categoria'] or '').lower() if nat == 'repasse' else ''
            if nat == 'repasse' and cat not in CAT_REPASSE:
                cat = _cat_palpite(d.get("descricao") or it['descricao'])
            cur.execute("""UPDATE os_itens SET descricao=%s, qtd=%s, valor=%s, custo=%s, natureza=%s, categoria=%s,
                                              orgao=%s, documento=%s WHERE id=%s""",
                        ((d.get("descricao") or it['descricao']).strip().upper(), qtd, valor, custo, nat, cat,
                         (d.get("orgao", it['orgao']) or '').strip().upper() if nat == 'repasse' else '',
                         (d.get("documento", it['documento']) or '').strip().upper() if nat == 'repasse' else '', iid))
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

    def _receber(cur, numero, d):
        """Lança um recebimento na OS (com baixa se o usuário pode dar baixa). Devolve (id, status)."""
        valor = _num(d.get("valor"))
        if valor <= 0:
            raise ValueError("Informe o valor recebido.")
        if not d.get("forma_pgto_id"):
            raise ValueError("Escolha a forma de pagamento.")
        if not d.get("conta_id"):
            raise ValueError("Escolha a conta.")
        if True:
            cur.execute("SELECT nome FROM formas_pgto WHERE id=%s", (d["forma_pgto_id"],))
            ftipo = _forma_tipo((cur.fetchone() or {}).get('nome'))
            maq, parc, nsu = '', 1, ''
            if ftipo in ('debito', 'credito'):
                maq = (d.get("maquininha") or "").strip().upper()
                if maq not in MAQUININHAS:
                    raise ValueError("Pagamento no cartão: escolha a maquininha (Stone, Sicredi ou Listo).")
                nsu = re.sub(r'\s+', '', (d.get("nsu") or ""))[:30].upper()
                if ftipo == 'credito':
                    try:
                        parc = int(d.get("parcelas") or 1)
                    except (TypeError, ValueError):
                        parc = 1
                    if not 1 <= parc <= 24:
                        raise ValueError("Parcelas: de 1 a 24.")
            r = _os_completa(cur, numero)
            if not r:
                raise ValueError("OS não encontrada")
            o = r['os']
            livre = o['devedor'] - o.get('aguardando_baixa', 0)
            if float(valor) > livre + 0.004:
                msg = "Valor maior que o saldo devedor (R$ %s)." % _br(o['devedor'])
                if o.get('aguardando_baixa'):
                    msg += " Já há R$ %s informado aguardando baixa." % _br(o['aguardando_baixa'])
                raise ValueError(msg)
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
            cartao = (' · %s%s%s' % (maq, (' %dx' % parc) if ftipo == 'credito' else '', (' · NSU ' + nsu) if nsu else '')) if maq else ''
            lid = None
            if baixa:
                lid = _gerar_lancamento(cur, o['id'], numero, quando, valor, d["conta_id"], centro,
                                        d["forma_pgto_id"], (obs + cartao).strip(' ·'), fav, _eu())
            cur.execute("""INSERT INTO os_recebimentos (os_id, quando, valor, forma_pgto_id, conta_id,
                               centro_id, obs, user_nome, lancamento_id, status, baixa_por, baixa_em,
                               maquininha, parcelas, nsu)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                        (o['id'], quando, valor, d["forma_pgto_id"], d["conta_id"], centro, obs, _eu(), lid,
                         'confirmado' if baixa else 'pendente', _eu() if baixa else '', _agora() if baixa else None,
                         maq, parc, nsu))
            rid = cur.fetchone()['id']
            cur.execute("SELECT nome FROM formas_pgto WHERE id=%s", (d["forma_pgto_id"],))
            fn = ((cur.fetchone() or {}).get('nome', '') + cartao)
            if baixa:
                _ocorrencia(cur, o['id'], 'outras', 'Recebido R$ %s (%s) — baixa por %s' % (_br(valor), fn, _eu()))
            else:
                _ocorrencia(cur, o['id'], 'outras', 'Recebimento de R$ %s (%s) informado por %s — AGUARDANDO BAIXA'
                            % (_br(valor), fn, _eu()))
            _toca(cur, o['id'])
        return rid, ('confirmado' if baixa else 'pendente')

    @app.route("/api/os/<int:numero>/recebimentos", methods=["POST"])
    @equipe
    def os_receber(numero):
        d = request.get_json() or {}
        with db(commit=True) as cur:
            try:
                rid, st = _receber(cur, numero, d)
            except ValueError as e:
                return jsonify({"erro": str(e)}), 400
        return jsonify({"ok": True, "status": st, "id": rid})

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
                cartao = (' · %s%s%s' % (r['maquininha'], (' %dx' % r['parcelas']) if (r['parcelas'] or 1) > 1 else '',
                                         (' · NSU ' + r['nsu']) if r['nsu'] else '')) if r.get('maquininha') else ''
                lid = _gerar_lancamento(cur, r['oid'], r['numero'], r['quando'], r['valor'], r['conta_id'],
                                        r['centro_id'], r['forma_pgto_id'], ((r['obs'] or '') + cartao).strip(' ·'), fav, r['user_nome'])
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
            if tipo == 'entregue' and o['status'] != 'entregue':
                erro = _hon_zero_checa(cur, o, 'entregue', d.get("hon_zero_motivo"))
                if erro:
                    return jsonify(erro), 400
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
    # ── RECIBO: taxas pelo valor real do DUA (reembolso) + honorários num total só ──
    @app.route("/api/os/<int:numero>/recibo", methods=["GET"])
    @equipe
    def os_recibo(numero):
        with db(commit=True) as cur:
            d = _os_completa(cur, numero)
            if not d:
                return jsonify({"erro": "OS não encontrada"}), 404
            o = d['os']
            oid = _os_por_numero(cur, numero)['id']
            cur.execute("""SELECT descricao, categoria, orgao, documento, custo, qtd FROM os_itens
                           WHERE os_id = %s AND natureza = 'repasse' ORDER BY id""", (oid,))
            taxas = []
            for i in cur.fetchall():
                v = round(_f(i['custo']) * _f(i['qtd'] or 1), 2)
                taxas.append({"descricao": i['descricao'] or '', "categoria": CAT_REPASSE.get(i['categoria'] or '', ''),
                              "orgao": i['orgao'] or '', "documento": i['documento'] or '', "valor": v})
            cur.execute("""SELECT COALESCE(SUM(valor*qtd),0) AS v FROM os_itens WHERE os_id=%s""", (oid,))
            itens_v = _f(cur.fetchone()['v'])
            cur.execute("SELECT honorario, desconto FROM ordens_servico WHERE id=%s", (oid,))
            hd = cur.fetchone()
            total = round(itens_v + _f(hd['honorario']) - _f(hd['desconto']), 2)
            tx = round(sum(t['valor'] for t in taxas), 2)
            receb = [{"data": (x['quando'] or '')[:10], "forma": x.get('forma') or '', "maquininha": x.get('maquininha') or '',
                      "parcelas": x.get('parcelas') or None, "valor": x['valor']}
                     for x in d['recebimentos'] if (x.get('status') or 'confirmado') == 'confirmado']
            pago = round(sum(x['valor'] for x in receb), 2)
            pag = d.get('responsavel') or d.get('cliente') or {}
            vei = d.get('veiculo') or {}
            _ocorrencia(cur, oid, 'outras', 'Recibo emitido (R$ %s)' % _brl(pago))
        return jsonify({"numero": numero, "data_abertura": (o.get('data_abertura') or '')[:10],
                        "pagador": {"nome": pag.get('nome') or '', "cpf_cnpj": pag.get('cpf_cnpj') or ''},
                        "cliente": (d.get('cliente') or {}).get('nome') or '',
                        "veiculo": {"placa": vei.get('placa') or '', "modelo": vei.get('modelo') or ''},
                        "taxas": taxas, "taxas_total": tx, "honorarios": round(total - tx, 2), "total": total,
                        "recebimentos": receb, "pago": pago, "devedor": round(max(total - pago, 0), 2) if o.get('status') != 'cancelada' else 0.0})

    # ── NOTA FISCAL (NFS-e) DO HONORÁRIO ──────────────────────
    def _nota_de(cur, r):
        """Valor sugerido da nota de uma OS (linha com SQL_TOTAIS): receita; no parcelamento, o critério."""
        o = _os_saida(r)
        cur.execute("SELECT * FROM os_parcelamentos WHERE os_id = %s", (r['id'],))
        pr = cur.fetchone()
        calc = _parc_calc(cur, r['id'], pr) if pr else None
        o['nota_valor'] = calc['nota'] if calc else o['receita']
        o['acrescimo'] = calc['acrescimo'] if calc else 0.0
        o['retorno'] = _f(pr['retorno_valor']) if pr else 0.0
        o['maquininha_custo'] = _f(pr['custo_maquininha']) if pr else 0.0
        o['parcelamento'] = bool(pr)
        return o

    def _pode_nf(cur):
        p = _perms(cur)
        return p['ver_lucro'] or p['dar_baixa']

    @app.route("/api/os/<int:numero>/nota", methods=["POST"])
    @equipe
    def os_nota(numero):
        d = request.get_json() or {}
        with db(commit=True) as cur:
            if not _pode_nf(cur):
                return jsonify({"erro": "Sem permissão para lançar nota fiscal."}), 403
            o = _os_por_numero(cur, numero)
            if not o:
                return jsonify({"erro": "OS não encontrada"}), 404
            num = (d.get("nf_numero") or "").strip()
            st = (d.get("nf_status") or ("emitida" if num else "pendente")).strip().lower()
            if st not in NF_STATUS:
                return jsonify({"erro": "Situação da nota inválida."}), 400
            if st == 'emitida' and not num:
                return jsonify({"erro": "Informe o número da NFS-e."}), 400
            obs = (d.get("nf_obs") or "").strip()
            if st == 'dispensada' and not obs:
                return jsonify({"erro": "Diga o motivo de não emitir a nota."}), 400
            dt = _data(d.get("nf_data")) if d.get("nf_data") else (_hoje() if st == 'emitida' else None)
            val = _num(d.get("nf_valor")) if d.get("nf_valor") not in (None, '') else None
            cur.execute("""UPDATE ordens_servico SET nf_status=%s, nf_numero=%s, nf_data=%s, nf_valor=%s, nf_obs=%s
                           WHERE id=%s""", (st, num if st == 'emitida' else '', dt if st == 'emitida' else None,
                                            val if st == 'emitida' else None, obs, o['id']))
            txt = {"emitida": "NFS-e nº %s emitida%s" % (num, (" — R$ " + _brl(val)) if val is not None else ""),
                   "pendente": "Nota fiscal marcada como pendente",
                   "dispensada": "Nota fiscal dispensada: " + obs}[st]
            _ocorrencia(cur, o['id'], 'nota_fiscal', txt)
        return jsonify({"ok": True})

    @app.route("/api/notas-fiscais", methods=["GET"])
    @equipe
    def notas_fiscais():
        """OS com honorário (valor da nota > 0). situacao=pendente (padrão) | emitida | dispensada | todas."""
        sit = (request.args.get("situacao") or "pendente").lower()
        de, ate = request.args.get("de"), request.args.get("ate")
        with db() as cur:
            if not _pode_nf(cur):
                return jsonify({"erro": "Sem permissão."}), 403
            vl = _perms(cur)['ver_lucro']
            cond, args = ["o.excluida_em IS NULL", "o.status NOT IN ('orcamento','cancelada')"], []
            if sit in NF_STATUS:
                cond.append("COALESCE(o.nf_status,'pendente') = %s"); args.append(sit)
            if de:
                cond.append("o.data_abertura::date >= %s"); args.append(_data(de))
            if ate:
                cond.append("o.data_abertura::date <= %s"); args.append(_data(ate))
            cur.execute("""SELECT o.*, c.nome AS cliente_nome, c.cpf_cnpj AS cliente_doc, v.placa, """ + SQL_TOTAIS + """
                           FROM ordens_servico o LEFT JOIN clientes c ON c.id = o.cliente_id
                           LEFT JOIN veiculos v ON v.id = o.veiculo_id
                           WHERE """ + " AND ".join(cond) + " ORDER BY o.data_abertura, o.numero", args)
            out, soma = [], 0.0
            for r in cur.fetchall():
                o = _nota_de(cur, r)
                if o['nota_valor'] <= 0.004 and o['nf_status'] != 'emitida':
                    continue
                x = {k: o.get(k) for k in ('numero', 'cliente_nome', 'cliente_doc', 'placa', 'status', 'total', 'pago',
                                           'devedor', 'nf_status', 'nf_numero', 'nf_obs')}
                x['data'] = (_d(r['data_abertura']) or '')[:10]
                x['nf_data'] = _d(r['nf_data'])
                x['nf_valor'] = _f(r['nf_valor']) if r['nf_valor'] is not None else None
                if vl:
                    x['nota_valor'] = o['nota_valor']; x['receita'] = o['receita']
                    soma += o['nota_valor']
                out.append(x)
        return jsonify({"itens": out, "total_nota": round(soma, 2) if vl else None})

    # ── RELATÓRIO MENSAL DO CONTADOR ───────────────────────────
    def _mes_args():
        m = (request.args.get("mes") or _hoje().strftime("%Y-%m")).strip()
        if not re.match(r"^\d{4}-\d{2}$", m):
            raise ValueError("Mês inválido (use AAAA-MM).")
        a, mm = int(m[:4]), int(m[5:])
        ini = date(a, mm, 1)
        fim = date(a + (mm == 12), (mm % 12) + 1, 1) - timedelta(days=1)
        return m, ini, fim

    def _rel_contador(cur, ini, fim):
        """Mês do contador. Recebimentos e repasses pela data do pagamento; NFS-e pela data de emissão;
        honorários pelo regime das Configurações (competência: data da nota ou da conclusão; caixa: data do recebimento)."""
        regime = _regime(cur)
        dq = "(r.quando AT TIME ZONE 'America/Sao_Paulo')::date"
        cur.execute("""SELECT r.*, f.nome AS forma, c.nome AS conta, o.numero, o.id AS oid, cl.nome AS cliente_nome, """ + dq + """ AS dia
                       FROM os_recebimentos r JOIN ordens_servico o ON o.id = r.os_id
                       LEFT JOIN formas_pgto f ON f.id = r.forma_pgto_id LEFT JOIN contas c ON c.id = r.conta_id
                       LEFT JOIN clientes cl ON cl.id = o.cliente_id
                       WHERE o.excluida_em IS NULL AND r.status IN ('confirmado','pendente') AND """ + dq + """ BETWEEN %s AND %s
                       ORDER BY r.quando, r.id""", (ini, fim))
        receb, por_forma, pend, rec_os, cartoes = [], {}, 0.0, {}, []
        for x in cur.fetchall():
            v = _f(x['valor']); tp = _forma_tipo(x['forma'])
            rot = {"pix": "PIX", "dinheiro": "DINHEIRO", "outro": (x['forma'] or 'OUTROS').upper()}.get(tp) or \
                  ("CARTÃO %s — %s" % ("DÉBITO" if tp == 'debito' else "CRÉDITO", (x['maquininha'] or 'SEM MAQUININHA').upper()))
            if x['status'] == 'confirmado':
                por_forma[rot] = round(por_forma.get(rot, 0) + v, 2)
                rec_os[x['oid']] = rec_os.get(x['oid'], 0) + v
                if tp in ('debito', 'credito'):
                    cartoes.append({"oid": x['oid'], "os": x['numero'], "cliente": x['cliente_nome'] or '',
                                    "maquininha": (x['maquininha'] or 'SEM MAQUININHA').upper(), "valor": v})
            else:
                pend += v
            receb.append({"data": _d(x['dia']), "os": x['numero'], "cliente": x['cliente_nome'] or '', "forma": x['forma'] or '',
                          "grupo": rot, "maquininha": x['maquininha'] or '', "parcelas": x['parcelas'] or None,
                          "nsu": x['nsu'] or '', "conta": x['conta'] or '', "valor": v,
                          "situacao": "CONFIRMADO" if x['status'] == 'confirmado' else "AGUARDANDO BAIXA"})
        # repasses pagos no mês
        cur.execute("""SELECT p.*, c.nome AS conta, o.numero, i.descricao, i.categoria, cl.nome AS cliente_nome
                       FROM os_repasse_pagtos p JOIN ordens_servico o ON o.id = p.os_id
                       LEFT JOIN contas c ON c.id = p.conta_id LEFT JOIN os_itens i ON i.id = p.item_id
                       LEFT JOIN clientes cl ON cl.id = o.cliente_id
                       WHERE o.excluida_em IS NULL AND p.data BETWEEN %s AND %s ORDER BY p.data, p.id""", (ini, fim))
        reps, rep_cat = [], {}
        for x in cur.fetchall():
            v = _f(x['valor']); cat = CAT_REPASSE.get(x['categoria'] or '', (x['categoria'] or 'OUTROS').upper())
            rep_cat[cat] = round(rep_cat.get(cat, 0) + v, 2)
            reps.append({"data": _d(x['data']), "os": x['numero'], "cliente": x['cliente_nome'] or '', "item": x['descricao'] or '',
                         "categoria": cat, "orgao": x['orgao'] or '', "documento": x['documento'] or '',
                         "conta": x['conta'] or '', "valor": v, "comprovante": bool(x['arquivo_id'])})
        # OS do mês conforme o regime
        base_sql = """COALESCE(CASE WHEN o.nf_status = 'emitida' THEN o.nf_data END,
                                (o.concluida_em AT TIME ZONE 'America/Sao_Paulo')::date)"""
        sel = """SELECT o.*, c.nome AS cliente_nome, c.cpf_cnpj AS cliente_doc, v.placa, pt.nome AS tipo_nome,
                        """ + base_sql + """ AS data_base, """ + SQL_TOTAIS + """
                 FROM ordens_servico o LEFT JOIN clientes c ON c.id = o.cliente_id
                 LEFT JOIN veiculos v ON v.id = o.veiculo_id LEFT JOIN processo_tipos pt ON pt.id = o.processo_tipo_id
                 WHERE o.excluida_em IS NULL AND o.status NOT IN ('orcamento','cancelada') AND """
        if regime == 'caixa':
            if rec_os:
                cur.execute(sel + "o.id = ANY(%s) ORDER BY o.numero", (list(rec_os.keys()),))
                linhas_os = cur.fetchall()
            else:
                linhas_os = []
        else:
            cur.execute(sel + base_sql + " BETWEEN %s AND %s ORDER BY " + base_sql + ", o.numero", (ini, fim))
            linhas_os = cur.fetchall()
        oss = []
        for r in linhas_os:
            o = _nota_de(cur, r)
            rec_m = round(rec_os.get(r['id'], 0), 2)
            fr = 1.0
            if regime == 'caixa':
                fr = min(1.0, rec_m / o['total']) if o['total'] > 0.004 else 0.0
            oss.append({"os": o['numero'], "data": (_d(r['data_abertura']) or '')[:10],
                        "conclusao": (_d(r['concluida_em']) or '')[:10] if r.get('concluida_em') else '',
                        "data_base": _d(r['data_base']) if r.get('data_base') else '',
                        "cliente": r['cliente_nome'] or '',
                        "cpf_cnpj": r['cliente_doc'] or '', "placa": r['placa'] or '', "tipo": r['tipo_nome'] or '',
                        "status": STATUS_OS.get(o['status'], o['status']), "total": o['total'],
                        "repasse": round(o['repasse_total'] * fr, 2), "receita": round(o['receita'] * fr, 2),
                        "receita_total": o['receita'], "acrescimo": round(o['acrescimo'] * fr, 2),
                        "retorno": round(o['retorno'] * fr, 2), "custo_maquininha": round(o['maquininha_custo'] * fr, 2),
                        "nota_sugerida": o['nota_valor'], "recebido_mes": rec_m,
                        "nf_status": NF_STATUS.get(o['nf_status'], 'PENDENTE'), "nf_numero": o.get('nf_numero') or '',
                        "nf_valor": _f(r['nf_valor']) if r['nf_valor'] is not None else None,
                        "recebido": o['pago'], "devedor": o['devedor'], "hon_zero_motivo": r.get('hon_zero_motivo') or ''})
        # NFS-e emitidas no mês (pela data de emissão, qualquer OS)
        cur.execute("""SELECT o.numero, o.nf_numero, o.nf_data, o.nf_valor, c.nome AS cliente_nome FROM ordens_servico o
                       LEFT JOIN clientes c ON c.id = o.cliente_id
                       WHERE o.excluida_em IS NULL AND o.nf_status = 'emitida' AND o.nf_data BETWEEN %s AND %s
                       ORDER BY o.nf_data, o.numero""", (ini, fim))
        nfs = [{"data": _d(x['nf_data']), "os": x['numero'], "cliente": x['cliente_nome'] or '', "nf_numero": x['nf_numero'],
                "valor": _f(x['nf_valor']) if x['nf_valor'] is not None else 0.0} for x in cur.fetchall()]
        sem_nota = [x for x in oss if x['nota_sugerida'] > 0.004 and x['nf_status'] == 'PENDENTE']
        hon_zero = [x for x in oss if x['nota_sugerida'] <= 0.004 and x['receita_total'] <= 0.004]
        dimp = _dimp(cur, cartoes)
        sm = lambda l, k: round(sum((x[k] or 0) for x in l), 2)
        resumo = {
            "regime": regime, "regime_nome": REGIMES[regime],
            "os_qtd": len(oss), "os_total": sm(oss, 'total'), "repasses_os": sm(oss, 'repasse'),
            "honorarios": sm(oss, 'receita'), "acrescimos": sm(oss, 'acrescimo'), "retornos": sm(oss, 'retorno'),
            "custo_maquininha": sm(oss, 'custo_maquininha'), "nota_sugerida": sm(oss, 'nota_sugerida'),
            "recebido": round(sum(por_forma.values()), 2), "recebido_por_forma": dict(sorted(por_forma.items())),
            "aguardando_baixa": round(pend, 2), "repasses_pagos": sm(reps, 'valor'), "repasses_por_categoria": dict(sorted(rep_cat.items())),
            "repasses_sem_comprovante": len([x for x in reps if not x['comprovante']]),
            "nfs_emitidas_qtd": len(nfs), "nfs_emitidas_valor": sm(nfs, 'valor'),
            "sem_nota_qtd": len(sem_nota), "sem_nota_valor": sm(sem_nota, 'nota_sugerida'), "hon_zero_qtd": len(hon_zero),
            "dimp_bruto": dimp['total']['bruto'], "dimp_sem_explicacao": dimp['total']['sem_explicacao']}
        return {"resumo": resumo, "os": oss, "recebimentos": receb, "repasses": reps, "notas": nfs,
                "sem_nota": sem_nota, "hon_zero": hon_zero, "dimp": dimp}

    def _dimp(cur, cartoes):
        """Conferência DIMP: cartão bruto do mês por maquininha, explicado por repasse documentado (DUA/comprovante)
        e por receita com NFS-e emitida; o resto fica sem explicação. Cada pagamento no cartão explica a parte
        proporcional dele no total da OS (não supõe que o cartão pagou primeiro as taxas)."""
        info = {}
        for oid in {c['oid'] for c in cartoes}:
            cur.execute("SELECT o.*, " + SQL_TOTAIS + " FROM ordens_servico o WHERE o.id = %s", (oid,))
            r = cur.fetchone()
            o = _nota_de(cur, r)
            cur.execute("""SELECT COALESCE(SUM(i.custo*i.qtd),0) AS v FROM os_itens i
                           WHERE i.os_id = %s AND i.natureza = 'repasse' AND (COALESCE(i.documento,'') <> '' OR EXISTS (
                             SELECT 1 FROM os_repasse_pagtos p WHERE p.item_id = i.id
                               AND (p.arquivo_id IS NOT NULL OR COALESCE(p.documento,'') <> '')))""", (oid,))
            doc = _f(cur.fetchone()['v'])
            cur.execute("""SELECT COALESCE(SUM(valor),0) AS v FROM os_repasse_pagtos WHERE os_id = %s AND item_id IS NULL
                           AND (arquivo_id IS NOT NULL OR COALESCE(documento,'') <> '')""", (oid,))
            doc += _f(cur.fetchone()['v'])
            doc = min(doc, o['repasse_total']) if o['repasse_total'] > 0 else doc
            emit = (o.get('nf_status') == 'emitida')
            nota = (_f(r['nf_valor']) if r['nf_valor'] is not None else o['nota_valor']) if emit else 0.0
            motivos = []
            if o['repasse_total'] - doc > 0.004:
                motivos.append("repasse sem DUA/comprovante (%s)" % _brl(o['repasse_total'] - doc))
            if not emit and o['receita'] > 0.004:
                motivos.append("sem NFS-e")
            elif emit and o['nota_valor'] - nota > 0.004:
                motivos.append("nota menor que o honorário")
            info[oid] = {"total": o['total'], "doc": doc, "nota": nota, "motivos": motivos}
        maqs = {m: {"maquininha": m, "bruto": 0.0, "repasse_doc": 0.0, "receita_nota": 0.0, "sem_explicacao": 0.0, "qtd": 0}
                for m in MAQUININHAS}
        por_os = {}
        for c in cartoes:
            i = info[c['oid']]; v = c['valor']
            fr = v / i['total'] if i['total'] > 0.004 else 0.0
            rp = min(v, i['doc'] * fr); nt = min(v - rp, i['nota'] * fr); se = max(0.0, v - rp - nt)
            g = maqs.setdefault(c['maquininha'], {"maquininha": c['maquininha'], "bruto": 0.0, "repasse_doc": 0.0,
                                                   "receita_nota": 0.0, "sem_explicacao": 0.0, "qtd": 0})
            g['bruto'] += v; g['repasse_doc'] += rp; g['receita_nota'] += nt; g['sem_explicacao'] += se; g['qtd'] += 1
            k = (c['os'], c['maquininha'])
            e = por_os.setdefault(k, {"os": c['os'], "cliente": c['cliente'], "maquininha": c['maquininha'], "cartao": 0.0,
                                      "repasse_doc": 0.0, "receita_nota": 0.0, "sem_explicacao": 0.0,
                                      "motivo": "; ".join(i['motivos']) or "—"})
            e['cartao'] += v; e['repasse_doc'] += rp; e['receita_nota'] += nt; e['sem_explicacao'] += se
        arred = lambda d: {k: (round(v, 2) if isinstance(v, float) else v) for k, v in d.items()}
        linhas = [arred(g) for g in maqs.values()]
        tot = {"maquininha": "TOTAL", "qtd": sum(g['qtd'] for g in linhas)}
        for k in ("bruto", "repasse_doc", "receita_nota", "sem_explicacao"):
            tot[k] = round(sum(g[k] for g in linhas), 2)
        os_l = sorted([arred(e) for e in por_os.values() if e['sem_explicacao'] > 0.004], key=lambda e: -e['sem_explicacao'])
        return {"maquininhas": linhas, "total": tot, "os": os_l}

    @app.route("/api/relatorio-contador", methods=["GET"])
    @equipe
    def relatorio_contador():
        try:
            m, ini, fim = _mes_args()
        except ValueError as e:
            return jsonify({"erro": str(e)}), 400
        with db() as cur:
            if not _perms(cur)['ver_lucro']:
                return jsonify({"erro": "Só quem vê o financeiro completo gera o relatório do contador."}), 403
            r = _rel_contador(cur, ini, fim)
        r.update({"mes": m, "de": _d(ini), "ate": _d(fim)})
        return jsonify(r)

    @app.route("/api/relatorio-contador.xlsx", methods=["GET"])
    @equipe
    def relatorio_contador_xlsx():
        from io import BytesIO
        from flask import send_file
        try:
            m, ini, fim = _mes_args()
        except ValueError as e:
            return jsonify({"erro": str(e)}), 400
        with db() as cur:
            if not _perms(cur)['ver_lucro']:
                return jsonify({"erro": "Sem permissão."}), 403
            r = _rel_contador(cur, ini, fim)
        return send_file(BytesIO(xlsx_contador(r, m, ini, fim)), as_attachment=True, download_name="contador_%s.xlsx" % m.replace('-', '_'),
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

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
