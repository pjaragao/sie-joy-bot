"""Relatório de conferência do romaneio da La Sirene: lê o PDF do romaneio, cruza com o catálogo do CentralOps, a NF de entrada
em revisão e o pedido de compra lançado, e gera um PDF com um cartão por peça + cor (foto, descrição, composição e quantidade
por tamanho em cada origem). Serve para a Luisa conferir o que acrescenta ou retira. Só lê o banco (REST, GET); nada é gravado.

Bibliotecas (reportlab, pypdf) ficam em joy/_vendor: o container do bot não traz gerador nem leitor de PDF."""
import base64
import datetime
import hashlib
import io
import json
import logging
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

_VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_vendor")
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

import arquivos  # noqa: E402
from config import GROUP_JID, SUPABASE_KEY, SUPABASE_URL  # noqa: E402

logger = logging.getLogger("lolo.romaneio")

HOME = os.environ.get("HERMES_HOME", "/opt/data")
OUT_DIR = os.path.join(HOME, "cache", "relatorios")
IMG_DIR = os.path.join(HOME, "cache", "romaneio_img")
ORDEM = ["PP", "P", "M", "G", "GG", "TU"]
LINHA = re.compile(r"^(\d{5})(\d{3})(PP|P|M|G|GG|TU)$")
NOME_DOC = re.compile(r"romaneio", re.I)
GERADO = re.compile(r"relat[oó]rio|confer[eê]ncia", re.I)


def _plain(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()).strip()


def _brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# --------------------------------------------------------------------------- leitura do romaneio (PDF do showroom)
def ler_romaneio(pdf: bytes) -> Dict[str, Any]:
    """Linhas do romaneio: código de barras = modelo(5) + cor(3) + tamanho; depois descrição, cor, quantidade, preço."""
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    itens: List[Dict[str, Any]] = []
    cab: Dict[str, str] = {}
    texto_total = ""
    for page in reader.pages:
        texto = page.extract_text(extraction_mode="layout") or ""
        texto_total += texto + "\n"
        for linha in texto.splitlines():
            partes = [p.strip() for p in re.split(r"\s{2,}", linha.strip()) if p.strip()]
            if len(partes) >= 6 and re.fullmatch(r"\d{8}(?:PP|P|M|G|GG|TU)", partes[0]) and re.fullmatch(r"\d+", partes[-3]):
                sku = partes[0]
                try:
                    preco = float(partes[-2].replace(".", "").replace(",", "."))
                    qtd = int(partes[-3])
                except ValueError:
                    continue
                itens.append({"sku": sku, "desc": re.sub(r"\s+", " ", " ".join(partes[1:-4])), "cor": partes[-4],
                              "q": qtd, "preco": preco})
    m = re.search(r"Or[çc]amento\s*:\s*(\d+)", texto_total)
    if m:
        cab["orcamento"] = m.group(1)
    m = re.search(r"Data\s*:\s*(\d{2}/\d{2}/\d{4})", texto_total)
    if m:
        cab["data"] = m.group(1)
    m = re.search(r"Processado em\s*:\s*(\d{2}/\d{2}/\d{4})", texto_total)
    if m:
        cab["processado"] = m.group(1)
    m = re.search(r"Total L[ií]quido\s*\|?\s*([\d.]+,\d{2})", texto_total)
    if m:
        cab["total_liquido"] = float(m.group(1).replace(".", "").replace(",", "."))
    return {"itens": itens, "cab": cab}


