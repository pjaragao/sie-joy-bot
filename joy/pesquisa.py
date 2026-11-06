"""Módulo de pesquisa na web e sugestão de produtos/fornecedores para a loja SIÉ JOY."""
import json
import os
import urllib.parse
import logging
import urllib.request

logger = logging.getLogger("sie_joy.pesquisa")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")

def _agy(kind: str, query: str, profundo: bool) -> str:
    token = os.environ.get("AGY_SHIM_TOKEN", "")
    if not token:
        return ""
    body = {"kind": kind, "query": query[:800], "reasoning_effort": "high" if profundo else "low"}
    req = urllib.request.Request(os.environ.get("AGY_SHIM_URL", "http://172.26.0.1:8787").rstrip("/") + "/v1/task",
                                 data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {token}",
                                                                         "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=170) as resp:
        return (json.loads(resp.read()).get("text") or "").strip()


def web(consulta: str, profundo: bool = False, titulo: str = "") -> str:
    """Pesquisa geral na web (notícias, fatos, esporte, como fazer...), sem o viés de compras do pesquisar_web."""
    consulta = str(consulta or "").strip()
    if not consulta:
        return "Informe o que pesquisar."
    try:
        import datetime
        hoje = datetime.date.today()
        text = _agy("web", f"[Hoje é {hoje:%d/%m/%Y}; priorize informações atuais, de {hoje.year}.] {consulta}", profundo)
        if text:
            return f"*🔎 {titulo or consulta[:80]}*\n\n{text}"
    except Exception as exc:
        logger.warning("pesquisa web via AGY falhou: %s", type(exc).__name__)
    if GEMINI_API_KEY:
        try:
            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
            payload = {"contents": [{"parts": [{"text": f"Pesquise na web e responda em português, curto, com links: {consulta}"}]}],
                       "tools": [{"googleSearch": {}}]}
            req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY})
            with urllib.request.urlopen(req, timeout=60) as resp:
                parts = (json.loads(resp.read()).get("candidates") or [{}])[0].get("content", {}).get("parts", [])
            text = "\n".join(p.get("text", "") for p in parts if p.get("text")).strip()
            if text:
                return f"*🔎 {titulo or consulta[:80]}*\n\n{text}"
        except Exception as exc:
            logger.warning("pesquisa web via Gemini falhou: %s", type(exc).__name__)
    return "Não consegui pesquisar na web agora (AGY e Gemini indisponíveis). Tente de novo em alguns minutos."


def pesquisar_web(termo: str, foco: str = "produtos", profundo: bool = False) -> str:
    """Pesquisa na web por fornecedores, referências, equipamentos ou produtos usando Gemini Grounding."""
    if not termo:
        return "Informe o termo que deseja pesquisar."
    
    prompt = (
        f"Você é o pesquisador e especialista em compras da loja de luxo athleisure SIÉ Wear. "
        f"Pesquise na web em português sobre: '{termo}'. Foco: {foco}. "
        f"Priorize anúncios do Mercado Livre com preço e o link DIRETO do anúncio (nunca link de busca/lista; se não achar, diga que não localizou). Traga opções práticas, marcas/fornecedores confiáveis no Brasil, especificações recomendadas "
        f"e estimativas de custo/faixa de preço. Formate em tópicos limpos e executivos para WhatsApp."
    )

    # 1) AGY (shim /v1/task) — padrão; 2) Gemini com grounding como reserva
    token = os.environ.get("AGY_SHIM_TOKEN", "")
    if token:
        try:
            body = {"kind": "search", "query": f"{termo}. Foco: {foco}. Loja de luxo acessível athleisure SIÉ Wear (Florianópolis).",
                    "reasoning_effort": "high" if profundo else "low"}
            req = urllib.request.Request(os.environ.get("AGY_SHIM_URL", "http://172.26.0.1:8787").rstrip("/") + "/v1/task",
                                         data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {token}",
                                                                                 "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=170) as resp:
                text = (json.loads(resp.read()).get("text") or "").strip()
            if text:
                return f"*🔍 Pesquisa: {termo}*\n\n{text}"
        except Exception as exc:
            logger.warning("pesquisa via AGY falhou (%s): %s", termo, type(exc).__name__)

    if GEMINI_API_KEY:
        try:
            model = os.environ.get("PESQUISA_MODEL_HIGH", "gemini-2.5-pro") if profundo else "gemini-2.5-flash"
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "tools": [{"googleSearch": {}}]
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY})
            with urllib.request.urlopen(req, timeout=90 if profundo else 30) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
            
            candidates = res_json.get("candidates") or []
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                text = "\n".join(p.get("text", "") for p in parts if p.get("text"))
                if text:
                    return f"*🔍 Resultados da Pesquisa Web: {termo}*\n\n{text.strip()}"
        except Exception as exc:
            logger.error("pesquisa web falhou (%s): %s", termo, type(exc).__name__)

    # Fallback simplificado
    return f"Não foi possível obter dados ao vivo da web no momento para '{termo}'. Tente reformular o termo ou pesquisar um produto específico."
