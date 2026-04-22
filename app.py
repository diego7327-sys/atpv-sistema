from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import json, os, re, secrets
from datetime import datetime, date
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'atpv-diego-2670-secret-key-fixo')
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24 horas
app.config['SESSION_COOKIE_HTTPONLY'] = True

# ── ARQUIVOS ─────────────────────────────────────────────────
HIST_FILE     = "historico.json"
PESSOAS_FILE  = "pessoas.json"
VEICULOS_FILE = "veiculos.json"
USERS_FILE    = "usuarios.json"
EMPRESAS_FILE = "empresas.json"
CONTRAT_FILE  = "contratantes.json"

def ler(f):
    if os.path.exists(f):
        with open(f,"r",encoding="utf-8") as fp: return json.load(fp)
    return []

def gravar(f, data):
    with open(f,"w",encoding="utf-8") as fp: json.dump(data, fp, ensure_ascii=False, indent=2)

# ── USUÁRIOS PADRÃO ──────────────────────────────────────────
def init_usuarios():
    if not os.path.exists(USERS_FILE):
        admin = {
            "id": "1",
            "nome": "Diego Caetano",
            "login": "diego",
            "senha": generate_password_hash("diego2670"),
            "perfil": "admin",  # admin, funcionario, empresa
            "empresa_id": None,
            "ativo": True,
            "criado": datetime.now().strftime("%d/%m/%Y %H:%M")
        }
        gravar(USERS_FILE, [admin])

init_usuarios()

# ── AUTENTICAÇÃO ─────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"erro": "Não autorizado"}), 401
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"erro": "Não autorizado"}), 401
        if session.get('perfil') not in ['admin', 'funcionario']:
            return jsonify({"erro": "Sem permissão"}), 403
        return f(*args, **kwargs)
    return decorated