def localizar_romaneio(busca: str = "") -> Tuple[Optional[str], Dict[str, Any]]:
    """O PDF de romaneio mais recente recebido no grupo (ou o que casar com a busca). Ignora os relatórios já gerados."""
    cands: List[Tuple[float, str, Dict[str, Any]]] = []
    termos = [w for w in _plain(busca).split() if len(w) > 2 and w not in ("romaneio", "relatorio", "fotos")]
    if os.path.isdir(arquivos.INBOX):
        for n in os.listdir(arquivos.INBOX):
            if n.startswith(".") or n.endswith(".json"):
                continue
            meta: Dict[str, Any] = {}
            try:
                meta = json.load(open(os.path.join(arquivos.INBOX, n) + ".json", encoding="utf-8"))
            except (OSError, ValueError):
                pass
            nome = f"{n} {meta.get('original', '')}"
            if n.lower().endswith(".pdf") and NOME_DOC.search(nome) and not GERADO.search(nome):
                cands.append((float(meta.get("ts") or os.path.getmtime(os.path.join(arquivos.INBOX, n))),
                              os.path.join(arquivos.INBOX, n), meta))
    if os.path.isfile(arquivos.INDEX):
        for line in open(arquivos.INDEX, encoding="utf-8"):
            try:
                o = json.loads(line)
            except ValueError:
                continue
            nome = f"{o.get('dest', '')} {o.get('original', '')}"
            if "_Restrito" in nome or not NOME_DOC.search(nome) or GERADO.search(nome) or not nome.lower().rstrip().endswith(".pdf"):
                continue
            p = os.path.join(arquivos.BASE, o["dest"])
            if os.path.isfile(p):
                cands.append((float(o.get("ts") or os.path.getmtime(p)), p, o))
    if termos:
        filtrados = [c for c in cands if all(t in _plain(f"{c[1]} {c[2].get('original', '')} {c[2].get('resumo', '')}") for t in termos)]
        cands = filtrados or cands
    if not cands:
        return None, {}
    cands.sort(key=lambda c: c[0], reverse=True)
    return cands[0][1], cands[0][2]


# --------------------------------------------------------------------------- CentralOps (REST, só leitura)
def _get(schema: str, path: str, timeout: int = 40) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    step = 1000
    while True:
        req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/{path}",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Accept-Profile": schema,
                     "Range-Unit": "items", "Range": f"{len(out)}-{len(out) + step - 1}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            rows = json.loads(resp.read().decode("utf-8"))
        out += rows
        if len(rows) < step:
            return out


def carregar_catalogo() -> Dict[str, Any]:
    produtos = _get("catalog", "products?select=id,reference_code,name,description,composition,care,wholesale_cost,"
                    "categoria:categories(name),variants(id,sku,size,color:colors(code,name)),"
                    "media:product_media(storage_path,position,color:colors(code))&order=reference_code")
    precos: Dict[str, float] = {}
    for r in _get("catalog", "prices?select=product_id,price,valid_from&valid_to=is.null&product_id=not.is.null&order=valid_from.desc"):
        precos.setdefault(r["product_id"], float(r["price"]))
    por_ref: Dict[str, Dict[str, Any]] = {}
    sku_de_variante: Dict[str, str] = {}
    skus = set()
    for p in produtos:
        p["preco"] = precos.get(p["id"])
        por_ref[p["reference_code"]] = p
        for v in p.get("variants") or []:
            skus.add(v["sku"])
            sku_de_variante[v["id"]] = v["sku"]
    return {"produtos": produtos, "por_ref": por_ref, "skus": skus, "sku_de_variante": sku_de_variante}


def carregar_nf_em_revisao(cat: Dict[str, Any]) -> Dict[str, Any]:
    """Itens das notas de entrada ainda em conferência (PENDING_CHECK), por SKU do catálogo."""
    rec = _get("purch", "receipts?select=number,nf_total,document_id,receipt_items(supplier_cprod,qty_nfe,variant_id)&status=eq.PENDING_CHECK")
    nums: Dict[str, str] = {}
    ids = [r["document_id"] for r in rec if r.get("document_id")]
    if ids:
        try:
            for d in _get("fiscal", "documents?select=id,number,issue_at&id=in.(" + ",".join(ids) + ")"):
                nums[d["id"]] = f"NF {d['number']}" + (f" de {d['issue_at'][8:10]}/{d['issue_at'][5:7]}" if d.get("issue_at") else "")
        except (urllib.error.URLError, ValueError, KeyError):
            pass
    qtd: Dict[str, int] = {}
    for r in rec:
        for i in r.get("receipt_items") or []:
            sku = cat["sku_de_variante"].get(i.get("variant_id")) or i.get("supplier_cprod")
            if sku:
                qtd[sku] = qtd.get(sku, 0) + int(round(float(i["qty_nfe"])))
    return {"qtd": qtd, "rotulos": [nums.get(r.get("document_id"), r["number"]) for r in rec], "total": sum(float(r["nf_total"]) for r in rec)}


