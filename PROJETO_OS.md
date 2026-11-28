# SISTEMA ATPV E AJUSTES — Documento do projeto

Atualizado em 28/11/2026. Este arquivo guarda tudo que foi decidido e feito para não se perder entre conversas.

## 1. O que é

Sistema web do escritório **Diego Despachante / Caetano Despachante Ltda** (Anápolis-GO).
- Produção: https://atpv-sistema.onrender.com (Render, Postgres)
- Código: GitHub `diego7327-sys/atpv-sistema` (Flask + Postgres, Python)
- Arquivos principais: `app.py` (ATPV-e, agenda/recursos, relatórios, login), `os_modulo.py` (Ordens de Serviço, financeiro, fiscal), `templates/index.html` (tela principal e ATPV), `templates/os_modulo.html` (tela das OS), `requirements.txt` (precisa ter `openpyxl`).

## 2. Regras de trabalho (não quebrar)

1. **Tudo novo é feito só no ramo `teste-os-bitdesp`.** Nunca mexer no `main` nem na produção sem o Diego mandar subir.
2. O site de produção só é olhado (leitura), nunca alterado direto.
3. Prévia para o Diego testar: artifact "Prévia — Ordens de Serviço" (dados de exemplo em memória; recarregar a página apaga os testes).
4. Um passo de cada vez, com validação do Diego entre os passos. Respostas em português, curtas e diretas.
5. Nunca colocar o telefone antigo **(62) 3321-0040** em nenhum material. Celular principal (62) 99110-1506; escritório (62) 99267-3252.
6. Cliente nunca vê custo/margem. Lucro só o Diego ou quem ele autorizar. Funcionário só **informa** recebimento; **baixa** só quem tem permissão.
7. Não gravar senhas, tokens ou chaves em arquivos do projeto nem em commits.
8. Commits terminam com `Co-Authored-By: Claude ...` e o link da sessão.

## 3. Numeração e integração (decisões do Diego)

- **Toda OS nova começa em 40000** (veículos, ATPV, recursos). O número do BitDesp fica só para consultar processos antigos (campo "Nº OS BitDesp").
- **Cada ATPV (cada placa) = uma OS**, não importa quem paga. Entra nos relatórios da garagem/concessionária, com opção de tirar a OS do relatório (ex.: cliente desistiu e foi feito outro ATPV).
- **Valor do ATPV é decidido em cada um** (não existe valor padrão). Sem valor o sistema leva direto ao campo "Valor do serviço". Botão **🎁 Cortesia** = OS concluída com R$ 0,00 e motivo CORTESIA.
- ATPVs antigos: só daqui para frente; cadastros de clientes e veículos que já existem são mantidos.
- **Agenda de Prazos** passou a se chamar **Recursos de Multa e Suspensão de CNH** e cria OS (valor, entrada, cortesia, ou vincular a OS existente).
- A aba antiga "Recursos de Multa e Suspensão de CNH" (tabela `processos`) vai **sair do menu, mas os dados ficam guardados** (etapa 3, pendente). Hoje aparece como "Recursos (antigo)".

## 4. O que já está pronto no ramo de teste

**Ordens de Serviço (modelo BitDesp)**
- Nova OS com veículo, cliente e responsável na mesma tela (blocos coloridos), tipo de processo, taxas/débitos/despesas, desconto, acréscimo, honorário, total e adiantado.
- Orçamento que vira OS (mesmas cores da OS; tipo de processo no bloco Serviços).
- Documento da OS no modelo BitDesp (A4), aba Requerimentos (6 modelos em PDF com carimbo e assinatura), pendências com atalhos.
- Botão Voltar para a tela de origem (cliente, veículos, financeiro, ATPV, recursos).
- Painel: OS abertas hoje/ontem/mês e por quem; relatório por funcionário (OS e orçamentos por dia/mês, aprovadas, concluídas, canceladas, faturamento, honorários, lucro — PDF e Excel).
- Relatório do cliente/garagem com placa, marca/modelo e chassi (PDF deitado e Excel), filtros e "☑ Escolher OS" para excluir OS.

