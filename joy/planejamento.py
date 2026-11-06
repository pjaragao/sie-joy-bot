"""Módulo de consulta ao planejamento financeiro e operacional da unidade SIÉ JOY."""
from typing import Any, Dict

CAPEX_ITEMS = [
    {"code": "INV01", "name": "Comunicação Visual & Letreiro Glow", "valor": 4500.0, "pct": 15.0, "desc": "Logo SIÉ acrílico retroiluminado LED, painel boas-vindas e sinalização."},
    {"code": "INV02", "name": "Araras Móveis de Design Premium", "valor": 5200.0, "pct": 17.3, "desc": "3 módulos móveis em metalon escovado (dourado/preto fosco) e base madeira nobre."},
    {"code": "INV03", "name": "Manequins & Bustos de Alta Performance", "valor": 3800.0, "pct": 12.7, "desc": "2 manequins estilizados corpo inteiro alta definição + 1 busto de mesa."},
    {"code": "INV04", "name": "Balcão PDV / Móvel Caixa sob Medida", "valor": 4500.0, "pct": 15.0, "desc": "Marcenaria sob medida compacta, gavetas com fechadura eletrônica e nichos."},
    {"code": "INV05", "name": "Hardware PDV (iPad/Tablet + Suporte + Leitor)", "valor": 3500.0, "pct": 11.7, "desc": "Terminal touch para frente de caixa, suporte articulado e leitor de código de barras."},
    {"code": "INV06", "name": "Maquininha Stone/SIPAG + Certificado A1", "valor": 1200.0, "pct": 4.0, "desc": "Equipamento POS Stone Smart integrado + Certificado digital e-CNPJ A1 para NFC-e."},
    {"code": "INV07", "name": "Decoração, Iluminação, Cabides & Aroma", "valor": 3300.0, "pct": 11.0, "desc": "Spots iluminação direcionada, 100 cabides madeira nobre, difusor aroma SIÉ."},
    {"code": "INV08", "name": "Capital de Giro Inicial / Reserva de Implantação", "valor": 4000.0, "pct": 13.3, "desc": "Fundo de reserva em caixa para suporte operacional nos primeiros dias."},
]
TOTAL_CAPEX = 30000.0

CUSTOS_FIXOS = {
    "carencia_meses": 3,
    "aluguel_regular": 6000.0,
    "total_mensal_carencia": 4502.50,
    "total_mensal_regular": 10502.50,
    "itens": [
        {"item": "Aluguel JOY (após carência)", "valor": 6000.0},
        {"item": "Salário Base Vendedora (CLT 30h)", "valor": 2100.0},
        {"item": "Vale-Transporte Líquido", "valor": 534.0},
        {"item": "Encargos Trabalhistas & Provisões", "valor": 598.50},
        {"item": "Honorários Contábeis", "valor": 650.0},
        {"item": "Software PDV Nuvem & Emissor Fiscal", "valor": 220.0},
        {"item": "Despesas Gerais / Limpeza / Internet", "valor": 400.0},
    ]
}

EVENTOS = {
    "frequencia": "Bimestral (meses 1, 3, 5, 7, 9, 11...)",
    "custo_por_evento": 4000.0,
    "custo_medio_mensal": 2000.0,
    "desembolso_anual": 24000.0,
    "itens_inclusos": "DJ, coquetel funcional/saudável, decoração floral, fotógrafo e influenciadoras locais."
}

CENARIOS = {
    "padrao": "Cenário sugerido com faturamento crescente (ramping up de 400 a 1.000 alunos JOY, vendas de R$ 30k a R$ 70k+ com amortização no 3º a 4º mês graças à carência).",
    "quadro_comparativo": [
        {"cenario": "Cenário 1 (18m)", "faturamento": 30909.82, "cmv": 12879.09, "lucro_medio": 1666.67, "margem": "5,4%", "payback": "18 meses", "venda_dia": 1188.84},
        {"cenario": "Cenário 2 (12m)", "faturamento": 32727.73, "cmv": 13636.55, "lucro_medio": 2500.00, "margem": "7,6%", "payback": "12 meses", "venda_dia": 1258.76},
        {"cenario": "Cenário 3 (6m)", "faturamento": 38181.44, "cmv": 15908.93, "lucro_medio": 5000.00, "margem": "13,1%", "payback": "6 meses", "venda_dia": 1468.52},
        {"cenario": "Cenário 4 (Compra 25k)", "faturamento": 60000.00, "cmv": 25000.00, "lucro_medio": 13861.70, "margem": "23,1%", "payback": "2,2 meses (65 dias)", "venda_dia": 2307.69},
        {"cenario": "Cenário 5 (Compra 30k)", "faturamento": 72000.00, "cmv": 30000.00, "lucro_medio": 18558.54, "margem": "25,8%", "payback": "1,6 meses (49 dias)", "venda_dia": 2769.23},
        {"cenario": "Cenário 6 (Compra 35k)", "faturamento": 84000.00, "cmv": 35000.00, "lucro_medio": 23483.38, "margem": "28,0%", "payback": "1,3 meses (38 dias)", "venda_dia": 3230.77},
    ]
}

