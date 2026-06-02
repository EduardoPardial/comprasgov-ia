import re
import unicodedata

import pandas as pd
import requests
import streamlit as st
from google import genai


st.set_page_config(
    page_title="Busca Compras.gov IA",
    layout="wide"
)

st.title("Busca Compras.gov IA")
st.caption("Busca CATMAT/CATSER com até 3 termos gerados por IA.")


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
            model="gemini-2.5-flash",
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

        if "resultado" in dados:
            return dados.get("resultado", [])

        if "data" in dados:
            return dados.get("data", [])

        return []

    except Exception:
        return []


def buscar_catmat(termos):
    url = "https://dadosabertos.compras.gov.br/modulo-material/4_consultarItemMaterial"

    resultados = []

    for termo in termos:
        params = {
            "pagina": 1
        }

        itens = consultar_api(url, params)

        for item in itens:
            texto_item = " ".join(str(v) for v in item.values() if v)
            pontos = pontuar(texto_item, texto, [termo])

            if pontos <= 0:
                continue

            resultados.append({
                "Pontuação": pontos,
                "Tipo": "CATMAT",
                "Código": item.get("codigoItem"),
                "Descrição": item.get("descricaoItem") or item.get("nomeItem") or texto_item,
                "Status": item.get("statusItem"),
                "Termo usado": termo
            })

    return resultados


def buscar_catser(termos):
    url = "https://dadosabertos.compras.gov.br/modulo-servico/6_consultarItemServico"

    resultados = []

    for termo in termos:
        params = {
            "pagina": 1
        }

        itens = consultar_api(url, params)

        for item in itens:
            texto_item = " ".join(str(v) for v in item.values() if v)
            pontos = pontuar(texto_item, texto, [termo])

            if pontos <= 0:
                continue

            resultados.append({
                "Pontuação": pontos,
                "Tipo": "CATSER",
                "Código": item.get("codigoServico"),
                "Descrição": item.get("nomeServico") or item.get("descricaoServico") or texto_item,
                "Status": item.get("statusServico"),
                "Termo usado": termo
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

    with st.spinner("Consultando Compras.gov..."):
        if buscar_catmat:
            resultados.extend(buscar_catmat(termos))

        if buscar_catser:
            resultados.extend(buscar_catser(termos))

    if not resultados:
        st.warning("Nenhum resultado relevante encontrado.")
        st.stop()

    df = pd.DataFrame(resultados)
    df = df.drop_duplicates(subset=["Tipo", "Código", "Descrição"])
    df = df.sort_values(by="Pontuação", ascending=False)

    st.subheader("Resultados encontrados")
    st.dataframe(df, use_container_width=True, hide_index=True)

    csv = df.to_csv(index=False).encode("utf-8-sig")

    st.download_button(
        "Baixar CSV",
        csv,
        "comprasgov_resultados.csv",
        "text/csv"
    )