def carregar_pedidos(cat: Dict[str, Any]) -> Dict[str, Any]:
    """Pedidos de compra lançados e ainda não recebidos (rascunho, aprovado ou parcial): o que falta chegar, por SKU."""
    pos = _get("purch", "purchase_orders?select=number,total,po_items(variant_id,qty_ordered,qty_received,unit_cost)&status=in.(DRAFT,APPROVED,PARTIAL)")
    qtd: Dict[str, int] = {}
    custo: Dict[str, float] = {}
    total = 0.0
    for p in pos:
        for i in p.get("po_items") or []:
            sku = cat["sku_de_variante"].get(i["variant_id"])
            falta = int(round(float(i["qty_ordered"]) - float(i["qty_received"])))
            if sku and falta > 0:
                qtd[sku] = qtd.get(sku, 0) + falta
                custo[sku] = float(i["unit_cost"])
                total += falta * float(i["unit_cost"])
    return {"qtd": qtd, "custo": custo, "numeros": [p["number"] for p in pos], "total": total}


# --------------------------------------------------------------------------- cruzamento
def _nome_cor(v_color: Optional[Dict[str, Any]], fallback: str = "") -> str:
    return re.sub(r"\s*\(\d{3}\)$", "", (v_color or {}).get("name") or fallback or "")


def _resolver(it: Dict[str, Any], cat: Dict[str, Any], notas: List[str]) -> str:
    """SKU final de uma linha do romaneio. Corrige o que o showroom digitou diferente do catálogo (cor trocada, modelo
    inexistente), sempre avisando no relatório; sem correspondência segura, o SKU fica como veio."""
    sku = it["sku"]
    if sku in cat["skus"]:
        return sku
    mo, co, tam = LINHA.match(sku).groups()
    p = cat["por_ref"].get(mo)
    alvo = _plain(it["desc"].split(" - ")[0])
    if p is None:
        # modelo desconhecido: procura o mesmo nome no catálogo que tenha a mesma cor
        for q in cat["produtos"]:
            if _plain(q["name"]) == alvo and any((v.get("color") or {}).get("code") == co for v in q.get("variants") or []):
                notas.append(f"{it['desc']} {it['cor']} {tam}: o código do romaneio ({sku}) tem um modelo que não existe no catálogo. "
                             f"Pelo nome e pela cor, é {q['reference_code']}{co}{tam}; contei assim.")
                return f"{q['reference_code']}{co}{tam}"
        return sku
    # modelo existe, mas a cor do código não: tenta pelo nome da cor escrito no romaneio
    cor_txt = _plain(it["cor"])
    for v in p.get("variants") or []:
        c = v.get("color") or {}
        if _plain(_nome_cor(c)) == cor_txt:
            novo = f"{mo}{c['code']}{tam}"
            if novo in cat["skus"]:
                notas.append(f"{p['name']} {_nome_cor(c)} {tam}: o código do romaneio ({sku}) usa a cor {co}; no catálogo essa cor é {c['code']}. "
                             f"Contei como {novo}.")
                return novo
    return sku


def montar(romaneio: Dict[str, Any], cat: Dict[str, Any], nf: Dict[str, Any], ped: Dict[str, Any]) -> Dict[str, Any]:
    notas: List[str] = []
    dados: Dict[Tuple[str, str], Dict[str, Any]] = {}   # (modelo, cor) -> origens

    def slot(mo: str, co: str) -> Dict[str, Any]:
        return dados.setdefault((mo, co), {"rom": {}, "nf": {}, "po": {}, "cor_rom": "", "desc_rom": "", "preco": None})

    for it in romaneio["itens"]:
        sku = _resolver(it, cat, notas)
        m = LINHA.match(sku)
        if not m:
            continue
        mo, co, tam = m.groups()
        d = slot(mo, co)
        d["rom"][tam] = d["rom"].get(tam, 0) + it["q"]
        d["cor_rom"], d["desc_rom"], d["preco"] = it["cor"], it["desc"], it["preco"]
    for origem, qtds in (("nf", nf["qtd"]), ("po", ped["qtd"])):
        for sku, q in qtds.items():
            m = LINHA.match(sku)
            if m:
                mo, co, tam = m.groups()
                d = slot(mo, co)
                d[origem][tam] = d[origem].get(tam, 0) + q
                if origem == "po" and d["preco"] is None:
                    d["preco_po"] = ped["custo"].get(sku)
    return {"dados": dados, "notas": list(dict.fromkeys(notas))}


