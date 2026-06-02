import re
import unicodedata

import pandas as pd
import requests
import streamlit as st
from google import genai


st.set_page_config(page_title="Busca Compras.gov IA", layout="wide")

st.title("Busca Compras.gov IA")
st.caption("Busca CATMAT/CATSER e tenta localizar compras/preços relacionados.")


texto = st.text_input(
    "Digite o objeto ou serviço",
    placeholder="Ex: pneu 175/70 R14, água mineral, serviço de borracharia"
)

col1, col2, col3 = st.columns(3)

with col1:
    buscar_catmat = st.checkbox("Buscar CATMAT / Material", value=True)

with col2:
    buscar_catser = st.checkbox("Buscar CATSER / Serviço", value=True)

with col3:
    limite = st.slider("Resultados por termo", 5, 30, 10)

buscar_precos = st.checkbox("Buscar processos/preços após encontrar códigos", value=True)
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
Você é especialista em compras públicas brasileiras, CATMAT e CATSER.

Gere até 3 termos de busca para encontrar o item abaixo no catálogo Compras.gov.

Objeto:
{objeto}

Regras:
- No máximo 3 termos.
- Termos curtos.
- Priorize palavras usadas em catálogo público.
- Se for material, use termos de material.
- Se for serviço, use termos de serviço.
- Não explique nada.
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


def pontuar(texto_resultado, busca_original, termos):
    base = limpar_texto(texto_resultado)
    busca = limpar_texto(busca_original)

    pontos = 0

    if busca and busca in base:
        pontos += 20

    for termo in termos:
        termo_limpo = limpar_texto(termo)

        if termo_limpo and termo_limpo in base:
            pontos += 15

        for palavra in termo_limpo.split():
            if palavra not in PALAVRAS_IGNORADAS and len(palavra) > 2:
                if palavra in base:
                    pontos += 3

    return pontos


def consultar_api(url, params):
    try:
        resposta = requests.get(url, params=params, timeout=20)

        if resposta.status_code != 200:
            return []

        dados = resposta.json()

        if isinstance(dados, list):
            return dados

        if "resultado" in dados:
            return dados.get("resultado", [])

        if "data" in dados:
            return dados.get("data", [])

        if "content" in dados:
            return dados.get("content", [])

        return []

    except Exception:
        return []


def texto_item(item):
    return " ".join(str(v) for v in item.values() if v)


def buscar_catmat(termos):
    url = "https://dadosabertos.compras.gov.br/modulo-material/4_consultarItemMaterial"

    resultados = []

    for termo in termos:
        params = {
            "pagina": 1,
            "tamanhoPagina": limite,
            "descricao": termo
        }

        itens = consultar_api(url, params)

        for item in itens:
            texto_completo = texto_item(item)
            pontos = pontuar(texto_completo, texto, [termo])

            if pontos <= 0:
                continue

            codigo = (
                item.get("codigoItem")
                or item.get("codigoMaterial")
                or item.get("codigo")
                or item.get("id")
            )

            descricao = (
                item.get("descricaoItem")
                or item.get("nomeItem")
                or item.get("descricao")
                or texto_completo
            )

            resultados.append({
                "Pontuação": pontos,
                "Tipo": "CATMAT",
                "Código": codigo,
                "Descrição": descricao,
                "Status": item.get("statusItem") or item.get("status") or "",
                "Termo usado": termo,
                "_bruto": item
            })

    return resultados


def buscar_catser(termos):
    url = "https://dadosabertos.compras.gov.br/modulo-servico/6_consultarItemServico"

    resultados = []

    for termo in termos:
        params = {
            "pagina": 1,
            "tamanhoPagina": limite,
            "descricao": termo
        }

        itens = consultar_api(url, params)

        for item in itens:
            texto_completo = texto_item(item)
            pontos = pontuar(texto_completo, texto, [termo])

            if pontos <= 0:
                continue

            codigo = (
                item.get("codigoServico")
                or item.get("codigoItem")
                or item.get("codigo")
                or item.get("id")
            )

            descricao = (
                item.get("nomeServico")
                or item.get("descricaoServico")
                or item.get("descricao")
                or texto_completo
            )

            resultados.append({
                "Pontuação": pontos,
                "Tipo": "CATSER",
                "Código": codigo,
                "Descrição": descricao,
                "Status": item.get("statusServico") or item.get("status") or "",
                "Termo usado": termo,
                "_bruto": item
            })

    return resultados


def buscar_precos_material(codigo_item):
    url = "https://dadosabertos.compras.gov.br/modulo-pesquisa-preco/1_consultarMaterial"

    params = {
        "pagina": 1,
        "tamanhoPagina": limite,
        "codigoItemCatalogo": codigo_item
    }

    return consultar_api(url, params)


