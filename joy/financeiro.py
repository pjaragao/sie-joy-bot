"""Módulo financeiro da loja SIÉ JOY — lançamento e gestão de reembolsos (CentralOps / fin.reimbursements)."""
import datetime
import json
import logging
import os
import re
import sqlite3
import unicodedata
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Tuple

from config import (
    CHART_ACCOUNTS,
    COST_CENTERS,
    LEGAL_ENTITY_ID,
    ORG_ID,
    PAULO_JR_MEMBER_ID,
    PAULO_JR_NAME,
    PAULO_JR_PARTY_ID,
    STORE_ID,
    SUPABASE_KEY,
    SUPABASE_URL,
)

logger = logging.getLogger("sie_joy.financeiro")

LOCAL_DB = os.path.join(os.environ.get("HERMES_HOME", "/opt/data"), "reembolsos_joy.db")
CAPEX_ORCADO = 30000.0
DOC_KINDS = ("NFE", "NFCE", "NFSE", "CUPOM", "RECIBO", "OUTRO")
_NS = uuid.UUID("5f0e6c1e-6a0b-4d52-9a39-0f6b1f4d2a11")  # ids determinísticos dos itens => retry idempotente


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(LOCAL_DB), exist_ok=True)
    conn = sqlite3.connect(LOCAL_DB, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _init_local_db() -> None:
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reembolsos (
                id TEXT PRIMARY KEY,
                number TEXT NOT NULL,
                spent_on TEXT NOT NULL,
                description TEXT NOT NULL,
                amount REAL NOT NULL,
                due_date TEXT NOT NULL,
                cost_center_name TEXT NOT NULL,
                cost_center_id TEXT NOT NULL,
                chart_account_name TEXT NOT NULL,
                chart_account_id TEXT NOT NULL,
                chart_account_code TEXT NOT NULL,
                supplier_name TEXT,
                supplier_doc TEXT,
                document_kind TEXT NOT NULL,
                document_number TEXT,
                justification TEXT,
                beneficiary TEXT NOT NULL,
                status TEXT NOT NULL,
                synced_supabase INTEGER DEFAULT 0,
                sync_error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(reembolsos)")}
        for col, ddl in (("justification", "TEXT"), ("sync_error", "TEXT"), ("supplier_party_id", "TEXT")):
            if col not in cols:
                conn.execute(f"ALTER TABLE reembolsos ADD COLUMN {col} {ddl}")


_init_local_db()


# --------------------------------------------------------------------------- regras
def calcular_data_reembolso(data_base: Optional[datetime.date] = None) -> str:
    """Dia 10 do mês seguinte à data-base (padrão: hoje, a data do lançamento)."""
    d = data_base or datetime.date.today()
    ano, mes = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return f"{ano:04d}-{mes:02d}-10"


def _has(text: str, *patterns: str) -> bool:
    return any(re.search(p, text) for p in patterns)


# (código, nome, padrões) — ordem = prioridade. Contas novas (7.2.10+, 1.2.1.04) têm o id resolvido no CentralOps.
_RULES: List[Tuple[str, str, Tuple[str, ...]]] = [
    ("7.2.10", "Taxas, licenças e registros",
     (r"\bdare\b", r"\btaxa\b", r"\balvar[áa]\b", r"\bjunta\b", r"\bjucesc\b", r"\bbombeiros?\b", r"\bcertid[ãa]o\b",
      r"\binscri[çc][ãa]o\b", r"\biptu\b", r"\blicen[çc]a de funcionamento\b", r"\bvigil[âa]ncia sanit[áa]ria\b")),
    ("7.2.11", "Serviços jurídicos e despachante",
     (r"\badvogad[oa]\b", r"\bjur[ií]dic", r"\bcart[óo]rio\b", r"\bdespachante\b", r"\bprocuraç[ãa]o\b")),
    ("7.2.12", "Despesas de implantação (pré-operacionais)",
     (r"\bconstitui[çc][ãa]o\b", r"\babertura de empresa\b", r"\bregistro da empresa\b")),
    ("1.2.1.04", "Expositores, manequins e cabides",
     (r"\bcabides?\b", r"\bmanequins?\b", r"\bbustos?\b", r"\bexpositor(?:es)?\b", r"\bvitrine\b")),
    ("1.2.1.02", "Móveis, araras e armários",
     (r"\bararas?\b", r"\bm[óo]ve(?:l|is)\b", r"\bmarcenaria\b", r"\bbalc[ãa]o\b", r"\bestantes?\b", r"\bmesas?\b",
      r"\bprateleiras?\b", r"\bnichos?\b", r"\bgaveteiro\b", r"\barm[áa]rio\b")),
    ("1.2.1.01", "Instalações e benfeitorias",
     (r"\bletreiro\b", r"\breforma\b", r"\biluminaç[ãa]o\b", r"\bspots?\b", r"\bpintura\b", r"\badesivos?\b",
      r"\bcomunicaç[ãa]o visual\b", r"\bfachada\b", r"\binstalaç[ãa]o\b", r"\bel[ée]trica\b", r"\bpainel\b", r"\blogo\b")),
    ("1.2.1.03", "Equipamentos (POS, tablets, leitores)",
     (r"\btablets?\b", r"\bipad\b", r"\bleitor\b", r"\bc[óo]digo de barras\b", r"\bpos\b", r"\bmaquininha\b",
      r"\bcomputador\b", r"\bnotebook\b", r"\bimpressora\b", r"\broteador\b")),
    ("6.1.02", "Embalagens, sacolas e tags aromáticas",
     (r"\bsacolas?\b", r"\bembalagens?\b", r"\baroma\b", r"\bdifusor\b", r"\btags?\b", r"\betiquetas?\b",
      r"\bpapel de seda\b", r"\becobags?\b")),
    ("7.3.01", "Eventos e Drops",
     (r"\bevento\b", r"\bdj\b", r"\bcoquetel\b", r"\bbuffet\b", r"\bflor(?:es)?\b", r"\bfot[óo]grafo\b", r"\bdrop\b")),
    ("7.2.05", "Honorários contábeis", (r"\bcontador\b", r"\bcontabilidade\b", r"\bhonor[áa]rios?\b", r"\bcrc\b")),
    ("7.2.06", "Software e assinaturas",
     (r"\bsoftware\b", r"\bsistema\b", r"\blicen[çc]a\b", r"\bnfc-?e\b", r"\bcertificado\b", r"\bemissor\b",
      r"\bassinatura\b")),
    ("7.2.13", "Telefonia e dados móveis",
     (r"\bchip\b", r"\blinha (?:de )?celular\b", r"\bplano (?:de )?(?:celular|dados)\b", r"\bdados m[óo]veis\b",
      r"\bvivo\b", r"\btelefon")),
    ("7.2.07", "Energia, internet e limpeza",
     (r"\benergia\b", r"\bluz\b", r"\binternet\b", r"\bwi-?fi\b", r"\blimpeza\b", r"\bfaxina\b")),
    ("7.2.14", "Material de escritório, uso e consumo",
     (r"\bpapelaria\b", r"\bescrit[óo]rio\b", r"\btoner\b", r"\bcaneta\b", r"\bmaterial de consumo\b")),
    ("7.2.15", "Manutenção e reparos", (r"\bconserto\b", r"\breparo\b", r"\bmanuten[çc][ãa]o\b")),
    ("7.2.16", "Seguros", (r"\bseguro\b",)),
    ("7.3.02", "Mídia paga (Meta Ads)",
     (r"\btr[áa]fego\b", r"\ban[úu]ncios?\b", r"\bmeta ads\b", r"\binstagram\b", r"\binfluenc")),
]
_ACCT_CACHE: Dict[str, Tuple[str, str, str]] = {}


def classificar_codigo(descricao: str) -> Optional[str]:
    """Código contábil sugerido pelo texto, ou None se não houver correspondência clara."""
    d = (descricao or "").lower()
    for code, _name, pats in _RULES:
        if _has(d, *pats):
            return code
    return None


def _acct_by_code(code: str) -> Optional[Tuple[str, str, str]]:
    for v in CHART_ACCOUNTS.values():
        if v[1] == code:
            return v
    if code in _ACCT_CACHE:
        return _ACCT_CACHE[code]
    try:
        st, rows = _rest("GET", f"chart_accounts?select=id,code,name&code=eq.{urllib.parse.quote(code)}&limit=1")
        if st == 200 and rows:
            _ACCT_CACHE[code] = (rows[0]["id"], rows[0]["code"], rows[0]["name"])
            return _ACCT_CACHE[code]
    except Exception as exc:
        logger.warning("conta %s não resolvida no CentralOps: %s", code, exc)
    return None


def mapear_conta_contabil(descricao: str) -> Tuple[str, str, str]:
    """(id, código, nome). Sem correspondência (ou conta indisponível) => 7.2.99 'a classificar'."""
    code = classificar_codigo(descricao)
    return (code and _acct_by_code(code)) or CHART_ACCOUNTS["DESPESAS_DIVERSAS"]


def mapear_centro_custo(descricao: str) -> Tuple[str, str]:
    d = (descricao or "").lower()
    if _has(d, r"\bevento\b", r"\bcoquetel\b", r"\bdj\b", r"\bdrop\b"):
        return COST_CENTERS["EVENTOS"]
    if _has(d, r"\bsoftware\b", r"\blicen[çc]a\b", r"\bsistema\b", r"\bservidor\b", r"\bhospedagem\b", r"\bassinatura\b"):
        return COST_CENTERS["TI"]
    if _has(d, r"\bcontador\b", r"\bcontabilidade\b", r"\bhonor[áa]rios?\b"):
        return COST_CENTERS["ADM_FIN"]
    return COST_CENTERS["LOJA"]


def _resolve_override(table: Dict[str, tuple], nome: Optional[str], by_code: bool = False) -> Optional[tuple]:
    """Aceita chave (ex.: 'EVENTOS') ou código contábil (ex.: '7.3.01') informado explicitamente."""
    if not nome:
        return None
    n = nome.strip().upper()
    if n in table:
        return table[n]
    for v in table.values():
        if by_code and len(v) > 1 and str(v[1]).upper() == n:
            return v
    return None


# --------------------------------------------------------------------------- supabase
def _headers(profile_write: bool = True, schema: str = "fin") -> Dict[str, str]:
    h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json",
         "Accept-Profile": schema}
    if profile_write:
        h["Content-Profile"] = schema
    return h


def _rest(method: str, path: str, body: Any = None, prefer: str = "return=minimal", timeout: int = 8,
          schema: str = "fin") -> Tuple[int, Any]:
    headers = _headers(profile_write=method != "GET", schema=schema)
    headers["Prefer"] = prefer
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{SUPABASE_URL}/rest/v1/{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:300]


def _next_number() -> str:
    """Número do reembolso pelo contador do próprio CentralOps (core.next_number: REE-AAAA-NNNN), o mesmo da tela.
    Se o banco estiver fora do ar, cai para o maior número conhecido + 1 (mesmo formato)."""
    try:
        st, body = _rest("POST", "rpc/next_number", {"p_org": ORG_ID, "p_doc_type": "REE"}, prefer="return=representation",
                         schema="core")
        if st == 200 and isinstance(body, str) and re.fullmatch(r"REE-\d{4}-\d{4,6}", body):
            return body
        logger.warning("core.next_number respondeu %s: %s", st, body)
    except Exception as exc:
        logger.warning("core.next_number indisponível: %s", exc)
    ano = datetime.date.today().year
    prefix = f"REE-{ano}-"
    best = 0
    with _conn() as conn:
        for r in conn.execute("SELECT number FROM reembolsos WHERE number LIKE ?", (prefix + "%",)):
            best = max(best, int(r["number"].rsplit("-", 1)[-1] or 0))
    return f"{prefix}{best + 1:04d}"


def _sync_row(row: sqlite3.Row) -> Tuple[bool, str]:
    """Envia reembolso + item ao CentralOps de forma idempotente (ids estáveis, ignore-duplicates)."""
    rem = {
        "id": row["id"], "org_id": ORG_ID, "number": row["number"], "legal_entity_id": LEGAL_ENTITY_ID,
        "store_id": STORE_ID, "party_id": PAULO_JR_PARTY_ID, "requester_member_id": PAULO_JR_MEMBER_ID,
        "purpose": row["description"], "status": row["status"], "total": row["amount"], "due_date": row["due_date"],
    }
    kind = row["document_kind"] if row["document_kind"] in DOC_KINDS else "OUTRO"
    item = {
        "id": str(uuid.uuid5(_NS, row["id"] + ":1")), "org_id": ORG_ID, "reimbursement_id": row["id"], "position": 1,
        "spent_on": row["spent_on"], "description": row["description"],
        "supplier_name": row["supplier_name"] if row["supplier_name"] != "Não informado" else None,
        "supplier_doc": row["supplier_doc"] or None, "supplier_party_id": row["supplier_party_id"] or None,
        "document_kind": kind,
        "document_number": row["document_number"] or None, "amount": row["amount"],
        "chart_account_id": row["chart_account_id"], "cost_center_id": row["cost_center_id"],
        "no_document_reason": None if row["document_number"] else (row["justification"] or "Comprovante aguardando anexo"),
    }
    ign = "resolution=ignore-duplicates,return=minimal"
    try:
        st, body = _rest("POST", "reimbursements?on_conflict=id", rem, prefer=ign)
        if st >= 300:
            return False, f"reimbursements HTTP {st}: {body}"
        st, body = _rest("POST", "reimbursement_items?on_conflict=id", item, prefer=ign)
        if st >= 300:
            return False, f"reimbursement_items HTTP {st}: {body}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def _mark_sync(rem_id: str, ok: bool, err: str) -> None:
    with _conn() as conn:
        conn.execute("UPDATE reembolsos SET synced_supabase=?, sync_error=? WHERE id=?", (1 if ok else 0, err or None, rem_id))


def sincronizar_pendentes() -> str:
    """Reenvia ao CentralOps os reembolsos que ficaram só no livro local."""
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM reembolsos WHERE synced_supabase=0 ORDER BY created_at").fetchall()
    if not rows:
        return "Nenhum reembolso pendente de sincronização."
    ok_n, fails = 0, []
    for r in rows:
        ok, err = _sync_row(r)
        _mark_sync(r["id"], ok, err)
        if ok:
            ok_n += 1
        else:
            fails.append(f"{r['number']}: {err}")
            logger.error("sync %s falhou: %s", r["number"], err)
    msg = f"Sincronizados: {ok_n}/{len(rows)}."
    return msg + ("\nFalhas:\n" + "\n".join(fails) if fails else "")



# --------------------------------------------------------------------------- fornecedor no cadastro (crm.parties)
# O CentralOps (fin.save_reimbursement) NÃO cadastra o fornecedor sozinho: só aceita supplier_party_id de quem já existe.
# Então é o bot quem procura pelo CNPJ (ou cadastra) e passa o id.
_CONHECIDOS = {"mercado livre": "03007331000141", "sefaz": "82951310000156", "sef sc": "82951310000156",
               "dare": "82951310000156", "vivo": "02558157000162"}


def _plain(t: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()).strip()


def _cnpj_valido(d: str) -> bool:
    if len(d) != 14 or len(set(d)) == 1:
        return False
    for n in (12, 13):
        pesos = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2][-n:] if n == 12 else [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        soma = sum(int(c) * p for c, p in zip(d[:n], pesos))
        dv = 11 - soma % 11
        if int(d[n]) != (0 if dv >= 10 else dv):
            return False
    return True


def resolver_fornecedor(nome: Optional[str], doc: Optional[str]) -> Tuple[Optional[str], str]:
    """-> (party_id ou None, texto curto do que aconteceu). Procura no cadastro (por CNPJ; sem CNPJ, por nome exato) e,
    se for empresa com CNPJ válido que ainda não existe, cadastra como fornecedor. Pessoa física (CPF) não é cadastrada
    automaticamente."""
    nome = (nome or "").strip()
    digits = re.sub(r"\D", "", doc or "")
    if not digits:
        n = _plain(nome)
        digits = next((v for k, v in _CONHECIDOS.items() if k in n), "")
    try:
        if len(digits) == 11:
            return None, "CPF: cadastre a pessoa no CentralOps (não crio pessoa física sozinho)"
        if len(digits) == 14:
            if not _cnpj_valido(digits):
                return None, "CNPJ inválido"
            st, rows = _rest("GET", f"parties?select=id,display_name&cnpj=eq.{digits}&merged_into_id=is.null&limit=1", schema="crm")
            if st == 200 and rows:
                return rows[0]["id"], f"vinculado a “{rows[0]['display_name']}”"
            if len(nome) < 2:
                return None, "sem nome para cadastrar"
            nome_ok = nome.title() if nome.isupper() else nome
            st, body = _rest("POST", "parties", {"org_id": ORG_ID, "kind": "COMPANY", "display_name": nome_ok, "legal_name": nome,
                                                 "cnpj": digits, "source": "REEMBOLSO", "tags": ["fornecedor"]},
                             prefer="return=representation", schema="crm")
            if st >= 300 or not isinstance(body, list) or not body:
                return None, f"não consegui cadastrar o fornecedor (HTTP {st})"
            pid = body[0]["id"]
            _rest("POST", "party_roles", {"party_id": pid, "org_id": ORG_ID, "role": "SUPPLIER"}, schema="crm")
            return pid, f"cadastrado agora como fornecedor “{nome_ok}”"
        if nome:
            st, rows = _rest("GET", "parties?select=id,display_name&merged_into_id=is.null&limit=1&display_name=ilike." +
                             urllib.parse.quote(nome), schema="crm")
            if st == 200 and rows:
                return rows[0]["id"], f"vinculado a “{rows[0]['display_name']}”"
    except Exception as exc:
        logger.warning("fornecedor %s: %s", nome, exc)
        return None, "cadastro indisponível agora"
    return None, "sem CNPJ: não cadastrei (passe o CNPJ para vincular)"


def vincular_fornecedores() -> str:
    """Liga ao cadastro os itens de reembolso que ainda estão sem supplier_party_id (nome/CNPJ já digitados)."""
    st, items = _rest("GET", "reimbursement_items?select=id,supplier_name,supplier_doc,reimbursement_id&supplier_party_id=is.null")
    if st != 200 or not isinstance(items, list):
        return f"Não consegui ler os itens (HTTP {st})."
    cache: Dict[Tuple[str, str], Tuple[Optional[str], str]] = {}
    linhas = []
    for it in items:
        nome, doc = (it.get("supplier_name") or ""), (it.get("supplier_doc") or "")
        if not nome and not doc:
            continue
        key = (_plain(nome), re.sub(r"\D", "", doc))
        if key not in cache:
            cache[key] = resolver_fornecedor(nome, doc)
        pid, msg = cache[key]
        if pid:
            _rest("PATCH", f"reimbursement_items?id=eq.{it['id']}", {"supplier_party_id": pid})
            with _conn() as conn:
                conn.execute("UPDATE reembolsos SET supplier_party_id=? WHERE id=?", (pid, it["reimbursement_id"]))
        linhas.append(f"• {nome or doc}: {msg}")
    return ("*🗂️ Fornecedores no cadastro*\n" + "\n".join(sorted(set(linhas)))) if linhas else "Nenhum item sem fornecedor ligado."

# --------------------------------------------------------------------------- operações
def lancar_reembolso(
    descricao: str,
    valor: float,
    data_gasto: Optional[str] = None,
    fornecedor: Optional[str] = None,
    cnpj_cpf: Optional[str] = None,
    tipo_doc: str = "RECIBO",
    numero_doc: Optional[str] = None,
    justificativa: Optional[str] = None,
    conta_contabil: Optional[str] = None,
    centro_custo: Optional[str] = None,
    forcar: bool = False,
) -> str:
    """Lança despesa paga por Paulo Jr; reembolso sempre no dia 10 do mês seguinte ao lançamento."""
    if not valor or valor <= 0:
        return "Erro: o valor da despesa deve ser maior que zero."
    if not descricao or len(descricao.strip()) < 3:
        return "Erro: forneça uma descrição clara da despesa."
    descricao = descricao.strip()

    hoje = datetime.date.today()
    aviso_data = ""
    if data_gasto:
        try:
            data_gasto_dt = datetime.date.fromisoformat(data_gasto[:10])
        except ValueError:
            return f"Erro: data do gasto inválida ('{data_gasto}'). Use AAAA-MM-DD ou omita para hoje."
        if data_gasto_dt > hoje:
            return f"Erro: a data do gasto ({data_gasto_dt:%d/%m/%Y}) está no futuro — a despesa já foi paga?"
    else:
        data_gasto_dt = hoje
        aviso_data = "\n⚠️ _Data do gasto não informada: usei hoje._"
    data_gasto_str = data_gasto_dt.isoformat()

    tipo = (tipo_doc or "RECIBO").upper()
    if tipo not in DOC_KINDS:
        tipo = "OUTRO"

    if not forcar:
        with _conn() as conn:
            dup = conn.execute(
                "SELECT number FROM reembolsos WHERE ABS(amount-?)<0.005 AND spent_on=? AND LOWER(description)=LOWER(?)",
                (valor, data_gasto_str, descricao),
            ).fetchone()
        if dup:
            return (f"⚠️ Parece duplicado de `{dup['number']}` (mesmo valor, data e descrição). "
                    f"Nada foi lançado. Se for outra despesa, repita com forcar=true.")

    acct = (_resolve_override(CHART_ACCOUNTS, conta_contabil, by_code=True)
            or (_acct_by_code(conta_contabil) if conta_contabil else None))
    if not acct:
        if conta_contabil:
            return f"Conta '{conta_contabil}' não existe no plano de contas. Informe um código válido (ex.: 7.2.10)."
        acct = mapear_conta_contabil(descricao)
        if acct[1] == "7.2.99":  # sem correspondência clara: perguntar antes de lançar
            return ("Não lancei: não sei em qual conta classificar \"" + descricao + "\". Diga o tipo (ex.: taxa/licença "
                    "7.2.10, jurídico 7.2.11, implantação 7.2.12, telefonia 7.2.13, escritório 7.2.14, manutenção 7.2.15, "
                    "seguro 7.2.16, expositor 1.2.1.04, móvel/arara 1.2.1.02, instalação 1.2.1.01, equipamento 1.2.1.03, "
                    "embalagem 6.1.02) e eu lanço.")
    cc = _resolve_override(COST_CENTERS, centro_custo) or mapear_centro_custo(descricao)
    acct_id, acct_code, acct_name = acct
    cc_id, cc_name = cc
    due_date = calcular_data_reembolso(hoje)

    dig = re.sub(r"\D", "", cnpj_cpf or "")
    if len(dig) == 14 and not _cnpj_valido(dig):
        return f"Não lancei: o CNPJ {cnpj_cpf} é inválido (dígitos verificadores). Confira o número."
    party_id, forn_msg = resolver_fornecedor(fornecedor, cnpj_cpf)

    rem_id = str(uuid.uuid4())
    number = _next_number()
    with _conn() as conn:
        conn.execute("""
            INSERT INTO reembolsos (id, number, spent_on, description, amount, due_date, cost_center_name,
                cost_center_id, chart_account_name, chart_account_id, chart_account_code, supplier_name,
                supplier_doc, document_kind, document_number, justification, beneficiary, status, synced_supabase,
                supplier_party_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'SUBMITTED', 0, ?)
        """, (rem_id, number, data_gasto_str, descricao, valor, due_date, cc_name, cc_id, acct_name, acct_id,
              acct_code, fornecedor or "Não informado", cnpj_cpf or "", tipo, numero_doc or "", justificativa,
              PAULO_JR_NAME, party_id))

    with _conn() as conn:
        row = conn.execute("SELECT * FROM reembolsos WHERE id=?", (rem_id,)).fetchone()
    ok, err = _sync_row(row)
    _mark_sync(rem_id, ok, err)
    if not ok:
        logger.error("sync %s falhou: %s", number, err)

    sync_msg = ("✅ Registrado e integrado no CentralOps" if ok else
                "⚠️ Registrado no livro local; *CentralOps não confirmou* (reenvio automático às 17h)")
    return (
        f"*{sync_msg}*\n\n"
        f"• *Número:* `{number}`\n"
        f"• *Despesa:* {descricao}\n"
        f"• *Valor:* R$ {valor:,.2f}\n"
        f"• *Data do gasto:* {data_gasto_dt:%d/%m/%Y}\n"
        f"• *Beneficiário:* {PAULO_JR_NAME}\n"
        f"• *Reembolso em:* *{datetime.date.fromisoformat(due_date):%d/%m/%Y}*\n"
        f"• *Centro de custo:* {cc_name}\n"
        f"• *Conta:* `{acct_code}` — {acct_name}\n"
        f"• *Fornecedor:* {fornecedor or 'Pendente'}" + (f" — 🗂️ {forn_msg}" if fornecedor or cnpj_cpf else "") + "\n"
        f"• *Documento:* {tipo}{' ' + numero_doc if numero_doc else ' (sem número — comprovante pendente)'}"
        f"{aviso_data}"
    )


def _listar_remoto(limit: int) -> Optional[str]:
    try:
        st, rows = _rest("GET", f"reimbursements?select=number,total,due_date,status,purpose&order=number.desc&limit={limit}")
    except Exception:
        return None
    if st != 200 or not isinstance(rows, list):
        return None
    if not rows:
        return "Nenhum reembolso registrado até o momento."
    ativos = [r for r in rows if r["status"] != "CANCELLED"]
    lines = ["*📋 REEMBOLSOS (CentralOps)*"]
    for r in rows:
        due = datetime.date.fromisoformat(r["due_date"]).strftime("%d/%m/%Y") if r.get("due_date") else "—"
        lines.append(f"• `{r['number']}` {r['status']} {_brl(r['total'])} — {r['purpose']}\n  _reembolso {due}_")
    lines.append(f"\n*Total ativo:* {_brl(sum(float(r['total']) for r in ativos))} em {len(ativos)} lançamento(s)")
    return "\n".join(lines)


def listar_reembolsos(limit: int = 10) -> str:
    limit = max(1, min(int(limit or 10), 50))
    remoto = _listar_remoto(limit)
    if remoto:
        return remoto
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM reembolsos ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        tot_all, qtd_all = conn.execute("SELECT COALESCE(SUM(amount),0), COUNT(*) FROM reembolsos").fetchone()
    if not rows:
        return "Nenhum reembolso registrado até o momento."
    lines = ["*📋 REEMBOLSOS (conta Paulo Jr)*"]
    for r in rows:
        due = datetime.date.fromisoformat(r["due_date"]).strftime("%d/%m/%Y")
        icon = "🟢" if r["synced_supabase"] else "🔴"
        lines.append(f"• `{r['number']}` {icon} R$ {r['amount']:,.2f} — {r['description']}\n"
                     f"  _reembolso {due} · {r['cost_center_name']}_")
    lines.append(f"\n*Total geral:* R$ {tot_all:,.2f} em {qtd_all} lançamento(s)  (🟢 no CentralOps · 🔴 pendente)")
    return "\n".join(lines)


def resumo_capex() -> str:
    """Capex (R$ 30k) vs realizado — só contas de investimento/implantação; opex fica separado."""
    capex_codes = (CHART_ACCOUNTS["INSTALACOES"][1], CHART_ACCOUNTS["MOVEIS_ARARAS"][1], CHART_ACCOUNTS["EQUIPAMENTOS"][1],
                   CHART_ACCOUNTS["EMBALAGENS_AROMA"][1])
    with _conn() as conn:
        marks = ",".join("?" * len(capex_codes))
        cap, cap_n = conn.execute(
            f"SELECT COALESCE(SUM(amount),0), COUNT(*) FROM reembolsos WHERE chart_account_code IN ({marks})", capex_codes
        ).fetchone()
        oth, oth_n = conn.execute(
            f"SELECT COALESCE(SUM(amount),0), COUNT(*) FROM reembolsos WHERE chart_account_code NOT IN ({marks})", capex_codes
        ).fetchone()
    pct = cap / CAPEX_ORCADO * 100
    return (
        "*📊 INVESTIMENTO INICIAL (CAPEX JOY)*\n\n"
        f"• *Orçado:* R$ {CAPEX_ORCADO:,.2f}\n"
        f"• *Realizado (capex):* R$ {cap:,.2f} ({pct:.1f}%) · {cap_n} item(ns)\n"
        f"• *Saldo:* R$ {CAPEX_ORCADO - cap:,.2f}\n"
        f"• *Outras despesas reembolsáveis (opex/eventos/a classificar):* R$ {oth:,.2f} · {oth_n} item(ns)\n\n"
        "_Obs.: o orçado inclui R$ 4.000 de reserva de giro (INV08), que não é gasto de capex._"
    )


# --------------------------------------------------------------------------- edição / cancelamento
EDITAVEIS = ("DRAFT", "SUBMITTED", "REJECTED")  # APPROVED/PAID já viraram título a pagar: não mexer por aqui


def _num(numero: str) -> str:
    n = (numero or "").strip().upper()
    if re.fullmatch(r"\d{1,4}", n):
        n = f"REE-{datetime.date.today().year}-{int(n):04d}"
    return n


def _find_account(ref: str) -> Optional[Tuple[str, str, str]]:
    hit = _resolve_override(CHART_ACCOUNTS, ref, by_code=True)
    if hit:
        return hit
    st, rows = _rest("GET", f"chart_accounts?select=id,code,name&code=eq.{urllib.parse.quote(ref.strip())}&limit=1")
    if st == 200 and rows:
        return rows[0]["id"], rows[0]["code"], rows[0]["name"]
    return None


def _find_cost_center(ref: str) -> Optional[Tuple[str, str]]:
    hit = _resolve_override(COST_CENTERS, ref)
    if hit:
        return hit
    st, rows = _rest("GET", f"cost_centers?select=id,code,name&code=eq.{urllib.parse.quote(ref.strip().upper())}&limit=1",
                     schema="core")
    if st == 200 and rows:
        return rows[0]["id"], f"{rows[0]['name']} ({rows[0]['code']})"
    return None


def _fetch(numero: str) -> Tuple[Optional[dict], List[dict]]:
    st, rows = _rest("GET", f"reimbursements?select=*&number=eq.{urllib.parse.quote(numero)}&limit=1")
    if st != 200 or not rows:
        return None, []
    rem = rows[0]
    st, items = _rest("GET", f"reimbursement_items?select=*&reimbursement_id=eq.{rem['id']}&order=position")
    return rem, (items if st == 200 and isinstance(items, list) else [])


def _brl(v: Any) -> str:
    return f"R$ {float(v):,.2f}"


def editar_reembolso(numero: str, valor: Optional[float] = None, descricao: Optional[str] = None,
                     data_gasto: Optional[str] = None, fornecedor: Optional[str] = None, cnpj_cpf: Optional[str] = None,
                     tipo_doc: Optional[str] = None, numero_doc: Optional[str] = None,
                     justificativa: Optional[str] = None, conta_contabil: Optional[str] = None,
                     centro_custo: Optional[str] = None, data_reembolso: Optional[str] = None,
                     item: Optional[int] = None) -> str:
    """Edita um reembolso já lançado (valor, descrição, data, fornecedor, documento, conta, centro de custo, data do
    reembolso). Direto no CentralOps; só enquanto não aprovado/pago."""
    numero = _num(numero)
    rem, items = _fetch(numero)
    if not rem:
        return f"Reembolso {numero} não encontrado no CentralOps."
    if rem["status"] not in EDITAVEIS:
        why = "já foi aprovado e virou conta a pagar" if rem["status"] in ("APPROVED", "PAID") else "está cancelado"
        return (f"Não posso editar {numero}: {why} ({rem['status']}). "
                f"Só edito DRAFT/SUBMITTED/REJECTED. Para ajustar, é preciso reabrir pelo CentralOps.")
    if not items:
        return f"{numero} não tem itens para editar."
    item_fields = any(v is not None for v in (valor, data_gasto, fornecedor, cnpj_cpf, tipo_doc, numero_doc,
                                              justificativa, conta_contabil, centro_custo))
    if len(items) > 1 and item_fields and item is None:
        pos = ", ".join(f"{i['position']}: {i['description']} ({_brl(i['amount'])})" for i in items)
        return f"{numero} tem {len(items)} itens ({pos}). Informe qual item (parâmetro item)."
    target = next((i for i in items if i["position"] == item), None) if item is not None else items[0]
    if target is None:
        return f"{numero} não tem o item {item}."

    changes: List[str] = []
    ipatch: Dict[str, Any] = {}
    rpatch: Dict[str, Any] = {}

    if valor is not None:
        if valor <= 0:
            return "Erro: o valor deve ser maior que zero (para anular, use cancelar_reembolso)."
        if round(float(valor), 2) != round(float(target["amount"]), 2):
            changes.append(f"valor: {_brl(target['amount'])} → {_brl(valor)}")
            ipatch["amount"] = round(float(valor), 2)
    if descricao and descricao.strip() != target["description"]:
        changes.append(f"descrição: {target['description']} → {descricao.strip()}")
        ipatch["description"] = descricao.strip()
        if len(items) == 1:
            rpatch["purpose"] = descricao.strip()
    if data_gasto:
        try:
            d = datetime.date.fromisoformat(data_gasto[:10])
        except ValueError:
            return f"Erro: data do gasto inválida ('{data_gasto}'). Use AAAA-MM-DD."
        if d > datetime.date.today():
            return "Erro: a data do gasto está no futuro."
        if d.isoformat() != target["spent_on"]:
            changes.append(f"data do gasto: {target['spent_on']} → {d.isoformat()}")
            ipatch["spent_on"] = d.isoformat()
    if fornecedor is not None and fornecedor != (target.get("supplier_name") or ""):
        changes.append(f"fornecedor: {target.get('supplier_name') or '—'} → {fornecedor}")
        ipatch["supplier_name"] = fornecedor
    if cnpj_cpf is not None:
        dig = re.sub(r"\D", "", cnpj_cpf)
        if dig and len(dig) not in (11, 14):
            return "Erro: CNPJ/CPF deve ter 14 ou 11 dígitos."
        changes.append(f"CNPJ/CPF: {target.get('supplier_doc') or '—'} → {dig or '—'}")
        ipatch["supplier_doc"] = dig or None
        if len(dig) == 14 and not _cnpj_valido(dig):
            return f"Erro: o CNPJ {cnpj_cpf} é inválido (dígitos verificadores)."
    if fornecedor is not None or cnpj_cpf is not None:   # mudou o favorecido: refaz a ligação com o cadastro
        nome_f = fornecedor if fornecedor is not None else (target.get("supplier_name") or "")
        doc_f = re.sub(r"\D", "", cnpj_cpf) if cnpj_cpf is not None else (target.get("supplier_doc") or "")
        pid, msg_f = resolver_fornecedor(nome_f, doc_f)
        if pid and pid != target.get("supplier_party_id"):
            ipatch["supplier_party_id"] = pid
            changes.append(f"cadastro do fornecedor: {msg_f}")
    if tipo_doc:
        k = tipo_doc.upper()
        if k not in DOC_KINDS:
            return f"Erro: tipo de documento deve ser um de {', '.join(DOC_KINDS)}."
        changes.append(f"documento: {target['document_kind']} → {k}")
        ipatch["document_kind"] = k
    if numero_doc is not None:
        changes.append(f"nº do documento: {target.get('document_number') or '—'} → {numero_doc or '—'}")
        ipatch["document_number"] = numero_doc or None
        if numero_doc:
            ipatch["no_document_reason"] = None
    if justificativa is not None:
        ipatch["no_document_reason"] = justificativa or None
        changes.append("justificativa atualizada")
    if conta_contabil:
        acc = _find_account(conta_contabil)
        if not acc:
            return f"Conta '{conta_contabil}' não existe no plano de contas (use o código, ex.: 7.2.10)."
        changes.append(f"conta: → {acc[1]} {acc[2]}")
        ipatch["chart_account_id"] = acc[0]
    if centro_custo:
        cc = _find_cost_center(centro_custo)
        if not cc:
            return f"Centro de custo '{centro_custo}' não encontrado (ex.: LOJA, EVENTOS, ADM-TI)."
        changes.append(f"centro de custo: → {cc[1]}")
        ipatch["cost_center_id"] = cc[0]
    if data_reembolso:
        try:
            dr = datetime.date.fromisoformat(data_reembolso[:10])
        except ValueError:
            return "Erro: data do reembolso inválida. Use AAAA-MM-DD."
        if dr.isoformat() != rem.get("due_date"):
            changes.append(f"reembolso em: {rem.get('due_date') or '—'} → {dr.isoformat()}")
            rpatch["due_date"] = dr.isoformat()

    if not changes:
        return f"{numero}: nada a alterar (os valores informados já são os atuais)."

    if ipatch:
        st, body = _rest("PATCH", f"reimbursement_items?id=eq.{target['id']}", ipatch, prefer="return=representation")
        if st >= 300:
            return f"Falha ao editar o item de {numero}: HTTP {st} {body}"
    new_total = sum(float(ipatch.get("amount", i["amount"])) if i["id"] == target["id"] else float(i["amount"])
                    for i in items)
    if round(new_total, 2) != round(float(rem["total"]), 2):
        rpatch["total"] = round(new_total, 2)
    if rpatch:
        st, body = _rest("PATCH", f"reimbursements?id=eq.{rem['id']}", rpatch, prefer="return=representation")
        if st >= 300:
            return f"Item alterado, mas falhou ao atualizar o cabeçalho de {numero}: HTTP {st} {body}"

    # espelha no livro local, se o lançamento nasceu por aqui
    colmap = {"amount": "amount", "description": "description", "spent_on": "spent_on", "supplier_name": "supplier_name",
              "supplier_doc": "supplier_doc", "document_kind": "document_kind", "document_number": "document_number",
              "no_document_reason": "justification", "cost_center_id": "cost_center_id",
              "chart_account_id": "chart_account_id", "supplier_party_id": "supplier_party_id"}
    local = {colmap[k]: v for k, v in ipatch.items() if k in colmap}
    local.update({k: v for k, v in rpatch.items() if k == "due_date"})
    if "chart_account_id" in ipatch:
        a = _find_account(conta_contabil)
        local.update(chart_account_name=a[2], chart_account_code=a[1])
    if "cost_center_id" in ipatch:
        local["cost_center_name"] = _find_cost_center(centro_custo)[1]
    if local:
        with _conn() as conn:
            conn.execute("UPDATE reembolsos SET " + ", ".join(f"{k}=?" for k in local) + " WHERE number=?",
                         (*local.values(), numero))
    logger.info("editar_reembolso %s: %s", numero, "; ".join(changes))
    return (f"*✏️ {numero} atualizado no CentralOps* (status {rem['status']})\n"
            + "\n".join(f"• {c}" for c in changes)
            + f"\n• *Total do reembolso:* {_brl(new_total)}")


def cancelar_reembolso(numero: str, motivo: Optional[str] = None) -> str:
    """Cancela (status CANCELLED) um reembolso ainda não aprovado/pago."""
    numero = _num(numero)
    rem, _ = _fetch(numero)
    if not rem:
        return f"Reembolso {numero} não encontrado."
    if rem["status"] not in EDITAVEIS:
        return f"Não posso cancelar {numero}: está {rem['status']}."
    st, body = _rest("PATCH", f"reimbursements?id=eq.{rem['id']}",
                     {"status": "CANCELLED", "reject_reason": (motivo or "Cancelado")[:300]}, prefer="return=minimal")
    if st >= 300:
        return f"Falha ao cancelar {numero}: HTTP {st} {body}"
    with _conn() as conn:
        conn.execute("UPDATE reembolsos SET status='CANCELLED' WHERE number=?", (numero,))
    return f"*🚫 {numero} cancelado* ({_brl(rem['total'])}). Motivo: {motivo or '—'}"


def resumo_reembolsos_abertos() -> Dict[str, Any]:
    """Reembolsos ainda não pagos/cancelados (CentralOps; cai para o livro local se offline)."""
    try:
        st, rows = _rest("GET", "reimbursements?select=total,due_date,status&status=in.(DRAFT,SUBMITTED,APPROVED)")
        if st == 200 and isinstance(rows, list):
            total = sum(float(r["total"]) for r in rows)
            due = sorted({r["due_date"] for r in rows if r.get("due_date")})
            return {"qtd": len(rows), "total": total,
                    "vencimento": datetime.date.fromisoformat(due[0]).strftime("%d/%m") if due else ""}
    except Exception:
        pass
    with _conn() as conn:
        qtd, total = conn.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM reembolsos "
                                  "WHERE status NOT IN ('PAID','CANCELLED')").fetchone()
    return {"qtd": qtd, "total": total, "vencimento": ""}