def get_user():
    uid = session.get('user_id')
    if not uid: return None
    users = ler(USERS_FILE)
    return next((u for u in users if u['id']==uid), None)

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

    # ── DETECTA SE É CNH (OCR) ───────────────────────────────
    is_cnh = bool(re.search(r"CARTEIRA\s+NACIONAL\s+DE\s+HABILITAC|DRIVER\s+LICENSE|PERMISO\s+DE\s+CONDUC|HABILITAC[AÃ]O", t, re.IGNORECASE))
    is_rg  = bool(re.search(r"CARTEIRA\s+DE\s+IDENTIDADE|REGISTRO\s+GERAL|INSTITUTO\s+DE\s+IDENTIFICA", t, re.IGNORECASE))

    if is_cnh:
        # CNH: nome é a primeira linha com só letras maiúsculas após o cabeçalho
        # Padrão: após "CONDUCCION\n" ou "LICENSE\n" vem o nome
        nome_cnh = match([
            r"CONDUCCION\s*\n\s*([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ][A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ\s]{3,60}?)(?:\s*\n)",
            r"LICENSE[/\s]*PERMISO[^\n]*\n\s*([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ][A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ\s]{3,60}?)(?:\s*\n)",
            r"HABILITAC[AÃ]O[^\n]*\n\s*([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ][A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ\s]{3,60}?)(?:\s*\n)",
        ])
        # Se não achou com padrão, pega a primeira linha com 2+ palavras só letras maiúsculas
        if not nome_cnh:
            for linha in t.split('\n'):
                linha = linha.strip()
                if re.match(r'^[A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ]{2,}(\s+[A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ]{2,})+$', linha):
                    if len(linha) > 8 and not any(w in linha for w in ['BRASIL','FEDERAL','MINISTERIO','SECRETARIA','NACIONAL','TRANSITO','TERRITORIO','HABILITACAO']):
                        nome_cnh = linha
                        break
        if nome_cnh:
            r["v_nome"] = nome_cnh.strip()

        # Data de nascimento na CNH: formato "DD/MM/AAAA, CIDADE, UF" ou linha isolada
        nasc_m = re.search(r"(\d{2}/\d{2}/\d{4}),?\s+([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ][A-Z\s]+),?\s+([A-Z]{2})", t)
        if nasc_m:
            r["v_nasc"] = nasc_m.group(1)
            r["v_cidade"] = nasc_m.group(2).strip() + "/" + nasc_m.group(3)

        # RG da CNH (número de registro — 9+ dígitos)
        rg_cnh = re.search(r"\b(\d{9,11})\b", t)
        if rg_cnh:
            r["v_rg"] = rg_cnh.group(1)

        # Cidade atual (GOIANIA, GO — última ocorrência de cidade/UF)
        cidades = re.findall(r"([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ][A-Z\s]{2,20}),\s*([A-Z]{2})(?:\s|\n|$)", t)
        for cidade, uf in reversed(cidades):
            cidade = cidade.strip()
            if cidade not in ['DRIVER LICENSE','PERMISO','REPUBLICA','MINISTERIO','SECRETARIA']:
                if not r.get("v_cidade"):
                    r["v_cidade"] = cidade + "/" + uf
                break

    elif is_rg:
        # RG: nome após "NOME" ou primeira linha com letras maiúsculas
        r["v_nome"] = match([
            r"NOME[:\s]*([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÈÌÒÙÇ][A-Z\s]{3,60}?)(?:\s*\n|\s*DATA)",
        ])
        r["v_nasc"] = match([r"NASCIMENTO[:\s]*(\d{2}/\d{2}/\d{4})"])
        r["v_cidade"] = match([r"NATURAL[:\s]*([A-Z][A-Z\s]{2,30}?)(?:\s*\n|\s*UF)"])

    # ── NOME — padrões gerais (DETRAN, formulários etc) ──────
    if not r.get("v_nome"):
        r["v_nome"] = match([
            r"Nome(?:\s+do\s+Proprietario)?[:\s]+([A-Z][A-Z\s]{3,60}?)(?:\s*CPF|\s*CNPJ|\n)",
            r"Proprietario[:\s]+([A-Z][A-Z\s]{3,60}?)(?:\s*CPF|\n)",
            r"Nome\s+Solicitante[:\s]+([A-Z][A-Z\s]{3,60}?)(?:\s*Tipo|\n)",
            r"Aberto por[:\s]+([A-Z][A-Z\s]{3,60}?)(?:\s*Tipo|\n)",
            r"Nome:[:\s]+([A-Z][A-Z\s]{3,60}?)(?:\s*CPF|\s*CNPJ|\n)",
            r"Nome[^\n:]*:\s*[\t ]*\n[\t ]*([A-Z][A-Z\s]{3,60}?)[\t ]*\n",
        ])
    palavras_invalidas = ['EMPRESARIAL','SITUACAO','ESPECIAL','REGULAR','SUSPENSA','CANCELADA',
                          'INAPTA','BAIXADA','PENDENTE','CONSULTA','SERVICOS','RECEITA',
                          'DRIVER LICENSE','HABILITACAO','REPUBLICA','MINISTERIO']
    if r.get("v_nome") and r["v_nome"].strip().upper() in palavras_invalidas:
        r["v_nome"] = ""

    r["v_cpf"] = match([
        r"CPF[/\s]*CNPJ[:\s]*([\d]{2,3}\.[\d]{3}\.[\d]{3}[/\-][\d]{4}[\-\d]{0,6})",
        r"CPF[:\s]*([\d]{3}\.[\d]{3}\.[\d]{3}-[\d]{2})",
        r"CNPJ[:\s]*([\d]{2}\.[\d]{3}\.[\d]{3}/[\d]{4}-[\d]{2})",
        r"\b(\d{3}\.\d{3}\.\d{3}-\d{2})\b",
        r"\b(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\b",
    ])

    if not r.get("v_rg"):
        r["v_rg"] = match([r"RG[:\s]*([\d]{5,12})", r"Identidade[:\s]*([\d]{5,12})"])

    # Data de nascimento geral
    if not r.get("v_nasc"):
        nasc_g = match([
            r"Nascimento[:\s]*(\d{2}/\d{2}/\d{4})",
            r"Data\s+de\s+Nasc[:\s]*(\d{2}/\d{2}/\d{4})",
        ])
        if nasc_g: r["v_nasc"] = nasc_g

    pm = re.search(r"Placa[:\s]*([A-Z]{3}[-\s]?[\dA-Z]{4})", t, re.IGNORECASE) or \
         re.search(r"\b([A-Z]{3}[-]?[0-9][A-Z0-9][0-9]{2})\b", t)
    if pm: r["ve_placa"] = pm.group(1).replace(" ","").upper()

    cm = re.search(r"Chassi[:\s]*([A-Z0-9]{17})", t, re.IGNORECASE) or \
         re.search(r"\b([A-Z0-9]{17})\b", t)
    if cm: r["ve_chassi"] = cm.group(1).upper()

    r["ve_modelo"] = match([
        r"Marca[/\s]*Modelo[:\s]*[\d-]*\s*([A-Z0-9][A-Z0-9\s/\-\.]{3,50}?)(?:\s*Ano|\s*cor|\s*Cap|\n)",
        r"Modelo[:\s]*[\d-]*\s*([A-Z0-9][A-Z0-9\s/\-\.]{3,40}?)(?:\s*Ano|\s*Cor|\n)",
        r"\d{4,6}-([A-Z][A-Z0-9\s/\.]{3,40}?)(?:\s*Ano\s*Mod|\s*Ano\s*Fab|\n)",
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
    nro_m = re.search(r"N[uú]mero[:\s]*(\d+[A-Z]?)", t, re.IGNORECASE) or \
            re.search(r"\bN[o°º][:\s]*(\d+[A-Z]?)", t, re.IGNORECASE)
    nro = nro_m.group(1).strip() if nro_m else ""
    if nro in ["0","00","000"]: nro = "SN"
    complemento = match([r"Complemento[:\s]*([^\n]{3,50}?)(?:\s*N[ouú]|\s*Munic|\s*CEP|\n)"])
    end_parts = []
    if logradouro: end_parts.append(logradouro.strip().rstrip(","))
    if nro: end_parts.append("Nº "+nro)
    if complemento: end_parts.append(complemento.strip())
    if end_parts: r["v_end"] = ", ".join(end_parts)

    r["v_bairro"] = match([r"Bairro[:\s]*([A-Z][^\n]{3,40}?)(?:\s*CEP|\s*Munic|\s*Compl|\n)"])

    if not r.get("v_cidade"):
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

# ── ROTAS DE AUTENTICAÇÃO ─────────────────────────────────────
@app.route("/")
def index():
    if 'user_id' not in session:
        return render_template("login.html")
    return render_template("index.html")

@app.route("/login", methods=["GET"])
def login_page():
    if 'user_id' in session:
        return redirect('/')
    return render_template("login.html")

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json()
    login = data.get("login","").strip().lower()
    senha = data.get("senha","")
    users = ler(USERS_FILE)
    user = next((u for u in users if u['login'].lower()==login and u.get('ativo',True)), None)
    if not user or not check_password_hash(user['senha'], senha):
        return jsonify({"erro": "Login ou senha incorretos"}), 401
    session.permanent = True
    session['user_id']  = user['id']
    session['user_nome']= user['nome']
    session['perfil']   = user['perfil']
    session['empresa_id'] = user.get('empresa_id')
    return jsonify({"ok":True, "perfil":user['perfil'], "nome":user['nome']})

@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok":True})

@app.route("/api/me")
def api_me():
    if 'user_id' not in session:
        return jsonify({"logado": False})
    return jsonify({"logado":True,"nome":session.get('user_nome'),"perfil":session.get('perfil'),
                    "empresa_id":session.get('empresa_id')})

# ── ROTAS PRINCIPAIS ──────────────────────────────────────────
@app.route("/api/extrair", methods=["POST"])
@login_required
def api_extrair():
    data = request.get_json()
    campos = extrair_campos(data.get("texto",""))
    return jsonify({"campos":campos,"total":len(campos)})

# ── HISTÓRICO ─────────────────────────────────────────────────
@app.route("/api/historico", methods=["GET"])
@login_required
def api_hist_get():
    hist = ler(HIST_FILE)
    perfil = session.get('perfil')
    empresa_id = session.get('empresa_id')
    # Empresa só vê o próprio histórico
    if perfil == 'empresa':
        hist = [h for h in hist if h.get('empresa_id') == empresa_id]
    return jsonify(hist)

@app.route("/api/historico", methods=["POST"])
@login_required
def api_hist_post():
    data = request.get_json()
    hist = ler(HIST_FILE)
    data["data"]        = datetime.now().strftime("%d/%m/%Y %H:%M")
    data["user_id"]     = session.get('user_id')
    data["user_nome"]   = session.get('user_nome')
    data["perfil"]      = session.get('perfil')
    data["empresa_id"]  = session.get('empresa_id')
    hist.insert(0,data); hist = hist[:500]
    gravar(HIST_FILE, hist)
    return jsonify({"ok":True})

@app.route("/api/historico/<int:idx>", methods=["DELETE"])
@login_required
def api_hist_del(idx):
    hist = ler(HIST_FILE)
    perfil = session.get('perfil')
    empresa_id = session.get('empresa_id')
    if perfil == 'empresa':
        # empresa só apaga os próprios
        visivel = [h for h in hist if h.get('empresa_id')==empresa_id]
        if 0<=idx<len(visivel):
            real_idx = hist.index(visivel[idx])
            hist.pop(real_idx)
    elif 0<=idx<len(hist):
        hist.pop(idx)
    gravar(HIST_FILE, hist)
    return jsonify({"ok":True})

# ── PESSOAS ───────────────────────────────────────────────────
@app.route("/api/pessoas", methods=["GET"])
@login_required
def api_pessoas_get():
    q = request.args.get("q","").lower()
    pessoas = ler(PESSOAS_FILE)
    if q:
        pessoas = [p for p in pessoas if q in (p.get("nome","")+"  "+p.get("cpf","")).lower()]
    return jsonify(pessoas[:20])

@app.route("/api/pessoas", methods=["POST"])
@login_required
def api_pessoas_post():
    data = request.get_json()
    if not data.get("nome") and not data.get("cpf"):
        return jsonify({"erro":"Informe nome ou CPF"}), 400
    pessoas = ler(PESSOAS_FILE)
    cpf = data.get("cpf","").strip()
    idx = next((i for i,p in enumerate(pessoas) if cpf and p.get("cpf")==cpf), None)
    data["atualizado"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    if idx is not None: pessoas[idx] = data
    else: pessoas.insert(0, data)
    gravar(PESSOAS_FILE, pessoas[:500])
    return jsonify({"ok":True})

# ── VEÍCULOS ──────────────────────────────────────────────────
@app.route("/api/veiculos", methods=["GET"])
@login_required
def api_veiculos_get():
    q = request.args.get("q","").lower()
    veiculos = ler(VEICULOS_FILE)
    if q:
        veiculos = [v for v in veiculos if q in (v.get("placa","")+"  "+v.get("modelo","")).lower()]
    return jsonify(veiculos[:20])

@app.route("/api/veiculos", methods=["POST"])
@login_required
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
    gravar(VEICULOS_FILE, veiculos[:500])
    return jsonify({"ok":True})

# ── USUÁRIOS (só admin) ───────────────────────────────────────
@app.route("/api/usuarios", methods=["GET"])
@login_required
def api_usuarios_get():
    if session.get('perfil') != 'admin':
        return jsonify({"erro":"Sem permissão"}), 403
    users = ler(USERS_FILE)
    # Remove senhas da resposta
    return jsonify([{k:v for k,v in u.items() if k!='senha'} for u in users])

@app.route("/api/usuarios", methods=["POST"])
@login_required
def api_usuarios_post():
    if session.get('perfil') != 'admin':
        return jsonify({"erro":"Sem permissão"}), 403
    data = request.get_json()
    users = ler(USERS_FILE)
    login = data.get("login","").strip().lower()
    if not login or not data.get("senha"):
        return jsonify({"erro":"Login e senha são obrigatórios"}), 400
    if any(u['login'].lower()==login for u in users):
        return jsonify({"erro":"Login já existe"}), 400
    novo = {
        "id": str(int(datetime.now().timestamp()*1000)),
        "nome": data.get("nome",""),
        "login": login,
        "senha": generate_password_hash(data.get("senha","")),
        "perfil": data.get("perfil","funcionario"),
        "empresa_id": data.get("empresa_id"),
        "ativo": True,
        "criado": datetime.now().strftime("%d/%m/%Y %H:%M")
    }
    users.append(novo)
    gravar(USERS_FILE, users)
    return jsonify({"ok":True})

@app.route("/api/usuarios/<uid>", methods=["PUT"])
@login_required
def api_usuarios_put(uid):
    if session.get('perfil') != 'admin':
        return jsonify({"erro":"Sem permissão"}), 403
    data = request.get_json()
    users = ler(USERS_FILE)
    idx = next((i for i,u in enumerate(users) if u['id']==uid), None)
    if idx is None: return jsonify({"erro":"Não encontrado"}), 404
    users[idx]['nome']   = data.get("nome", users[idx]['nome'])
    users[idx]['perfil'] = data.get("perfil", users[idx]['perfil'])
    users[idx]['ativo']  = data.get("ativo", users[idx]['ativo'])
    users[idx]['empresa_id'] = data.get("empresa_id", users[idx].get('empresa_id'))
    if data.get("senha"):
        users[idx]['senha'] = generate_password_hash(data["senha"])
    gravar(USERS_FILE, users)
    return jsonify({"ok":True})

@app.route("/api/usuarios/<uid>", methods=["DELETE"])
@login_required
def api_usuarios_del(uid):
    if session.get('perfil') != 'admin':
        return jsonify({"erro":"Sem permissão"}), 403
    if uid == session.get('user_id'):
        return jsonify({"erro":"Não pode excluir a si mesmo"}), 400
    users = ler(USERS_FILE)
    users = [u for u in users if u['id']!=uid]
    gravar(USERS_FILE, users)
    return jsonify({"ok":True})

# ── EMPRESAS (só admin) ───────────────────────────────────────
@app.route("/api/empresas", methods=["GET"])
@login_required
def api_empresas_get():
    if session.get('perfil') not in ['admin','funcionario']:
        return jsonify({"erro":"Sem permissão"}), 403
    return jsonify(ler(EMPRESAS_FILE))

@app.route("/api/empresas", methods=["POST"])
@login_required
def api_empresas_post():
    if session.get('perfil') != 'admin':
        return jsonify({"erro":"Sem permissão"}), 403
    data = request.get_json()
    if not data.get("nome"):
        return jsonify({"erro":"Nome é obrigatório"}), 400
    empresas = ler(EMPRESAS_FILE)
    data["id"] = str(int(datetime.now().timestamp()*1000))
    data["criado"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    empresas.append(data)
    gravar(EMPRESAS_FILE, empresas)
    return jsonify({"ok":True, "id":data["id"]})

@app.route("/api/empresas/<eid>", methods=["DELETE"])
@login_required
def api_empresas_del(eid):
    if session.get('perfil') != 'admin':
        return jsonify({"erro":"Sem permissão"}), 403
    empresas = [e for e in ler(EMPRESAS_FILE) if e['id']!=eid]
    gravar(EMPRESAS_FILE, empresas)
    return jsonify({"ok":True})

# ── LIMPEZA ───────────────────────────────────────────────────
@app.route("/api/limpar-tudo", methods=["POST"])
@login_required
def api_limpar_tudo():
    if session.get('perfil') != 'admin':
        return jsonify({"erro":"Sem permissão"}), 403
    gravar(HIST_FILE, []); gravar(PESSOAS_FILE, []); gravar(VEICULOS_FILE, [])
    return jsonify({"ok":True})

@app.route("/api/historico-limpar", methods=["POST"])
@login_required
def api_hist_limpar():
    if session.get('perfil') != 'admin': return jsonify({"erro":"Sem permissão"}), 403
    gravar(HIST_FILE, []); return jsonify({"ok":True})

@app.route("/api/pessoas-limpar", methods=["POST"])
@login_required
def api_pessoas_limpar():
    if session.get('perfil') != 'admin': return jsonify({"erro":"Sem permissão"}), 403
    gravar(PESSOAS_FILE, []); return jsonify({"ok":True})

@app.route("/api/veiculos-limpar", methods=["POST"])
@login_required
def api_veiculos_limpar():
    if session.get('perfil') != 'admin': return jsonify({"erro":"Sem permissão"}), 403
    gravar(VEICULOS_FILE, []); return jsonify({"ok":True})

# ── FINANCEIRO — atualizar valor/status de um atendimento ─────
@app.route("/api/historico/<int:idx>/financeiro", methods=["PUT"])
@login_required
def api_fin_put(idx):
    data = request.get_json()
    hist = ler(HIST_FILE)
    perfil = session.get('perfil')
    empresa_id = session.get('empresa_id')
    # Empresa só edita seus próprios
    if perfil == 'empresa':
        visivel = [h for h in hist if h.get('empresa_id')==empresa_id]
        if idx < 0 or idx >= len(visivel): return jsonify({"erro":"Não encontrado"}), 404
        real_idx = hist.index(visivel[idx])
    else:
        if idx < 0 or idx >= len(hist): return jsonify({"erro":"Não encontrado"}), 404
        real_idx = idx
    hist[real_idx]['valor_cobrado'] = data.get('valor_cobrado', hist[real_idx].get('valor_cobrado',''))
    hist[real_idx]['status_pgto']   = data.get('status_pgto', hist[real_idx].get('status_pgto','pendente'))
    hist[real_idx]['obs_fin']       = data.get('obs_fin', hist[real_idx].get('obs_fin',''))
    gravar(HIST_FILE, hist)
    return jsonify({"ok":True})

# ── RELATÓRIOS ────────────────────────────────────────────────
@app.route("/api/relatorios")
@login_required
def api_relatorios():
    perfil      = session.get('perfil')
    empresa_id  = session.get('empresa_id')
    user_id     = session.get('user_id')

    # Filtros
    de   = request.args.get('de','')    # DD/MM/AAAA
    ate  = request.args.get('ate','')
    func = request.args.get('func','')  # user_id filtro
    emp  = request.args.get('emp','')   # empresa_id filtro

    hist = ler(HIST_FILE)

    # Restrição por perfil
    if perfil == 'empresa':
        hist = [h for h in hist if h.get('empresa_id') == empresa_id]
    elif perfil == 'funcionario':
        # Verifica se tem permissão de relatório
        users = ler(USERS_FILE)
        me = next((u for u in users if u['id']==user_id), {})
        if not me.get('ver_relatorio', False):
            return jsonify({"erro":"Sem permissão para relatórios"}), 403

    # Filtro de datas
    def parse_data(s):
        try:
            d,m,a = s.split('/')
            return datetime(int(a),int(m),int(d))
        except: return None

    if de:
        dt_de = parse_data(de)
        if dt_de:
            hist = [h for h in hist if parse_data(h.get('data','').split(' ')[0]) and parse_data(h.get('data','').split(' ')[0]) >= dt_de]
    if ate:
        dt_ate = parse_data(ate)
        if dt_ate:
            hist = [h for h in hist if parse_data(h.get('data','').split(' ')[0]) and parse_data(h.get('data','').split(' ')[0]) <= dt_ate]
    if func and perfil == 'admin':
        hist = [h for h in hist if h.get('user_id') == func]
    if emp and perfil in ['admin','funcionario']:
        hist = [h for h in hist if h.get('empresa_id') == emp]

    # Totais
    total     = len(hist)
    recebidos = sum(1 for h in hist if h.get('status_pgto')=='pago')
    pendentes = total - recebidos

    def parse_val(v):
        if not v: return 0.0
        return float(str(v).replace('R$','').replace('.','').replace(',','.').strip() or 0)

    val_total    = sum(parse_val(h.get('valor_cobrado','')) for h in hist)
    val_recebido = sum(parse_val(h.get('valor_cobrado','')) for h in hist if h.get('status_pgto')=='pago')
    val_pendente = val_total - val_recebido

    # Agrupamento por funcionário
    por_func = {}
    for h in hist:
        uid  = h.get('user_id','?')
        nome = h.get('user_nome','Desconhecido')
        if uid not in por_func:
            por_func[uid] = {'nome':nome,'total':0,'recebidos':0,'val_total':0,'val_recebido':0}
        por_func[uid]['total']       += 1
        por_func[uid]['val_total']   += parse_val(h.get('valor_cobrado',''))
        if h.get('status_pgto')=='pago':
            por_func[uid]['recebidos']    += 1
            por_func[uid]['val_recebido'] += parse_val(h.get('valor_cobrado',''))

    # Agrupamento por empresa
    empresas_map = {e['id']:e['nome'] for e in ler(EMPRESAS_FILE)}
    por_emp = {}
    for h in hist:
        eid  = h.get('empresa_id') or 'escritorio'
        nome = empresas_map.get(eid,'Escritório') if eid!='escritorio' else 'Escritório'
        if eid not in por_emp:
            por_emp[eid] = {'nome':nome,'total':0,'recebidos':0,'val_total':0,'val_recebido':0,'atendimentos':[]}
        por_emp[eid]['total']       += 1
        por_emp[eid]['val_total']   += parse_val(h.get('valor_cobrado',''))
        if h.get('status_pgto')=='pago':
            por_emp[eid]['recebidos']    += 1
            por_emp[eid]['val_recebido'] += parse_val(h.get('valor_cobrado',''))
        por_emp[eid]['atendimentos'].append({
            'placa':   h.get('placa',''),
            'modelo':  h.get('modelo',''),
            'chassi':  h.get('snap',{}).get('ve_chassi','') if h.get('snap') else '',
            'vendedor':h.get('snap',{}).get('v_nome','') if h.get('snap') else '',
            'data':    h.get('data',''),
            'valor':   h.get('valor_cobrado',''),
            'status':  h.get('status_pgto','pendente'),
        })

    # Agrupamento por mês
    por_mes = {}
    for h in hist:
        dt_str = h.get('data','')
        mes = dt_str[3:10] if len(dt_str)>=10 else '?'
        if mes not in por_mes: por_mes[mes]={'total':0,'recebidos':0,'val_total':0}
        por_mes[mes]['total'] += 1
        por_mes[mes]['val_total'] += parse_val(h.get('valor_cobrado',''))
        if h.get('status_pgto')=='pago': por_mes[mes]['recebidos'] += 1

    return jsonify({
        'total':total,'recebidos':recebidos,'pendentes':pendentes,
        'val_total':round(val_total,2),'val_recebido':round(val_recebido,2),'val_pendente':round(val_pendente,2),
        'por_func':list(por_func.values()),
        'por_emp':list(por_emp.values()),
        'por_mes':[ {'mes':k,'total':v['total'],'recebidos':v['recebidos'],'val_total':round(v['val_total'],2)} for k,v in sorted(por_mes.items(),reverse=True) ],
        'atendimentos': [{
            'idx':i,'data':h.get('data',''),'placa':h.get('placa',''),'modelo':h.get('modelo',''),
            'vendedor':h.get('snap',{}).get('v_nome','') if h.get('snap') else '',
            'chassi':h.get('snap',{}).get('ve_chassi','') if h.get('snap') else '',
            'func':h.get('user_nome',''),'empresa':empresas_map.get(h.get('empresa_id',''),'Escritório'),
            'valor':h.get('valor_cobrado',''),'status':h.get('status_pgto','pendente'),
        } for i,h in enumerate(hist)]
    })

# ── PERMISSÕES DE RELATÓRIO ───────────────────────────────────
@app.route("/api/usuarios/<uid>/permissoes", methods=["PUT"])
@login_required
def api_permissoes(uid):
    if session.get('perfil') != 'admin':
        return jsonify({"erro":"Sem permissão"}), 403
    data  = request.get_json()
    users = ler(USERS_FILE)
    idx   = next((i for i,u in enumerate(users) if u['id']==uid), None)
    if idx is None: return jsonify({"erro":"Não encontrado"}), 404
    users[idx]['ver_relatorio'] = data.get('ver_relatorio', False)
    gravar(USERS_FILE, users)
    return jsonify({"ok":True})

# ── CONTRATANTES ─────────────────────────────────────────────
@app.route("/api/contratantes", methods=["GET"])
@login_required
def api_contrat_get():
    q = request.args.get("q","").lower()
    lista = ler(CONTRAT_FILE)
    if q:
        lista = [c for c in lista if q in (c.get("nome","")+"  "+c.get("cpf","")).lower()]
    return jsonify(lista[:20])

@app.route("/api/contratantes", methods=["POST"])
@login_required
def api_contrat_post():
    data = request.get_json()
    if not data.get("nome"): return jsonify({"erro":"Nome obrigatório"}), 400
    lista = ler(CONTRAT_FILE)
    cpf = data.get("cpf","").strip()
    idx = next((i for i,c in enumerate(lista) if cpf and c.get("cpf")==cpf), None)
    data["atualizado"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    if idx is not None: lista[idx] = data
    else: lista.insert(0, data)
    gravar(CONTRAT_FILE, lista[:500])
    return jsonify({"ok":True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT",5000))
    app.run(host="0.0.0.0", port=port, debug=False)
