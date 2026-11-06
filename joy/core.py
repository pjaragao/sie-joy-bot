"""Motor central de operações da loja SIÉ JOY — roteador de consultas da ferramenta sie_joy."""
import datetime
import logging
import re
import unicodedata
from typing import Any, Dict

import arquivos
import financeiro
import group_history
import pendencias
import pesquisa
import planejamento

logger = logging.getLogger("sie_joy")

DIAS_PT = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
_SEM = {"segunda": 0, "seg": 0, "terca": 1, "ter": 1, "quarta": 2, "qua": 2, "quinta": 3, "qui": 3, "sexta": 4, "sex": 4,
        "sabado": 5, "sab": 5, "domingo": 6, "dom": 6}


def _rel(v: Any) -> Any:
    """Resolve datas relativas ('hoje', 'ontem', 'amanhã', 'sexta', 'dd/mm/aaaa') para AAAA-MM-DD."""
    if not isinstance(v, str) or not v.strip():
        return v
    t = unicodedata.normalize("NFKD", v).encode("ascii", "ignore").decode().lower().strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", t):
        return v[:10]
    resto = re.sub(r"^(na |no |nesta |neste |proxima |proximo |[aà]s? )", "", t).replace("-feira", "").strip()
    hoje = datetime.date.today()
    d = None
    if resto == "hoje":
        d = hoje
    elif resto == "ontem":
        d = hoje - datetime.timedelta(days=1)
    elif resto == "anteontem":
        d = hoje - datetime.timedelta(days=2)
    elif resto == "amanha":
        d = hoje + datetime.timedelta(days=1)
    elif resto == "depois de amanha":
        d = hoje + datetime.timedelta(days=2)
    elif resto.split(" ")[0] in _SEM:
        wd = _SEM[resto.split(" ")[0]]
        if wd == hoje.weekday() and re.search(r"\b(nest[ea]|ness[ea]|hoje)\b", t):
            d = hoje
        else:
            d = hoje + datetime.timedelta(days=(wd - hoje.weekday() - 1) % 7 + 1)
    else:
        m = re.match(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$", resto)
        if m:
            ano = int(m.group(3)) + (2000 if m.group(3) and len(m.group(3)) == 2 else 0) if m.group(3) else hoje.year
            d = datetime.date(ano, int(m.group(2)), int(m.group(1)))
    return d.isoformat() if d else v


def run_query(consulta: str, args: Dict[str, Any]) -> str:
    """Executa a operação solicitada pela ferramenta sie_joy."""
    c = (consulta or "").lower().strip()
    args = dict(args)
    for k in ("data_gasto", "data_reembolso", "prazo"):
        if k in args and args[k]:
            args[k] = _rel(args[k])

    try:
        if c == "agora":
            n = datetime.datetime.now()
            return f"{DIAS_PT[n.weekday()]}, {n:%d/%m/%Y} {n:%H:%M} (America/Sao_Paulo)"

        if c == "lancar_reembolso":
            valor = float(args.get("valor") or 0.0)
            descricao = str(args.get("descricao") or args.get("alvo") or "")
            data_gasto = args.get("data_gasto")
            fornecedor = args.get("fornecedor")
            cnpj_cpf = args.get("cnpj_cpf")
            tipo_doc = str(args.get("tipo_doc") or "RECIBO")
            numero_doc = args.get("numero_doc")
            justificativa = args.get("justificativa")
            forcar = str(args.get("forcar", "")).lower() in ("1", "true", "sim")
            return financeiro.lancar_reembolso(
                descricao=descricao,
                valor=valor,
                data_gasto=data_gasto,
                fornecedor=fornecedor,
                cnpj_cpf=cnpj_cpf,
                tipo_doc=tipo_doc,
                numero_doc=numero_doc,
                justificativa=justificativa,
                conta_contabil=args.get("conta_contabil"),
                centro_custo=args.get("centro_custo"),
                forcar=forcar,
            )

        if c == "editar_reembolso":
            v = args.get("valor")
            return financeiro.editar_reembolso(
                numero=str(args.get("numero") or ""),
                valor=float(v) if v not in (None, "") else None,
                descricao=args.get("descricao"), data_gasto=args.get("data_gasto"),
                fornecedor=args.get("fornecedor"), cnpj_cpf=args.get("cnpj_cpf"), tipo_doc=args.get("tipo_doc"),
                numero_doc=args.get("numero_doc"), justificativa=args.get("justificativa"),
                conta_contabil=args.get("conta_contabil"), centro_custo=args.get("centro_custo"),
                data_reembolso=args.get("data_reembolso"),
                item=int(args["item"]) if args.get("item") not in (None, "") else None)

        if c == "cancelar_reembolso":
            return financeiro.cancelar_reembolso(str(args.get("numero") or ""), args.get("motivo"))

        if c == "vincular_fornecedores":
            return financeiro.vincular_fornecedores()

        if c == "sincronizar_reembolsos":
            return financeiro.sincronizar_pendentes()

        if c == "registrar_pendencia":
            return pendencias.registrar(str(args.get("titulo") or args.get("alvo") or ""), args.get("detalhe"),
                                        args.get("responsavel"), args.get("prazo"))

        if c == "atualizar_pendencia":
            return pendencias.atualizar(int(args.get("id") or 0), str(args.get("estado") or ""), args.get("evidencia"))

        if c == "listar_pendencias":
            return pendencias.listar(str(args.get("estado") or "aberto"), int(args.get("limite") or 30))

        if c == "listar_reembolsos":
            limite = int(args.get("limite") or 10)
            return financeiro.listar_reembolsos(limit=limite)

        if c == "resumo_capex":
            return financeiro.resumo_capex()

        if c in ("consultar_planejamento", "planejamento"):
            topico = str(args.get("topico") or args.get("alvo") or "todos")
            return planejamento.consultar_planejamento(topico)

        if c in ("pesquisar_produtos", "pesquisa_web"):
            termo = str(args.get("termo") or args.get("alvo") or "")
            foco = str(args.get("foco") or "produtos e fornecedores para loja de roupas")
            profundo = str(args.get("profundo", "")).lower() in ("1", "true", "sim")
            return pesquisa.pesquisar_web(termo, foco, profundo=profundo)

        if c == "web_pesquisar":
            termo = str(args.get("termo") or args.get("busca") or args.get("alvo") or "")
            profundo = str(args.get("profundo", "")).lower() in ("1", "true", "sim")
            return pesquisa.web(termo, profundo=profundo)

        if c == "historico_grupo":
            horas = float(args.get("horas") or 24.0)
            busca = str(args.get("busca") or args.get("alvo") or "").strip().lower()
            msgs = group_history.get_recent_messages(hours=horas)
            if busca:
                msgs = [m for m in msgs if busca in (m.get("text") or "").lower()]
            return group_history.format_messages(msgs)

        if c == "arquivos":
            return arquivos.resumo()

        if c == "arquivo_ler":
            return arquivos.ler(str(args.get("busca") or args.get("alvo") or args.get("termo") or ""))

        if c in ("relatorio_romaneio", "romaneio"):
            import romaneio   # carrega só quando pedido: reportlab/pypdf ficam em joy/_vendor
            enviar = str(args.get("enviar", "true")).lower() not in ("0", "false", "nao", "não")
            return romaneio.relatorio(str(args.get("busca") or args.get("alvo") or ""), enviar=enviar)

        if c == "organizar_arquivos":
            return arquivos.organizar() + "\n" + arquivos.notas()

        if c in ("ajuda", "help"):
            return (
                "*COMANDOS E CONSULTAS DISPONÍVEIS:* \n"
                "• `agora`: Data, hora e dia da semana em Brasília\n"
                "• `lancar_reembolso`: Lança despesa para reembolso a Paulo Jr (valor, descricao, fornecedor...)\n"
                "• `listar_reembolsos`: Lista os reembolsos já registrados\n"
                "• `resumo_capex`: Mostra Capex orçado (30k) vs realizado\n"
                "• `consultar_planejamento`: Detalhes de capex, custos fixos, cenários ou eventos\n"
                "• `editar_reembolso` / `cancelar_reembolso`: corrige valor, data, fornecedor, conta... de um REE-AAAA-NNNN\n"
                "• `sincronizar_reembolsos`: Reenvia ao CentralOps o que ficou só no livro local\n"
                "• `registrar_pendencia` / `atualizar_pendencia` / `listar_pendencias`: livro de decisões em aberto\n"
                "• `arquivo_ler`: lê o conteúdo (OCR/Office) de um arquivo recebido no grupo, achado por nome/assunto\n"
                "• `relatorio_romaneio`: gera o PDF de conferência do romaneio da La Sirene (fotos, descrição, quantidade por tamanho; cruza com NF em revisão e pedido) e envia no grupo\n"
                "• `arquivos` / `organizar_arquivos`: pastas organizadas dos arquivos do grupo / força a organização agora\n"
                "• `pesquisar_produtos` / `web_pesquisar`: Pesquisa fornecedores/produtos ou pesquisa geral na web\n"
                "• `historico_grupo`: Mensagens recentes trocadas no WhatsApp"
            )

        return f"Consulta '{consulta}' não reconhecida. Use 'ajuda' para ver as consultas disponíveis."
    except Exception as exc:
        logger.error("[sie_joy] erro ao executar consulta %s: %s", consulta, exc, exc_info=True)
        return f"Erro ao processar consulta '{consulta}': {exc}"