# --------------------------------------------------------------------------- fotos
def _foto(url: Optional[str]) -> Optional[bytes]:
    if not url:
        return None
    os.makedirs(IMG_DIR, exist_ok=True)
    f = os.path.join(IMG_DIR, hashlib.sha1(url.encode()).hexdigest() + ".jpg")
    if os.path.isfile(f):
        return open(f, "rb").read()
    try:
        from PIL import Image, ImageOps
        req = urllib.request.Request(url, headers={"User-Agent": "sie-joy-bot"})
        raw = urllib.request.urlopen(req, timeout=30).read()
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        im = ImageOps.fit(im, (330, 440), method=Image.LANCZOS, centering=(0.5, 0.15))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=72)
        open(f, "wb").write(buf.getvalue())
        return buf.getvalue()
    except Exception as exc:  # foto que não baixa não derruba o relatório
        logger.warning("foto indisponível %s: %s", url, exc)
        return None


# --------------------------------------------------------------------------- PDF
def gerar_pdf(romaneio: Dict[str, Any], cat: Dict[str, Any], nf: Dict[str, Any], ped: Dict[str, Any], destino: str) -> Dict[str, Any]:
    from xml.sax.saxutils import escape
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    res = montar(romaneio, cat, nf, ped)
    dados, notas = res["dados"], res["notas"]
    cab = romaneio["cab"]
    tem_nf = bool(nf["qtd"])
    tem_po = bool(ped["qtd"])

    base = ParagraphStyle("b", fontName="Helvetica", fontSize=8.2, leading=10.4, textColor=colors.HexColor("#1d1d1f"))
    pequeno = ParagraphStyle("p", parent=base, fontSize=7.4, leading=9.2, textColor=colors.HexColor("#555555"))
    titulo = ParagraphStyle("t", parent=base, fontName="Helvetica-Bold", fontSize=10.5, leading=12.5)
    h1 = ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=17, leading=20)
    h2 = ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=11, leading=14, spaceBefore=8, spaceAfter=3)
    cel = ParagraphStyle("c", parent=base, fontSize=7.6, leading=9, alignment=1)
    cel_l = ParagraphStyle("cl", parent=cel, alignment=0)

    soma = lambda o: sum(o.values())
    ordenados = sorted(dados.items(), key=lambda kv: (_plain((cat["por_ref"].get(kv[0][0]) or {}).get("name") or kv[1]["desc_rom"] or kv[0][0]), kv[0]))
    cartoes: List[Any] = []
    faltam_tam: List[str] = []
    fora: List[str] = []
    sem_modelo: List[str] = []
    n_rom = sum(soma(d["rom"]) for d in dados.values())
    v_rom = sum(soma(d["rom"]) * (d["preco"] or 0) for d in dados.values())
    modelos = set()

    rom_por_modelo: Dict[str, int] = {}
    for (mo, _c), d in dados.items():
        rom_por_modelo[mo] = rom_por_modelo.get(mo, 0) + soma(d["rom"])

    for (mo, co), d in ordenados:
        p = cat["por_ref"].get(mo)
        modelos.add(mo)
        nome = p["name"] if p else (d["desc_rom"].split(" - ")[0] or mo)
        cor = _nome_cor(next((v.get("color") for v in (p or {}).get("variants") or [] if (v.get("color") or {}).get("code") == co), None), d["cor_rom"] or co)
        preco = d["preco"] if d["preco"] is not None else d.get("preco_po")
        flags: List[str] = []
        if p is None:
            flags.append("Modelo não existe no catálogo")
            sem_modelo.append(f"{nome} {cor} ({mo}{co})")
        if not rom_por_modelo.get(mo):
            flags.append("Não está no romaneio (só NF/pedido)")
            if nome not in fora:
                fora.append(nome)
        if p and not p.get("composition"):
            flags.append("Sem composição no catálogo")
        if p and not p.get("description"):
            flags.append("Sem descrição no catálogo")
        if p and p.get("wholesale_cost") and preco and abs(float(p["wholesale_cost"]) - preco) > 0.01:
            flags.append(f"Atacado no catálogo {_brl(float(p['wholesale_cost']))} difere de {_brl(preco)}")

        tams_cat = {v["size"] for v in (p or {}).get("variants") or [] if (v.get("color") or {}).get("code") == co}
        usados = set(d["rom"]) | set(d["nf"]) | set(d["po"])
        tams = [t for t in ORDEM if t in usados or t in tams_cat]
        faltando = sorted((t for t in usados if f"{mo}{co}{t}" not in cat["skus"]), key=ORDEM.index)
        if faltando:
            faltam_tam.append(f"{nome} {cor} ({mo}{co}): {', '.join(faltando)}")

        def linha(rotulo: str, chave: str) -> List[Any]:
            o = d[chave]
            return [Paragraph(rotulo, cel_l)] + [Paragraph(f"<b>{o[t]}</b>" if o.get(t) else "", cel) for t in tams] + \
                   [Paragraph(f"<b>{soma(o)}</b>" if o else "–", cel)]

        linhas = [[Paragraph("", cel)] + [Paragraph(f"<b>{t}</b>", cel) for t in tams] + [Paragraph("<b>Total</b>", cel)],
                  linha("Romaneio", "rom")]
        if tem_nf:
            linhas.append(linha("NF em revisão", "nf"))
        if tem_po:
            linhas.append(linha("Pedido lançado", "po"))
        linhas.append([Paragraph("Ajuste (Luisa)", cel_l)] + [""] * (len(tams) + 1))
        larg = [26 * mm] + [11 * mm] * len(tams) + [12 * mm]
        t = Table(linhas, colWidths=larg, rowHeights=[None] * (len(linhas) - 1) + [6.5 * mm])
        est = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d4d4d4")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f4f4f4")),
               ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#f4f4f4")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
               ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]
        for j, tm in enumerate(tams, start=1):
            if f"{mo}{co}{tm}" not in cat["skus"]:
                est.append(("BACKGROUND", (j, 1), (j, len(linhas) - 2), colors.HexColor("#fde2e2")))
        t.setStyle(TableStyle(est))

        ref_txt = f"ref. {mo} · cor {co}"
        if d["cor_rom"] and _plain(d["cor_rom"]) != _plain(cor):
            ref_txt += f" · no romaneio: “{escape(d['cor_rom'])}”"
        categoria = ((p or {}).get("categoria") or {}).get("name") or ""
        meta = " · ".join(x for x in [escape(categoria),
                                       f"atacado {_brl(preco)}" if preco else "",
                                       f"venda {_brl(p['preco'])}" if p and p.get("preco") else ""] if x)
        corpo: List[Any] = [Paragraph(f"{escape(nome)} — {escape(cor)} <font size=7 color='#777777'>{ref_txt}</font>", titulo)]
        if meta:
            corpo.append(Paragraph(meta, pequeno))
        if flags:
            corpo.append(Paragraph(" ".join(f"<font backColor='#fff1d6' color='#8a5200' size=7>&nbsp;{escape(f)}&nbsp;</font>" for f in flags), base))
        corpo.append(Paragraph(escape((p or {}).get("description") or "(sem descrição)"), base))
        if p and p.get("composition"):
            corpo.append(Paragraph(f"<b>Composição:</b> {escape(p['composition'])}", base))
        corpo.append(Spacer(1, 2))
        corpo.append(t)
        if faltando:
            corpo.append(Paragraph(f"<font color='#b00020'>Tamanho(s) {', '.join(faltando)} ainda não existem no catálogo: entram como variação "
                                   f"vinculada a este modelo/cor (SKU {mo}{co}+tamanho).</font>", pequeno))

        media = (p or {}).get("media") or []
        url = next((m["storage_path"] for m in sorted(media, key=lambda m: m.get("position") or 0)
                    if (m.get("color") or {}).get("code") == co), None) or (media[0]["storage_path"] if media else None)
        raw = _foto(url) if url else None
        foto: Any = Image(io.BytesIO(raw), width=30 * mm, height=40 * mm) if raw else Paragraph("sem foto", pequeno)
        cartao = Table([[foto, corpo]], colWidths=[33 * mm, 150 * mm])
        cartao.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9d9d9")),
                                    ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                                    ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        cartoes += [KeepTogether([cartao]), Spacer(1, 4)]

    # sobreposições entre origens (mesmo SKU e tamanho)
    ov_nf = sum(min(q, d["rom"].get(t, 0)) for d in dados.values() for t, q in d["nf"].items())
    tot_nf = sum(soma(d["nf"]) for d in dados.values())
    ov_po = sum(min(q, d["rom"].get(t, 0)) for d in dados.values() for t, q in d["po"].items())
    tot_po = sum(soma(d["po"]) for d in dados.values())

    hoje = datetime.datetime.now()
    sub = " × ".join(x for x in [
        f"Orçamento {cab['orcamento']}" + (f" ({cab['processado']})" if cab.get("processado") else "") if cab.get("orcamento") else "Romaneio",
        f"NF em revisão ({', '.join(nf['rotulos'])})" if tem_nf else "",
        f"pedido lançado ({', '.join(ped['numeros'])})" if tem_po else ""] if x)
    def quadro(num: Any, legenda: str) -> List[Any]:
        return [Paragraph(f"<b>{num}</b>", ParagraphStyle("k", parent=base, fontSize=17, leading=21)), Paragraph(legenda, base)]

    kpi = [[quadro(n_rom, f"peças no romaneio<br/>{_brl(v_rom)}")]]
    if tem_nf:
        kpi[0].append(quadro(tot_nf, f"peças na NF em revisão<br/>{_brl(nf['total'])}"))
    if tem_po:
        kpi[0].append(quadro(tot_po, f"peças no pedido lançado<br/>{_brl(ped['total'])}"))
    kpi[0].append(quadro(len(modelos), f"modelos<br/>{len(dados)} cores"))
    kt = Table(kpi, colWidths=[183 * mm / len(kpi[0])] * len(kpi[0]))
    kt.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9d9d9")), ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9d9d9")),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))

    pontos: List[str] = list(notas)
    if cab.get("total_liquido") and abs(cab["total_liquido"] - v_rom) > 0.5:
        pontos.append(f"Conferência do romaneio: as linhas somam {_brl(v_rom)}, mas o total impresso no PDF é {_brl(cab['total_liquido'])}.")
    if tem_nf:
        pontos.append(f"<b>NF × romaneio:</b> {ov_nf} das {tot_nf} peças da NF em revisão também estão no romaneio (mesmo SKU e tamanho). "
                      f"Se o romaneio é o total do orçamento, essas já chegaram — confirmar se contam como saldo.")
    if tem_po:
        pontos.append(f"<b>Pedido × romaneio:</b> {ov_po} das {tot_po} peças do pedido lançado coincidem com SKU/tamanho do romaneio.")
    pontos.append(f"<b>Fora do romaneio</b> (só na NF ou no pedido): {', '.join(escape(x) for x in fora) or 'nenhum'}.")
    if sem_modelo:
        pontos.append("<b>Sem modelo no catálogo</b> (cadastrar no mesmo padrão dos demais): " + "; ".join(escape(x) for x in sem_modelo) + ".")
    pontos.append("<b>Tamanhos que não existem no catálogo</b> (entram como variação vinculada ao modelo e à cor existentes, no mesmo padrão de SKU): "
                  + ("<br/>".join(escape(x) for x in faltam_tam) if faltam_tam else "nenhum") + ".")

    historia: List[Any] = [Paragraph("Romaneio La Sirene · conferência de peças", h1), Paragraph(f"{escape(sub)} · gerado em {hoje:%d/%m/%Y}", pequeno),
                           Spacer(1, 6), kt, Paragraph("Pontos de atenção", h2)]
    for x in pontos:
        historia.append(Paragraph("• " + (x if "<b>" in x else escape(x)), base))
    historia += [Spacer(1, 4), Paragraph("Como ler: cada cartão é uma peça + cor, com a quantidade por tamanho em cada origem. "
                                         "Colunas em vermelho = tamanho que ainda não existe no catálogo. A linha “Ajuste (Luisa)” fica em branco para anotar "
                                         "+/− por tamanho. As origens não se somam automaticamente: o romaneio pode incluir o que já veio na NF.", pequeno),
                 Spacer(1, 8)] + cartoes

    os.makedirs(os.path.dirname(destino), exist_ok=True)
    SimpleDocTemplate(destino, pagesize=A4, leftMargin=10 * mm, rightMargin=10 * mm, topMargin=10 * mm, bottomMargin=10 * mm,
                      title="Romaneio La Sirene - conferência de peças", author="SIÉ JOY").build(historia)
    return {"pecas": n_rom, "valor": v_rom, "modelos": len(modelos), "cores": len(dados), "notas": notas, "faltam_tamanho": faltam_tam,
            "fora": fora, "sem_modelo": sem_modelo, "nf": tot_nf, "po": tot_po, "ov_nf": ov_nf}


