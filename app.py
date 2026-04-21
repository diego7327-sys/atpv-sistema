from flask import Flask, render_template, request, jsonify
import json, os, re
from datetime import datetime

app = Flask(__name__)

# Arquivo de histórico simples (JSON)
HIST_FILE = "historico.json"

def carregar_historico():
    if os.path.exists(HIST_FILE):
        with open(HIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def salvar_historico(hist):
    with open(HIST_FILE, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)

# ── EXTRAÇÃO POR REGEX ──────────────────────────────────────────
def extrair_campos(texto):
    t = texto.replace("\r\n", "\n").replace("\t", " ")
    r = {}

    def match(patterns):
        for p in patterns:
            m = re.search(p, t, re.IGNORECASE)
            if m and m.group(1) and m.group(1).strip():
                return m.group(1).strip()
        return ""

    # Nome proprietário
    r["v_nome"] = match([
        r"Nome(?:\s+do\s+Proprietário)?[:\s]+([A-ZÀ-Ú][A-ZÀ-Ú\s]{3,60}?)(?:\s*CPF|\s*CNPJ|\n)",
        r"Proprietário[:\s]+([A-ZÀ-Ú][A-ZÀ-Ú\s]{3,60}?)(?:\s*CPF|\n)",
        r"Nome\s+Solicitante[:\s]+([A-ZÀ-Ú][A-ZÀ-Ú\s]{3,60}?)(?:\s*Tipo|\n)",
        r"Aberto por[:\s]+([A-ZÀ-Ú][A-ZÀ-Ú\s]{3,60}?)(?:\s*Tipo|\n)",
    ])

    # CPF/CNPJ
    r["v_cpf"] = match([
        r"CPF[/\s]*CNPJ[:\s]*([\d]{2,3}\.[\d]{3}\.[\d]{3}[/\-][\d]{4}[\-\d]{0,6})",
        r"CPF[:\s]*([\d]{3}\.[\d]{3}\.[\d]{3}-[\d]{2})",
        r"CNPJ[:\s]*([\d]{2}\.[\d]{3}\.[\d]{3}/[\d]{4}-[\d]{2})",
    ])

    # RG
    r["v_rg"] = match([r"RG[:\s]*([\d]{5,12})", r"Identidade[:\s]*([\d]{5,12})"])

    # Placa
    pm = re.search(r"Placa[:\s]*([A-Z]{3}[-\s]?[\dA-Z]{4})", t, re.IGNORECASE) or \
         re.search(r"\b([A-Z]{3}[-]?[0-9][A-Z0-9][0-9]{2})\b", t)
    if pm:
        r["ve_placa"] = pm.group(1).replace(" ", "").upper()

    # Chassi
    cm = re.search(r"Chassi[:\s]*([A-Z0-9]{17})", t, re.IGNORECASE) or \
         re.search(r"\b([A-Z0-9]{17})\b", t)
    if cm:
        r["ve_chassi"] = cm.group(1).upper()

    # Marca/Modelo
    r["ve_modelo"] = match([
        r"Marca[/\s]*Modelo[:\s]*[\d-]*\s*([A-ZÀ-Ú0-9\s/]{4,50}?)(?:\s*Ano|\s*\n)",
        r"Modelo[:\s]*([A-ZÀ-Ú0-9\s/]{4,40}?)(?:\s*Ano|\s*Cor|\n)",
    ])
    # Remove prefixo numérico tipo "319465-"
    if r.get("ve_modelo"):
        r["ve_modelo"] = re.sub(r"^\d+-", "", r["ve_modelo"]).strip()

    # Ano
    fab = re.search(r"Ano\s*Fab[:\s]*(\d{4})", t, re.IGNORECASE)
    mod = re.search(r"Ano\s*Mod[:\s]*(\d{4})", t, re.IGNORECASE)
    if fab and mod:
        r["ve_ano"] = fab.group(1) + "/" + mod.group(1)
    elif fab:
        r["ve_ano"] = fab.group(1)
    elif mod:
        r["ve_ano"] = mod.group(1)

    # Endereço
    r["v_end"] = match([
        r"Endere[çc]o[:\s]*([A-ZÀ-Ú][^\n]{5,60}?)(?:\s*N[º°]|\s*Bairro|\s*CEP|\n)",
        r"Logradouro[:\s]*([A-ZÀ-Ú][^\n]{4,50}?)(?:\s*Bairro|\s*CEP|\n)",
    ])
    # Tenta adicionar número
    nro = re.search(r"N[º°][:\s]*(\w+)", t, re.IGNORECASE)
    if nro and r.get("v_end") and nro.group(1) not in r["v_end"]:
        r["v_end"] = r["v_end"].rstrip(", ") + ", " + nro.group(1)

    r["v_bairro"] = match([
        r"Bairro[:\s]*([A-ZÀ-Ú][^\n]{3,40}?)(?:\s*CEP|\s*Munic|\s*Compl|\n)",
    ])

    r["v_cidade"] = match([
        r"Munic[íi]pio[:\s]*[\d-]*\s*([A-ZÀ-Ú][^\n]{3,30}?)(?:\s*CEP|\s*UF|\n)",
        r"Cidade[:\s]*([A-ZÀ-Ú][^\n]{3,30}?)(?:\s*CEP|\s*UF|\n)",
    ])

    cep = re.search(r"CEP[:\s]*([\d]{5}-?[\d]{3})", t, re.IGNORECASE)
    if cep:
        c = re.sub(r"\D", "", cep.group(1))
        r["v_cep"] = c[:5] + "-" + c[5:]

    # Limpa valores muito curtos
    for k in ["v_nome", "v_bairro", "v_cidade", "ve_modelo"]:
        if r.get(k) and len(r[k]) < 3:
            r[k] = ""

    return {k: v for k, v in r.items() if v}

# ── ROTAS ──────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/extrair", methods=["POST"])
def api_extrair():
    data = request.get_json()
    texto = data.get("texto", "")
    if not texto.strip():
        return jsonify({"erro": "Texto vazio"}), 400
    campos = extrair_campos(texto)
    return jsonify({"campos": campos, "total": len(campos)})

@app.route("/api/historico", methods=["GET"])
def api_historico_get():
    return jsonify(carregar_historico())

@app.route("/api/historico", methods=["POST"])
def api_historico_post():
    data = request.get_json()
    hist = carregar_historico()
    data["data"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    hist.insert(0, data)
    hist = hist[:200]  # Mantém últimos 200
    salvar_historico(hist)
    return jsonify({"ok": True})

@app.route("/api/historico/<int:idx>", methods=["DELETE"])
def api_historico_del(idx):
    hist = carregar_historico()
    if 0 <= idx < len(hist):
        hist.pop(idx)
        salvar_historico(hist)
    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
