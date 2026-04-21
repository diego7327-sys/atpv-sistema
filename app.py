from flask import Flask, render_template, request, jsonify
import json, os, re
from datetime import datetime

app = Flask(__name__)
HIST_FILE    = "historico.json"
PESSOAS_FILE = "pessoas.json"
VEICULOS_FILE= "veiculos.json"

# ── HELPERS JSON ──────────────────────────────────────────────
def ler(f):
    if os.path.exists(f):
        with open(f,"r",encoding="utf-8") as fp: return json.load(fp)
    return []

def gravar(f, data):
    with open(f,"w",encoding="utf-8") as fp: json.dump(data, fp, ensure_ascii=False, indent=2)

# ── EXTRAÇÃO POR REGEX ────────────────────────────────────────
def extrair_campos(texto):
    t = texto.replace("\r\n","\n").replace("\t"," ")
    r = {}

    def match(patterns):
        for p in patterns:
            m = re.search(p, t, re.IGNORECASE)
            if m and m.group(1) and m.group(1).strip():
                return m.group(1).strip()
        return ""

    r["v_nome"] = match([
        r"Nome(?:\s+do\s+Proprietario)?[:\s]+([A-ZA-Z\s]{3,60}?)(?:\s*CPF|\s*CNPJ|\n)",
        r"Proprietario[:\s]+([A-Z][A-Z\s]{3,60}?)(?:\s*CPF|\n)",
        r"Nome\s+Solicitante[:\s]+([A-Z][A-Z\s]{3,60}?)(?:\s*Tipo|\n)",
        r"Aberto por[:\s]+([A-Z][A-Z\s]{3,60}?)(?:\s*Tipo|\n)",
        r"Nome:[:\s]+([A-Z][A-Z\s]{3,60}?)(?:\s*CPF|\s*CNPJ|\n)",
    ])
    r["v_cpf"] = match([
        r"CPF[/\s]*CNPJ[:\s]*([\d]{2,3}\.[\d]{3}\.[\d]{3}[/\-][\d]{4}[\-\d]{0,6})",
        r"CPF[:\s]*([\d]{3}\.[\d]{3}\.[\d]{3}-[\d]{2})",
        r"CNPJ[:\s]*([\d]{2}\.[\d]{3}\.[\d]{3}/[\d]{4}-[\d]{2})",
    ])
    r["v_rg"] = match([r"RG[:\s]*([\d]{5,12})", r"Identidade[:\s]*([\d]{5,12})"])

    pm = re.search(r"Placa[:\s]*([A-Z]{3}[-\s]?[\dA-Z]{4})", t, re.IGNORECASE) or \
         re.search(r"\b([A-Z]{3}[-]?[0-9][A-Z0-9][0-9]{2})\b", t)
    if pm: r["ve_placa"] = pm.group(1).replace(" ","").upper()

    cm = re.search(r"Chassi[:\s]*([A-Z0-9]{17})", t, re.IGNORECASE) or \
         re.search(r"\b([A-Z0-9]{17})\b", t)
    if cm: r["ve_chassi"] = cm.group(1).upper()

    r["ve_modelo"] = match([
        r"Marca[/\s]*Modelo[:\s]*[\d-]*\s*([A-Z0-9\s/]{4,50}?)(?:\s*Ano|\s*\n)",
        r"Modelo[:\s]*([A-Z0-9\s/]{4,40}?)(?:\s*Ano|\s*Cor|\n)",
    ])
    if r.get("ve_modelo"): r["ve_modelo"] = re.sub(r"^\d+-","",r["ve_modelo"]).strip()

    fab = re.search(r"Ano\s*Fab[:\s]*(\d{4})", t, re.IGNORECASE)
    mod = re.search(r"Ano\s*Mod[:\s]*(\d{4})", t, re.IGNORECASE)
    if fab and mod: r["ve_ano"] = fab.group(1)+"/"+mod.group(1)
    elif fab: r["ve_ano"] = fab.group(1)
    elif mod: r["ve_ano"] = mod.group(1)

    logradouro = match([
        r"Logradouro[:\s]*([A-Z][^\n]{4,60}?)(?:\s*Bairro|\s*CEP|\s*N[ou]|\n)",
        r"Endere[cC]o[:\s]*([A-Z][^\n]{5,60}?)(?:\s*N[ou]|\s*Bairro|\s*CEP|\n)",
    ])
    nro_m = re.search(r"N[uú]mero[:\s]*([A-Z0-9/]+)", t, re.IGNORECASE) or \
            re.search(r"N[o°][:\s]*([A-Z0-9/]+)", t, re.IGNORECASE) or \
            re.search(r"N[º][:\s]*([A-Z0-9/]+)", t, re.IGNORECASE)
    nro = nro_m.group(1).strip() if nro_m else ""
    complemento = match([r"Complemento[:\s]*([^\n]{3,50}?)(?:\s*N[ouú]|\s*Munic|\s*CEP|\n)"])
    end_parts = []
    if logradouro: end_parts.append(logradouro.strip().rstrip(","))
    if nro: end_parts.append("Nº "+nro)
    if complemento: end_parts.append(complemento.strip())
    if end_parts: r["v_end"] = ", ".join(end_parts)

    r["v_bairro"] = match([r"Bairro[:\s]*([A-Z][^\n]{3,40}?)(?:\s*CEP|\s*Munic|\s*Compl|\n)"])

    cm2 = re.search(r"Munic[íi]pio[:\s]*([^\n]{3,50}?)(?:\s*CEP|\s*UF|\n)", t, re.IGNORECASE)
    cidade_raw = re.sub(r"^[\d\s]+[-]\s*","",cm2.group(1)).strip() if cm2 else ""
    if not cidade_raw: cidade_raw = match([r"Cidade[:\s]*([A-Z][^\n]{3,30}?)(?:\s*CEP|\s*UF|\n)"])
    r["v_cidade"] = cidade_raw

    cep_m = re.search(r"CEP[:\s]*([\d]{2}[.;]?[\d]{3}[-.]?[\d]{3})", t, re.IGNORECASE)
    if cep_m:
        c = re.sub(r"\D","",cep_m.group(1))
        if len(c)==8: r["v_cep"] = c[:5]+"-"+c[5:]

    for k in ["v_nome","v_bairro","v_cidade","ve_modelo"]:
        if r.get(k) and len(r[k])<3: r[k]=""

    return {k:v for k,v in r.items() if v}

