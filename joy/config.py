"""Configurações e constantes da loja SIÉ JOY e do sistema CentralOps."""
import os

ORG_ID = "00000000-0000-4000-8000-000000000001"
LEGAL_ENTITY_ID = "f9502c0b-4a3e-44ee-90cc-54613ed8c496"
STORE_ID = "2c953e07-205c-4e75-8383-1a67875e67b9"
STORE_CODE = "SIE-JOY-ESTEVES"
STORE_NAME = "SIÉ JOY ESTEVES JÚNIOR"

# Membros e Pessoas
PAULO_JR_PARTY_ID = "ddff9682-1564-4f5e-b425-b472370a99dc"
PAULO_JR_MEMBER_ID = "cc110b5a-00c5-4f23-b895-5e8dfcf5a9d6"
PAULO_JR_NAME = "Paulo José Aragão Júnior"

LUISA_PARTY_ID = "9d62e748-5cce-436b-ba1d-a70546b5dd5a"
LUISA_MEMBER_ID = "e158bce3-f7e1-4810-8226-d46b8a6984e6"
LUISA_NAME = "Luisa Felix de Carvalho Aragão"

# WhatsApp Group
GROUP_JID = "120363000000000000@g.us"
GROUP_NAME = "LPO - SIÉ JOY"

# Centros de Custo Padrão
COST_CENTERS = {
    "LOJA": ("21cc8918-6463-46f6-9561-c345e700c401", "Loja SIÉ JOY ESTEVES JÚNIOR (LOJA-SIE-JOY-ESTEVES)"),
    "EVENTOS": ("3817807f-69d1-463f-a69c-a6c706fc870d", "Eventos e ativações (MKT-EVENTOS)"),
    "TI": ("dbe3d625-5009-4ec5-9f4c-78e0a71d09d0", "Sistemas e tecnologia (ADM-TI)"),
    "MKT_MIDIA": ("68e52ae5-1c8e-4e31-9bd9-4760d5d36c0d", "Mídia paga e influenciadores (MKT-MIDIA)"),
    "COLECAO": ("8a09738a-caa0-4d46-aef9-dc2c6c79ec5a", "Compras e coleção (PROD-COLECAO)"),
    "ADM_FIN": ("49e822ff-167e-461a-bd55-32724ad699a1", "Financeiro e contabilidade (ADM-FIN)"),
}
DEFAULT_COST_CENTER_ID = COST_CENTERS["LOJA"][0]

# Contas Contábeis Frequentes
CHART_ACCOUNTS = {
    "INSTALACOES": ("0db80d5d-2040-42d6-a313-d2ab05e09e15", "1.2.1.01", "Instalações e benfeitorias"),
    "MOVEIS_ARARAS": ("824a7ce2-be5d-4ca2-bae8-8e9e8785a910", "1.2.1.02", "Móveis, araras e armários"),
    "EQUIPAMENTOS": ("8c673d29-4ab1-43b4-840d-6578a326e21e", "1.2.1.03", "Equipamentos (POS, tablets, leitores)"),
    "EMBALAGENS_AROMA": ("1df9a656-6410-4642-b9af-0fb24776c719", "6.1.02", "Embalagens, sacolas e tags aromáticas"),
    "CONTADOR": ("4cbab02c-1740-4651-86ca-9e4e6caccaf5", "7.2.05", "Honorários contábeis"),
    "SOFTWARE": ("10495be1-f127-4d50-a52c-34b6e8cd2f61", "7.2.06", "Software e assinaturas"),
    "ENERGIA_LIMPEZA": ("599106a6-9c90-4b55-a0d1-719b4462d258", "7.2.07", "Energia, internet e limpeza"),
    "EVENTOS": ("85490139-0177-42b0-9ee6-738e1dbf9023", "7.3.01", "Eventos e Drops"),
    "MIDIA": ("050c02da-cee3-4bde-bd87-2479e30127ec", "7.3.02", "Mídia paga (Meta Ads)"),
    "DESPESAS_DIVERSAS": ("51ac5bc6-b57f-4d31-9ef9-20eb41523ad4", "7.2.99", "Despesas a classificar"),
}

# Database & Storage
SUPABASE_URL = os.environ.get("SUPABASE_URL", "http://supabase-kong:8000")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")  # sem default: senha nunca fica no código