def consultar_planejamento(topico: str = "todos") -> str:
    """Retorna detalhes formatados do planejamento financeiro."""
    t = (topico or "").lower().strip()
    if t in ("capex", "investimento"):
        lines = ["*ORÇAMENTO DE INVESTIMENTO INICIAL (CAPEX: R$ 30.000,00):*"]
        for it in CAPEX_ITEMS:
            lines.append(f"• *{it['code']} - {it['name']}*: R$ {it['valor']:,.2f} ({it['pct']}%) — {it['desc']}")
        lines.append(f"\n*TOTAL CAPEX:* R$ {TOTAL_CAPEX:,.2f}")
        return "\n".join(lines)
    
    if t in ("custos_fixos", "opex", "aluguel"):
        lines = ["*ESTRUTURA DE CUSTOS FIXOS MENSAIS (OPEX):*"]
        lines.append(f"• Carência de Aluguel: 3 meses iniciais (economia de R$ 18.000 preservados no caixa!)")
        lines.append(f"• Custo Fixo durante a Carência: R$ {CUSTOS_FIXOS['total_mensal_carencia']:,.2f}/mês")
        lines.append(f"• Custo Fixo Regular pós-carência: R$ {CUSTOS_FIXOS['total_mensal_regular']:,.2f}/mês\n")
        lines.append("*Composição:*")
        for it in CUSTOS_FIXOS["itens"]:
            lines.append(f"• {it['item']}: R$ {it['valor']:,.2f}/mês")
        return "\n".join(lines)

    if t in ("cenarios", "metas", "payback"):
        lines = [f"*CENÁRIOS FINANCEIROS E PRAZOS DE RETORNO:*", f"Padrão adotado: {CENARIOS['padrao']}\n"]
        for c in CENARIOS["quadro_comparativo"]:
            lines.append(f"• *{c['cenario']}*: Faturamento R$ {c['faturamento']:,.2f} | Lucro Líq: R$ {c['lucro_medio']:,.2f} ({c['margem']}) | Payback: {c['payback']} | Venda/Dia: R$ {c['venda_dia']:,.2f}")
        return "\n".join(lines)

    if t in ("eventos", "drops"):
        lines = ["*PLANEJAMENTO DE EVENTOS BIMESTRAIS & DROPS:*"]
        lines.append(f"• Frequência: {EVENTOS['frequencia']}")
        lines.append(f"• Investimento por evento: R$ {EVENTOS['custo_por_evento']:,.2f}")
        lines.append(f"• Provisão contábil média: R$ {EVENTOS['custo_medio_mensal']:,.2f}/mês (R$ 24k/ano)")
        lines.append(f"• Escopo: {EVENTOS['itens_inclusos']}")
        return "\n".join(lines)

    # Visão geral consolidada
    return (
        "*RESUMO EXECUTIVO DO PLANEJAMENTO SIÉ JOY:*\n\n"
        f"1. *Capex Inicial:* R$ 30.000,00 distribuídos em 8 rubricas essenciais.\n"
        f"2. *Aluguel & Carência:* 3 meses de carência (preserva R$ 18.000), depois R$ 6.000/mês.\n"
        f"3. *Custos Fixos:* R$ 4.502,50/mês (carência) → R$ 10.502,50/mês (regular).\n"
        f"4. *Eventos & Drops:* R$ 4.000 a cada 60 dias (meses ímpares).\n"
        f"5. *Cenário Padrão:* Ramping up de 400 a 1.000 alunas JOY, amortizando os R$ 30k entre o 3º e 4º mês de operação.\n\n"
        "Para detalhes específicos use: capex, custos_fixos, cenarios ou eventos."
    )
