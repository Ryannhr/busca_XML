"""
Constantes e configurações para o cliente SEFAZ DF-e.
"""

VALID_UF_CODES = frozenset([
    "11", "12", "13", "14", "15", "16", "17", "21", "22", "23", "24",
    "25", "26", "27", "28", "29", "31", "32", "33", "35", "41", "42",
    "43", "50", "51", "52", "53",
])

# Limites horários para consultas pontuais
DFE_POINT_QUERY_LIMITS = {
    "normal_per_hour": 15,
    "safety_ceiling_per_hour": 18,
    "absolute_per_hour": 20,
}

# Endpoints oficiais do Web Service NFeDistribuicaoDFe (Ambiente Nacional / SVRS)
SEFAZ_ENDPOINTS = {
    "PRODUCAO": "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx",
    "HOMOLOGACAO": "https://hom1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx",
}

SOAP_ACTION = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe/nfeDistDFeInteresse"

# Mapeamento de Siglas de UF para Código IBGE
UF_IBGE_MAP = {
    "RO": "11", "AC": "12", "AM": "13", "RR": "14", "PA": "15", "AP": "16", "TO": "17",
    "MA": "21", "PI": "22", "CE": "23", "RN": "24", "PB": "25", "PE": "26", "AL": "27",
    "SE": "28", "BA": "29", "MG": "31", "ES": "32", "RJ": "33", "SP": "35", "PR": "41",
    "SC": "42", "RS": "43", "MS": "50", "MT": "51", "GO": "52", "DF": "53",
}


