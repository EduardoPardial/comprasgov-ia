import re
import unicodedata
from urllib.parse import quote_plus

import pandas as pd
import requests
import streamlit as st
from google import genai


st.set_page_config(page_title="Compras.gov + PNCP", layout="wide")

st.title("Compras.gov + PNCP")
st.caption("Busca compras/preços reais no Compras.gov e gera link de pesquisa no PNCP.")


texto = st.text_input(
    "Digite o objeto ou serviço",
    placeholder="Ex: borracharia, pneus, água mineral, sistema ISSQN"
)

col1, col2, col3 = st.columns(3)

with col1:
    buscar_material = st.checkbox("Buscar materiais", value=True)

with col2:
    buscar_servico = st.checkbox("Buscar serviços", value=True)

with col3:
    limite = st.slider("Resultados por termo", 5, 30, 10)

modo_diagnostico = st.checkbox("Modo diagnóstico", value=False)


PALAVRAS_IGNORADAS = {
    "de", "da", "do", "das", "dos", "para", "por", "com", "sem",
    "em", "no", "na", "nos", "nas", "a", "o", "as", "os",
    "e", "ou", "ao", "aos", "um", "uma"
}


def remover_acentos(txt):
    txt = unicodedata.normalize("NFKD", str(txt))
    return "".join(c for c in txt if not unicodedata.combining(c))


def limpar_texto(txt):
    txt = remover_acentos(txt).lower()
    txt = re.sub(r"[^a-z0-9\s]", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def gerar_buscas_simples(objeto):
    limpo = limpar_texto(objeto)

    palavras = [
        p for p in limpo.split()
        if p not in PALAVRAS_IGNORADAS and len(p) > 2
    ]

    buscas = [limpo]

    for palavra in palavras:
        buscas.append(palavra)

    unicas = []
    for busca in buscas:
        if busca and busca not in unicas:
            unicas.append(busca)

    return unicas[:3]


def gerar_termos_gemini(objeto):
    try:
        client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

        prompt = f"""
Você é especialista em compras públicas brasileiras.

Gere até 3 termos curtos para pesquisar compras públicas relacionadas ao objeto abaixo.

Objeto:
{objeto}

Regras:
- No máximo 3 termos.
- Use termos comuns em editais e descrições de itens.
- Não use termos genéricos demais.
- Retorne apenas um termo por linha.
"""

        resposta = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=prompt
        )

        termos = resposta.text.splitlines()
        termos = [
            t.strip("-•0123456789. ").strip()
            for t in termos
            if t.strip()
        ]

        unicos = []
        for termo in termos:
            if termo and termo not in unicos:
                unicos.append(termo)

        if not unicos:
            return gerar_buscas_simples(objeto)

        return unicos[:3]

    except Exception as e:
        st.warning(f"Gemini falhou. Usando busca simples. Erro: {e}")
        return gerar_buscas_simples(objeto)


def consultar_api(url, params):
    try:
        resposta = requests.get(url, params=params, timeout=20)

        if resposta.status_code != 200:
            return []

        dados = resposta.json()

        if isinstance(dados, list):
            return dados

        for chave in ["resultado", "data", "content", "items"]:
            if chave in dados and isinstance(dados[chave], list):
                return dados[chave]

        return []

    except Exception:
        return []


def texto_item(item):
    return " ".join(str(v) for v in item.values() if v)


def pontuar(texto_resultado, busca_original, termos):
    base = limpar_texto(texto_resultado)
    busca = limpar_texto(busca_original)

    pontos = 0

    if busca and busca in base:
        pontos += 30

    for termo in termos:
        termo_limpo = limpar_texto(termo)

        if termo_limpo and termo_limpo in base:
            pontos += 20

        for palavra in termo_limpo.split():
            if palavra not in PALAVRAS_IGNORADAS and len(palavra) > 2:
                if palavra in base:
                    pontos += 5

    return pontos


def extrair_campo(item, opcoes):
    for campo in opcoes:
        valor = item.get(campo)
        if valor not in [None, ""]:
            return valor
    return ""


def link_busca_pncp(objeto, orgao=""):
    termo = f"{objeto} {orgao}".strip()
    return f"https://pncp.gov.br/app/editais?q={quote_plus(termo)}"


def link_comprasgov(item):
    id_compra = extrair_campo(item, ["idCompra", "compraId", "id"])

    if id_compra:
        return f"https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra?compra={id_compra}"

    return "https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras"


