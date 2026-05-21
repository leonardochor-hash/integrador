"""
Cliente Python para o LivePDV / Moombox (Yii2).

Mapeia endpoints para o projeto integrador que classifica marcas
inadimplentes e executa bloqueios em 5 niveis de severidade.

Endpoints documentados em docs/livepdv_endpoints.md
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# =====================================================================
#  Excecoes
# =====================================================================
class LivePDVError(Exception):
    """Erro generico do cliente LivePDV."""


class LivePDVAuthError(LivePDVError):
    """Falha de autenticacao ou sessao expirada."""


class LivePDVValidationError(LivePDVError):
    """O servidor recusou o payload."""


# =====================================================================
#  DTOs
# =====================================================================
@dataclass
class ZoopEmpresa:
    id: int
    zoopid: str
    status: str
    tipo: str
    nome: str
    cpf_cnpj: str
    nome_fantasia: str
    usuario_id: Optional[int]
    principal: bool
    bloqueio_recebimento: bool
    marketplace_id: str


@dataclass
class Fornecedor:
    id: int
    codigo: str
    cnpj: str
    nome: str
    celular: str
    email: str
    sheet_size: Optional[str]
    bloqueio_acesso: bool
    bloqueio_vendas: bool
    usuario_id: Optional[int]


@dataclass
class Marca:
    id: int
    nome_fantasia: str
    cnpj: Optional[str] = None
    razao_social: Optional[str] = None
    extras: dict = field(default_factory=dict)


# =====================================================================
#  Cliente
# =====================================================================
class LivePDVClient:
    """Cliente HTTP autenticado contra o LivePDV/Moombox."""

    DEFAULT_BASE_URL = "https://expositores.moombox.com.br"
    DEFAULT_TIMEOUT = 30
    DEFAULT_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    def __init__(self, base_url=DEFAULT_BASE_URL,
                 timeout=DEFAULT_TIMEOUT, user_agent=DEFAULT_UA):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self._csrf_token = None
        self._logged_in = False

    # ---------- helpers ----------
    def _url(self, path):
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def _soup(self, html):
        return BeautifulSoup(html, "lxml")

    def _extract_csrf(self, html):
        soup = self._soup(html)
        meta = soup.find("meta", attrs={"name": "csrf-token"})
        if not meta or not meta.get("content"):
            raise LivePDVError("CSRF token nao encontrado")
        return meta["content"]

    def _refresh_csrf(self, path="/"):
        resp = self.session.get(self._url(path), timeout=self.timeout)
        resp.raise_for_status()
        self._csrf_token = self._extract_csrf(resp.text)
        return self._csrf_token

    @property
    def csrf_token(self):
        if not self._csrf_token:
            self._refresh_csrf()
        return self._csrf_token

    # ---------- autenticacao ----------
    def login(self, username, password, remember=False):
        login_url = self._url("/user/login")
        resp = self.session.get(login_url, timeout=self.timeout)
        resp.raise_for_status()
        csrf = self._extract_csrf(resp.text)
        payload = {
            "_csrf": csrf,
            "login-form[login]": username,
            "login-form[password]": password,
            "login-form[rememberMe]": "1" if remember else "0",
        }
        resp = self.session.post(login_url, data=payload,
                                 timeout=self.timeout, allow_redirects=True)
        if resp.url.endswith("/user/login"):
            raise LivePDVAuthError("Credenciais invalidas")
        self._csrf_token = self._extract_csrf(resp.text)
        self._logged_in = True
        logger.info("Login bem-sucedido para %s", username)

    def logout(self):
        if not self._logged_in:
            return
        self.session.post(self._url("/user/logout"),
                          data={"_csrf": self.csrf_token},
                          timeout=self.timeout)
        self._logged_in = False
        self._csrf_token = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.logout()
        finally:
            self.session.close()


    # =================================================================
    #  LISTAGENS
    # =================================================================
    def listar_zoop_empresas(self, max_paginas=100):
        """Lista empresas Zoop. GET /zoop/cadastro-zoop/list-empresas"""
        empresas = []
        for page in range(1, max_paginas + 1):
            resp = self.session.get(
                self._url("/zoop/cadastro-zoop/list-empresas"),
                params={"page": page}, timeout=self.timeout)
            resp.raise_for_status()
            soup = self._soup(resp.text)
            tbody = soup.select_one("table tbody")
            if not tbody:
                break
            rows = tbody.find_all("tr")
            if not rows:
                break
            for tr in rows:
                tds = tr.find_all("td")
                if len(tds) < 12:
                    continue
                try:
                    empresas.append(ZoopEmpresa(
                        id=int(tds[0].get_text(strip=True)),
                        zoopid=tds[1].get_text(strip=True),
                        status=tds[2].get_text(strip=True),
                        tipo=tds[3].get_text(strip=True),
                        nome=tds[4].get_text(" ", strip=True),
                        cpf_cnpj=tds[5].get_text(strip=True),
                        nome_fantasia=tds[6].get_text(strip=True),
                        usuario_id=_safe_int(tds[7].get_text(strip=True)),
                        principal=_sim_nao(tds[8].get_text(strip=True)),
                        bloqueio_recebimento=_sim_nao(tds[9].get_text(strip=True)),
                        marketplace_id=tds[10].get_text(strip=True),
                    ))
                except (ValueError, IndexError) as e:
                    logger.debug("Linha zoop ignorada (%s)", e)
            if len(rows) < 50:
                break
        return empresas

    def listar_fornecedores(self, max_paginas=100):
        """Lista fornecedores. GET /configura/fornecedores/index"""
        fornecedores = []
        for page in range(1, max_paginas + 1):
            resp = self.session.get(
                self._url("/configura/fornecedores/index"),
                params={"page": page}, timeout=self.timeout)
            resp.raise_for_status()
            soup = self._soup(resp.text)
            tbody = soup.select_one("table tbody")
            if not tbody:
                break
            rows = tbody.find_all("tr")
            if not rows:
                break
            for tr in rows:
                tds = tr.find_all("td")
                if len(tds) < 10:
                    continue
                try:
                    fornecedores.append(Fornecedor(
                        id=int(tds[0].get_text(strip=True)),
                        codigo=tds[1].get_text(strip=True),
                        cnpj=tds[2].get_text(strip=True),
                        nome=tds[3].get_text(strip=True),
                        celular=tds[4].get_text(strip=True),
                        email=tds[5].get_text(strip=True),
                        sheet_size=tds[6].get_text(strip=True) or None,
                        bloqueio_acesso=_sim_nao(tds[7].get_text(strip=True)),
                        bloqueio_vendas=_sim_nao(tds[8].get_text(strip=True)),
                        usuario_id=_safe_int(tds[9].get_text(strip=True)),
                    ))
                except (ValueError, IndexError) as e:
                    logger.debug("Linha fornecedor ignorada (%s)", e)
            if len(rows) < 50:
                break
        return fornecedores


    # =================================================================
    #  BLOQUEIOS - TELA ZOOP
    # =================================================================
    def _zoop_inline_update(self, zoop_id, atributo, valor):
        """POST /zoop/cadastro-zoop/inline-update - generic toggle."""
        self._refresh_csrf("/zoop/cadastro-zoop/list-empresas")
        url = self._url("/zoop/cadastro-zoop/inline-update")
        payload = {
            "_csrf": self.csrf_token,
            "hasEditable": "1",
            "editableIndex": "0",
            "editableKey": str(zoop_id),
            "editableAttribute": atributo,
            f"CadastroZoop[0][{atributo}]": str(valor),
        }
        headers = {
            "X-CSRF-Token": self.csrf_token,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": self._url("/zoop/cadastro-zoop/list-empresas"),
        }
        resp = self.session.post(url, data=payload, headers=headers,
                                 timeout=self.timeout)
        if resp.status_code >= 400:
            raise LivePDVValidationError(
                f"inline-update falhou ({resp.status_code})")
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}

    def bloquear_recebimento_zoop(self, zoop_id, ativar=True):
        """Nivel LEVE - toggle Bloqueio Recebimento na Zoop."""
        return self._zoop_inline_update(
            zoop_id=zoop_id, atributo="bloqueio_recebimento",
            valor=1 if ativar else 0)

    def bloquear_repasse_total(self, zoop_id, ativar=True):
        """Nivel ALTO - toggle Principal. Trava repasse por completo."""
        return self._zoop_inline_update(
            zoop_id=zoop_id, atributo="principal",
            valor=0 if ativar else 1)

    # =================================================================
    #  BLOQUEIOS - TELA EXPOSITORES
    # =================================================================
    def _fornecedor_update(self, fornecedor_id, overrides):
        """GET o form atual, preserva values, aplica overrides, POSTa."""
        update_url = self._url("/configura/fornecedores/update")
        resp = self.session.get(update_url, params={"id": fornecedor_id},
                                timeout=self.timeout)
        resp.raise_for_status()
        soup = self._soup(resp.text)
        form = soup.find("form", id="w0")
        if not form:
            raise LivePDVError("Form #w0 nao encontrado")
        payload = []
        for inp in form.find_all(["input", "select", "textarea"]):
            name = inp.get("name")
            if not name:
                continue
            if inp.name == "select":
                sel = inp.find("option", selected=True)
                payload.append((name, sel.get("value", "") if sel else ""))
            elif inp.get("type") == "checkbox":
                if name in overrides:
                    continue
                if inp.has_attr("checked"):
                    payload.append((name, inp.get("value", "1")))
            elif inp.get("type") == "radio":
                if inp.has_attr("checked"):
                    payload.append((name, inp.get("value", "")))
            elif inp.get("type") == "hidden":
                payload.append((name, inp.get("value", "")))
            else:
                payload.append((name, inp.get("value", "")))
        for k, v in overrides.items():
            payload.append((k, str(v)))
        headers = {"Referer": resp.url, "X-CSRF-Token": self.csrf_token}
        resp2 = self.session.post(update_url, params={"id": fornecedor_id},
                                  data=payload, headers=headers,
                                  timeout=self.timeout, allow_redirects=True)
        if resp2.status_code >= 400:
            raise LivePDVValidationError(
                f"update fornecedor falhou ({resp2.status_code})")
        return resp2

    def bloquear_acesso_expositor(self, fornecedor_id, ativar=True):
        """Bloqueia LOGIN do expositor no portal."""
        valor = "1" if ativar else "0"
        self._fornecedor_update(fornecedor_id,
            overrides={"Fornecedores[bloqueio_acesso]": valor})
        logger.info("Fornecedor %s: bloqueio_acesso=%s", fornecedor_id, valor)
        return True

    def bloquear_vendas_expositor(self, fornecedor_id, ativar=True):
        """Bloqueia VENDAS do expositor (mas pode logar)."""
        valor = "1" if ativar else "0"
        self._fornecedor_update(fornecedor_id,
            overrides={"Fornecedores[bloqueio_vendas]": valor})
        logger.info("Fornecedor %s: bloqueio_vendas=%s", fornecedor_id, valor)
        return True


# =====================================================================
#  Helpers de parsing
# =====================================================================
def _sim_nao(s):
    return s.strip().lower() in ("sim", "1", "true", "yes")


def _safe_int(s):
    try:
        return int(s.strip())
    except (ValueError, AttributeError):
        return None


# =====================================================================
#  Exemplo de uso
# =====================================================================
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s")
    username = os.environ["LIVEPDV_USERNAME"]
    password = os.environ["LIVEPDV_PASSWORD"]
    with LivePDVClient() as client:
        client.login(username, password)
        empresas = client.listar_zoop_empresas(max_paginas=1)
        print(f"Empresas Zoop (1a pagina): {len(empresas)}")
        for e in empresas[:3]:
            print(f"  id={e.id} {e.nome_fantasia!r}")
        print("Concluido")
