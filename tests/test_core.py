"""Testes offline (sem tocar no CentralOps real). Rodar no container:
   docker exec -e HERMES_HOME=/tmp/joytest -e SUPABASE_URL=http://127.0.0.1:9 sie-joy-bot \
       /opt/hermes/.venv/bin/python /opt/joy/../tests/test_core.py   (ou montar tests/)
"""
import datetime
import os
import shutil
import sys

assert os.environ.get("HERMES_HOME", "").startswith("/tmp"), "use HERMES_HOME=/tmp/... (nunca o real)"
assert "127.0.0.1" in os.environ.get("SUPABASE_URL", ""), "use SUPABASE_URL inalcançável (teste offline)"
shutil.rmtree(os.environ["HERMES_HOME"], ignore_errors=True)
os.makedirs(os.environ["HERMES_HOME"])
sys.path.insert(0, os.environ.get("JOY_DIR", "/opt/joy"))

import core, financeiro, pendencias  # noqa: E402

# data de reembolso: dia 10 do mês seguinte ao LANÇAMENTO, não ao gasto
assert financeiro.calcular_data_reembolso(datetime.date(2026, 10, 15)) == "2026-11-10"
assert financeiro.calcular_data_reembolso(datetime.date(2026, 12, 31)) == "2027-01-10"

# classificação por palavra inteira
assert financeiro.classificar_codigo("3 araras de metalon") == "1.2.1.02"
assert financeiro.classificar_codigo("posição do balcão na planta") == "1.2.1.02"
assert financeiro.classificar_codigo("tablet + suporte") == "1.2.1.03"
assert financeiro.classificar_codigo("estágio de vendas") is None
assert financeiro.mapear_centro_custo("DJ do coquetel")[1].startswith("Eventos")

# contas novas do plano (implantação)
for desc, code in (("Taxa DARE abertura de empresa", "7.2.10"), ("honorários da advogada do contrato", "7.2.11"),
                   ("linha celular Vivo pós", "7.2.13"), ("seguro da loja", "7.2.16"), ("100 cabides de madeira", "1.2.1.04"),
                   ("sacolas P e M", "6.1.02"), ("certificado digital A1", "7.2.06"), ("papelaria e toner", "7.2.14")):
    assert financeiro.classificar_codigo(desc) == code, (desc, financeiro.classificar_codigo(desc))
# sem correspondência: pergunta em vez de lançar em 7.2.99
assert "Não lancei" in core.run_query("lancar_reembolso", {"descricao": "coisa misteriosa", "valor": 10})

# lançamento offline: grava local, avisa que CentralOps não confirmou, reembolso = dia 10 do mês que vem
r = core.run_query("lancar_reembolso", {"descricao": "3 araras de metalon", "valor": 5200, "data_gasto": "2026-09-20"})
assert "CentralOps não confirmou" in r and "REE-" in r, r
nxt = financeiro.calcular_data_reembolso()
assert datetime.date.fromisoformat(nxt).strftime("%d/%m/%Y") in r, r

# duplicata bloqueada; forcar libera; data futura e valor inválido rejeitados
assert "duplicado" in core.run_query("lancar_reembolso", {"descricao": "3 araras de metalon", "valor": 5200, "data_gasto": "2026-09-20"})
assert "REE-" in core.run_query("lancar_reembolso", {"descricao": "3 araras de metalon", "valor": 5200, "data_gasto": "2026-09-20", "forcar": True})
assert "futuro" in core.run_query("lancar_reembolso", {"descricao": "x tablet", "valor": 10, "data_gasto": "2999-01-01"})
assert "Erro" in core.run_query("lancar_reembolso", {"descricao": "tablet", "valor": 0})

# override explícito de conta/centro
r = core.run_query("lancar_reembolso", {"descricao": "taxa qualquer", "valor": 10, "data_gasto": "2026-10-01",
                                        "conta_contabil": "7.3.01", "centro_custo": "EVENTOS"})
assert "7.3.01" in r and "MKT-EVENTOS" in r, r

# numeração sequencial e resumo separa capex de opex
assert financeiro._next_number().endswith("0004")
assert "Realizado (capex)" in core.run_query("resumo_capex", {})

# pendências: efetivar exige evidência
assert "registrada" in core.run_query("registrar_pendencia", {"titulo": "Orçamento letreiro"})
assert "Erro" in core.run_query("atualizar_pendencia", {"id": 1, "estado": "efetivado"})
assert "efetivado" in core.run_query("atualizar_pendencia", {"id": 1, "estado": "efetivado", "evidencia": "Luisa: fechei o letreiro"})
assert "Nenhuma" in core.run_query("listar_pendencias", {})
print("TODOS OS TESTES OK")