# --------------------------------------------------------------------------- WhatsApp
def enviar_documento(path: str, legenda: str, chat_id: str = GROUP_JID) -> Tuple[bool, str]:
    base = os.environ.get("EVOLUTION_API_URL", "").rstrip("/")
    key = os.environ.get("EVOLUTION_API_KEY", "")
    inst = os.environ.get("EVOLUTION_INSTANCE", "")
    if not (base and key and inst):
        return False, "Evolution não configurada no ambiente"
    corpo = {"number": chat_id, "mediatype": "document", "mimetype": "application/pdf", "caption": legenda,
             "fileName": os.path.basename(path), "media": base64.b64encode(open(path, "rb").read()).decode()}
    req = urllib.request.Request(f"{base}/message/sendMedia/{inst}", data=json.dumps(corpo).encode(), method="POST",
                                 headers={"apikey": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return True, str(resp.status)
    except urllib.error.HTTPError as exc:
        return False, f"Evolution {exc.code}: {exc.read().decode('utf-8', 'ignore')[:200]}"
    except Exception as exc:
        return False, str(exc)


def relatorio(busca: str = "", enviar: bool = True, arquivo: Optional[str] = None, chat_id: str = GROUP_JID) -> str:
    """Gera o relatório do romaneio mais recente recebido no grupo (ou de `arquivo`) e, se `enviar`, manda o PDF no grupo."""
    path, meta = (arquivo, {}) if arquivo else localizar_romaneio(busca)
    if not path or not os.path.isfile(path):
        return ("Não achei nenhum PDF de romaneio recebido no grupo. Peça para a Luisa enviar o PDF do romaneio no grupo e "
                "depois pedir o relatório com fotos.")
    rom = ler_romaneio(open(path, "rb").read())
    if not rom["itens"]:
        return f"Li o arquivo {os.path.basename(path)}, mas não encontrei linhas de peças (código de barras, descrição, cor, quantidade). Não parece um romaneio da La Sirene."
    cat = carregar_catalogo()
    nf = carregar_nf_em_revisao(cat)
    ped = carregar_pedidos(cat)
    destino = os.path.join(OUT_DIR, f"relatorio-romaneio-{datetime.datetime.now():%Y-%m-%d-%H%M}.pdf")
    r = gerar_pdf(rom, cat, nf, ped, destino)
    resumo = (f"Relatório gerado a partir de {meta.get('original') or os.path.basename(path)}: {r['pecas']} peças, {_brl(r['valor'])}, "
              f"{r['modelos']} modelos, {r['cores']} cores.")
    if r["faltam_tamanho"]:
        resumo += " Tamanhos que faltam no catálogo: " + "; ".join(r["faltam_tamanho"]) + "."
    if r["sem_modelo"]:
        resumo += " Sem modelo no catálogo: " + "; ".join(r["sem_modelo"]) + "."
    if r["notas"]:
        resumo += " Correções automáticas: " + " ".join(r["notas"])
    if not enviar:
        return resumo + f" PDF salvo em {destino} (não enviado)."
    legenda = (f"Relatório do romaneio com fotos — {r['pecas']} peças, {_brl(r['valor'])}, {r['modelos']} modelos / {r['cores']} cores. "
               f"Cada cartão tem a foto, a descrição e a quantidade por tamanho (romaneio, NF em revisão e pedido), com uma linha em branco para o ajuste.")
    ok, det = enviar_documento(destino, legenda, chat_id)
    return resumo + (" PDF enviado no grupo." if ok else f" Não consegui enviar o PDF ({det}); ele ficou salvo em {destino}.")