def buscar_precos_servico(codigo_servico):
    url = "https://dadosabertos.compras.gov.br/modulo-pesquisa-preco/3_consultarServico"

    params = {
        "pagina": 1,
        "tamanhoPagina": limite,
        "codigoItemCatalogo": codigo_servico
    }

    return consultar_api(url, params)


def montar_link_generico(item):
    id_compra = item.get("idCompra", "")

    if id_compra:
        return f"https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/compras/acompanhamento-compra?compra={id_compra}"

    return "https://www.gov.br/compras/pt-br"


def extrair_campo(item, opcoes):
    for campo in opcoes:
        valor = item.get(campo)
        if valor not in [None, ""]:
            return valor
    return ""


def montar_resultados_processos(codigos_encontrados):
    processos = []

    for cod in codigos_encontrados:
        tipo = cod["Tipo"]
        codigo = cod["Código"]
        descricao_base = cod["Descrição"]

        if not codigo:
            continue

        if tipo == "CATMAT":
            precos = buscar_precos_material(codigo)
        else:
            precos = buscar_precos_servico(codigo)

        if modo_diagnostico and precos:
            st.subheader("Diagnóstico - primeiro preço/processo bruto retornado")
            st.write(f"Tipo: {tipo} | Código: {codigo}")
            st.json(precos[0])
            st.stop()

        for preco in precos:
            processos.append({
                "Tipo": tipo,
                "Código": codigo,
                "Descrição base": descricao_base,
                "Órgão": extrair_campo(preco, ["nomeOrgao", "orgao", "nomeUasg", "nomeUnidade"]),
                "UASG": extrair_campo(preco, ["codigoUasg", "uasg", "codigoUnidade"]),
                "Compra": extrair_campo(preco, ["numeroCompra", "numeroPregao", "compra", "numero"]),
                "Ano": extrair_campo(preco, ["anoCompra", "anoPregao", "ano"]),
                "Valor": extrair_campo(preco, ["valorUnitario", "valorHomologado", "valor", "precoUnitario"]),
                "Data": extrair_campo(preco, ["dataResultado", "dataCompra", "dataHomologacao", "data"]),
                "Link": montar_link_generico(preco)
            })

    return processos


if st.button("Buscar"):
    if not texto.strip():
        st.warning("Digite algo para buscar.")
        st.stop()

    with st.spinner("Gerando até 3 termos..."):
        termos = gerar_termos_gemini(texto)

    st.subheader("Termos usados")
    st.write(termos)

    resultados_catalogo = []

    with st.spinner("Consultando CATMAT/CATSER no Compras.gov..."):
        if buscar_catmat:
            resultados_catalogo.extend(buscar_catmat(termos))

        if buscar_catser:
            resultados_catalogo.extend(buscar_catser(termos))

    if not resultados_catalogo:
        st.warning("Nenhum CATMAT/CATSER relevante encontrado.")
        st.stop()

    df_catalogo = pd.DataFrame([
        {k: v for k, v in r.items() if k != "_bruto"}
        for r in resultados_catalogo
    ])

    df_catalogo = df_catalogo.drop_duplicates(subset=["Tipo", "Código", "Descrição"])
    df_catalogo = df_catalogo.sort_values(by="Pontuação", ascending=False)

    st.subheader("Códigos encontrados")
    st.dataframe(df_catalogo, use_container_width=True, hide_index=True)

    if not buscar_precos:
        csv = df_catalogo.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "Baixar códigos em CSV",
            csv,
            "comprasgov_codigos.csv",
            "text/csv"
        )
        st.stop()

    codigos_para_pesquisar = df_catalogo.head(5).to_dict("records")

    with st.spinner("Buscando processos/preços relacionados aos códigos encontrados..."):
        processos = montar_resultados_processos(codigos_para_pesquisar)

    if not processos:
        st.warning(
            "Códigos encontrados, mas nenhum processo/preço foi retornado. "
            "Ative o modo diagnóstico para analisarmos os campos reais da API."
        )
        st.stop()

    df_processos = pd.DataFrame(processos)
    df_processos = df_processos.drop_duplicates()

    st.subheader("Processos / preços encontrados")

    for _, row in df_processos.iterrows():
        st.markdown(f"""
### {row['Descrição base']}

**Tipo:** {row['Tipo']}  
**Código:** `{row['Código']}`  
**Órgão:** {row['Órgão']}  
**UASG:** {row['UASG']}  
**Compra:** {row['Compra']}  
**Ano:** {row['Ano']}  
**Valor:** {row['Valor']}  
**Data:** {row['Data']}  

<a href="{row['Link']}" target="_blank">Abrir Compras.gov</a>

---
""", unsafe_allow_html=True)

    csv = df_processos.to_csv(index=False).encode("utf-8-sig")

    st.download_button(
        "Baixar processos/preços em CSV",
        csv,
        "comprasgov_processos_precos.csv",
        "text/csv"
    )