def buscar_material_precos(termos):
    url = "https://dadosabertos.compras.gov.br/modulo-pesquisa-preco/1_consultarMaterial"
    resultados = []

    for termo in termos:
        params = {
            "pagina": 1,
            "tamanhoPagina": limite,
            "descricao": termo
        }

        itens = consultar_api(url, params)

        if modo_diagnostico and itens:
            st.subheader("Diagnóstico - primeiro material bruto")
            st.json(itens[0])
            st.stop()

        for item in itens:
            texto_completo = texto_item(item)
            pontos = pontuar(texto_completo, texto, [termo])

            if pontos <= 0:
                continue

            descricao = extrair_campo(item, [
                "descricaoItem",
                "descricaoMaterial",
                "descricao",
                "nomeItem"
            ]) or texto_completo

            orgao = extrair_campo(item, [
                "nomeOrgao",
                "orgao",
                "nomeUasg",
                "nomeUnidade"
            ])

            resultados.append({
                "Pontuação": pontos,
                "Tipo": "Material",
                "Descrição": descricao,
                "Órgão": orgao,
                "UASG": extrair_campo(item, ["codigoUasg", "uasg", "codigoUnidade"]),
                "Compra": extrair_campo(item, ["numeroCompra", "numeroPregao", "compra", "numero"]),
                "Ano": extrair_campo(item, ["anoCompra", "anoPregao", "ano"]),
                "Valor": extrair_campo(item, ["valorUnitario", "valorHomologado", "valor", "precoUnitario"]),
                "Data": extrair_campo(item, ["dataResultado", "dataCompra", "dataHomologacao", "data"]),
                "Termo usado": termo,
                "Link Compras.gov": link_comprasgov(item),
                "Link busca PNCP": link_busca_pncp(descricao, orgao)
            })

    return resultados


def buscar_servico_precos(termos):
    url = "https://dadosabertos.compras.gov.br/modulo-pesquisa-preco/3_consultarServico"
    resultados = []

    for termo in termos:
        params = {
            "pagina": 1,
            "tamanhoPagina": limite,
            "descricao": termo
        }

        itens = consultar_api(url, params)

        if modo_diagnostico and itens:
            st.subheader("Diagnóstico - primeiro serviço bruto")
            st.json(itens[0])
            st.stop()

        for item in itens:
            texto_completo = texto_item(item)
            pontos = pontuar(texto_completo, texto, [termo])

            if pontos <= 0:
                continue

            descricao = extrair_campo(item, [
                "descricaoServico",
                "descricaoItem",
                "descricao",
                "nomeServico"
            ]) or texto_completo

            orgao = extrair_campo(item, [
                "nomeOrgao",
                "orgao",
                "nomeUasg",
                "nomeUnidade"
            ])

            resultados.append({
                "Pontuação": pontos,
                "Tipo": "Serviço",
                "Descrição": descricao,
                "Órgão": orgao,
                "UASG": extrair_campo(item, ["codigoUasg", "uasg", "codigoUnidade"]),
                "Compra": extrair_campo(item, ["numeroCompra", "numeroPregao", "compra", "numero"]),
                "Ano": extrair_campo(item, ["anoCompra", "anoPregao", "ano"]),
                "Valor": extrair_campo(item, ["valorUnitario", "valorHomologado", "valor", "precoUnitario"]),
                "Data": extrair_campo(item, ["dataResultado", "dataCompra", "dataHomologacao", "data"]),
                "Termo usado": termo,
                "Link Compras.gov": link_comprasgov(item),
                "Link busca PNCP": link_busca_pncp(descricao, orgao)
            })

    return resultados


if st.button("Buscar"):
    if not texto.strip():
        st.warning("Digite algo para buscar.")
        st.stop()

    with st.spinner("Gerando até 3 termos..."):
        termos = gerar_termos_gemini(texto)

    st.subheader("Termos usados")
    st.write(termos)

    resultados = []

    with st.spinner("Consultando compras/preços reais no Compras.gov..."):
        if buscar_material:
            resultados.extend(buscar_material_precos(termos))

        if buscar_servico:
            resultados.extend(buscar_servico_precos(termos))

    if not resultados:
        st.warning("Nenhum resultado relevante encontrado.")
        st.stop()

    df = pd.DataFrame(resultados)
    df = df.drop_duplicates(subset=["Tipo", "Descrição", "Órgão", "Compra", "Ano"])
    df = df.sort_values(by="Pontuação", ascending=False)

    st.subheader("Resultados encontrados")

    for _, row in df.iterrows():
        st.markdown(f"""
### {row['Descrição']}

**Pontuação:** {row['Pontuação']}  
**Tipo:** {row['Tipo']}  
**Órgão:** {row['Órgão']}  
**UASG:** {row['UASG']}  
**Compra:** {row['Compra']}  
**Ano:** {row['Ano']}  
**Valor:** {row['Valor']}  
**Data:** {row['Data']}  
**Termo usado:** {row['Termo usado']}  

<a href="{row['Link Compras.gov']}" target="_blank">Abrir Compras.gov</a>
&nbsp; | &nbsp;
<a href="{row['Link busca PNCP']}" target="_blank">Buscar no PNCP</a>

---
""", unsafe_allow_html=True)

    csv = df.to_csv(index=False).encode("utf-8-sig")

    st.download_button(
        "Baixar CSV",
        csv,
        "comprasgov_processos.csv",
        "text/csv"
    )