**Financeiro e fiscal**
- Item REPASSE (dinheiro de terceiros: DUA, taxas DETRAN, vistoria) x HONORÁRIO (serviço do escritório).
- Recebimento em dinheiro/PIX/cartão (maquininhas **SICREDI, STONE, LISTO** — Listo cai no **BRADESCO**), parcelamento no cartão (retorno padrão R6, honorário padrão 0).
- Pagamento de taxa pelo valor real do DUA (diferença vira honorário); pagar todas as taxas pendentes de uma vez com comprovante.
- NFS-e por OS (anexo PDF/XML), lista de OS sem nota; recibo PDF (taxas pelo valor do DUA, honorário somado).
- Relatório do contador (Excel e PDF): regime **competência** (data da nota ou conclusão) ou **caixa** (data do recebimento) escolhido em Configurações; notas contam pela data de emissão.
- Regime de caixa: **taxas primeiro** (o dinheiro recebido cobre primeiro as taxas; o que sobra é honorário).
- **Conferência DIMP** por maquininha: bruto, repasse documentado, receita com nota, adiantamento (amarelo, DUA ainda não pago), diferença sem explicação (vermelho).
- Adiantamento parado há mais de 60 dias: alerta com 3 saídas — pagar a taxa, devolver ao cliente (com comprovante) ou reconhecer como receita.
- OS cancelada com dinheiro recebido: devolver (com comprovante) ou reter (vira receita e entra na lista sem nota).
- Importar extrato OFX/CSV (banco e relatório da maquininha) com conciliação automática e manual.

**ATPV-e integrado**
- Salvar histórico cria a OS (tipo ATPV). No histórico aparecem "OS nº" e "💰 Receber"; o status do ATPV (pendente/pago/cancelado/cortesia) vem da OS.
- Por que a OS de ATPV não tem Repasse: o valor do ATPV é todo serviço do escritório (honorário). Repasse só aparece se lançar taxa de terceiro.
- Só entra no Extrato do Financeiro quando o recebimento é registrado.
- Busca única: Vendedor, Comprador, Procurador, Contratante e Veículo procuram no cadastro do ATPV, nos clientes das OS e nos clientes de recursos/agenda; escolher a placa já preenche o vendedor com o proprietário.

**Recursos de Multa e Suspensão de CNH (antiga Agenda de Prazos)**
- Campos novos: CPF/CNPJ do cliente (com busca), placa, quadro "💰 Ordem de Serviço" (valor ★, 🎁 Cortesia, entrada recebida agora, "já existe OS? nº").
- Ao salvar cria a OS (40000+); se tiver entrada, abre na hora o recebimento com o valor preenchido.
- Tipo da OS automático: Recurso de Multa, Suspensão de CNH, Cassação de CNH, Transferência ou Outros. Despachante parceiro vira responsável pela OS.
- Lista mostra "OS 40xxx" e "💰 Receber" em cada processo.

## 5. Pendências (em ordem)

1. **Etapa 3:** tirar "Recursos (antigo)" do menu, mantendo os dados da tabela `processos`.
2. Validar tudo com o Diego na prévia / ambiente de teste.
3. **Subir para a produção** (só quando o Diego mandar): conferir `openpyxl` no `requirements.txt`, backup do banco antes, migrações rodam sozinhas (tabela `migracoes`).
4. Testar o importador de extrato com arquivos reais do banco e das maquininhas.
5. Por último: link de assinatura dos requerimentos pelo WhatsApp.

## 6. Observações técnicas

- Migrações controladas pela tabela `migracoes` (ex.: `os_fiscal_v3`, `os_fiscal_v4`, `os_func_v1`, `os_num_40000`).
- Ganchos entre módulos em `app.config`: `OS_DE_ATPV`, `OS_ATPV_VALOR`, `OS_ATPV_APAGADO`, `OS_DE_AGENDA`.
- Tabela `agenda` ganhou `os_id`, `placa`, `cliente_cpf`.
- Existe no repositório um arquivo `templates/index .html` (com espaço no nome) que não é usado — avaliar remoção junto com a subida.