# ── ROTAS PRINCIPAIS ──────────────────────────────────────────
@app.route("/")
def index(): return render_template("index.html")

@app.route("/api/extrair", methods=["POST"])
def api_extrair():
    data = request.get_json()
    texto = data.get("texto","")
    if not texto.strip(): return jsonify({"erro":"Texto vazio"}), 400
    campos = extrair_campos(texto)
    return jsonify({"campos":campos,"total":len(campos)})

# ── HISTÓRICO ────────────────────────────────────────────────
@app.route("/api/historico", methods=["GET"])
def api_hist_get(): return jsonify(ler(HIST_FILE))

@app.route("/api/historico", methods=["POST"])
def api_hist_post():
    data = request.get_json()
    hist = ler(HIST_FILE)
    data["data"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    hist.insert(0,data); hist = hist[:300]
    gravar(HIST_FILE, hist)
    return jsonify({"ok":True})

@app.route("/api/historico/<int:idx>", methods=["DELETE"])
def api_hist_del(idx):
    hist = ler(HIST_FILE)
    if 0<=idx<len(hist): hist.pop(idx); gravar(HIST_FILE, hist)
    return jsonify({"ok":True})

# ── CADASTRO PESSOAS ─────────────────────────────────────────
@app.route("/api/pessoas", methods=["GET"])
def api_pessoas_get():
    q = request.args.get("q","").lower()
    pessoas = ler(PESSOAS_FILE)
    if q:
        pessoas = [p for p in pessoas if q in (p.get("nome","")+"  "+p.get("cpf","")).lower()]
    return jsonify(pessoas[:20])

@app.route("/api/pessoas", methods=["POST"])
def api_pessoas_post():
    data = request.get_json()
    cpf = data.get("cpf","").strip()
    nome = data.get("nome","").strip()
    if not cpf and not nome: return jsonify({"erro":"Informe nome ou CPF"}), 400
    pessoas = ler(PESSOAS_FILE)
    # Atualiza se já existe (mesmo CPF), senão insere
    idx = next((i for i,p in enumerate(pessoas) if cpf and p.get("cpf")==cpf), None)
    data["atualizado"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    if idx is not None:
        pessoas[idx] = data
    else:
        pessoas.insert(0, data)
    pessoas = pessoas[:500]
    gravar(PESSOAS_FILE, pessoas)
    return jsonify({"ok":True})

@app.route("/api/pessoas/<int:idx>", methods=["DELETE"])
def api_pessoas_del(idx):
    pessoas = ler(PESSOAS_FILE)
    if 0<=idx<len(pessoas): pessoas.pop(idx); gravar(PESSOAS_FILE, pessoas)
    return jsonify({"ok":True})

# ── CADASTRO VEÍCULOS ────────────────────────────────────────
@app.route("/api/veiculos", methods=["GET"])
def api_veiculos_get():
    q = request.args.get("q","").lower()
    veiculos = ler(VEICULOS_FILE)
    if q:
        veiculos = [v for v in veiculos if q in (v.get("placa","")+"  "+v.get("modelo","")).lower()]
    return jsonify(veiculos[:20])

@app.route("/api/veiculos", methods=["POST"])
def api_veiculos_post():
    data = request.get_json()
    placa = data.get("placa","").strip().upper()
    if not placa: return jsonify({"erro":"Informe a placa"}), 400
    veiculos = ler(VEICULOS_FILE)
    idx = next((i for i,v in enumerate(veiculos) if v.get("placa")==placa), None)
    data["placa"] = placa
    data["atualizado"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    if idx is not None: veiculos[idx] = data
    else: veiculos.insert(0, data)
    veiculos = veiculos[:500]
    gravar(VEICULOS_FILE, veiculos)
    return jsonify({"ok":True})

@app.route("/api/veiculos/<int:idx>", methods=["DELETE"])
def api_veiculos_del(idx):
    veiculos = ler(VEICULOS_FILE)
    if 0<=idx<len(veiculos): veiculos.pop(idx); gravar(VEICULOS_FILE, veiculos)
    return jsonify({"ok":True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT",5000))
    app.run(host="0.0.0.0", port=port, debug=False)
