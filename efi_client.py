"""
efi_client.py
=============

Cliente Python para as APIs da Efí (antiga Gerencianet).

Cobre os dois universos da Efí:

  1) Efí Pagamentos (boletos, carnês, links de pagamento)
     - Base produção: https://api.gerencianet.com.br
     - Autenticação:  Basic Auth (client_id:client_secret) -> Bearer token

  2) Efí Pix (cobranças PIX imediatas e com vencimento)
     - Base produção: https://pix.api.efipay.com.br
     - Autenticação:  OAuth2 client_credentials + mTLS (certificado .p12/.pem)

Variáveis de ambiente esperadas (.env):

    EFI_CLIENT_ID=Client_Id_...
    EFI_CLIENT_SECRET=Client_Secret_...
    EFI_PIX_CERT_PATH=./certs/efi-prod.pem      # ou .p12 convertido
    EFI_PIX_KEY_PATH=                            # opcional se .pem combinado
    EFI_SANDBOX=false
    EFI_DIAS_ATRASO_MIN=1

Documentação oficial:
  - https://dev.efipay.com.br/docs/api-cobrancas
  - https://dev.efipay.com.br/docs/api-pix

Este módulo NÃO armazena credenciais. Sempre lê do ambiente.
"""

from __future__ import annotations

import base64
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable, Iterator, Optional

import requests


# ============================================================================
# 1) Efí Pagamentos — boletos, carnês, links
# ============================================================================
class EfiPagamentosClient:
    """Cliente para a API de Cobranças (boletos/carnês) da Efí.

    Endpoints usados:
      POST /oauth/token
      GET  /v1/charges
      GET  /v1/charge/:id
      GET  /v1/charge/:id/history
    """

    BASE_PROD = "https://api.gerencianet.com.br"
    BASE_SBX = "https://sandbox.gerencianet.com.br"

    def __init__(self, client_id: str, client_secret: str, sandbox: bool = False):
        if not client_id or not client_secret:
            raise ValueError("EFI_CLIENT_ID e EFI_CLIENT_SECRET são obrigatórios")
        self.base = self.BASE_SBX if sandbox else self.BASE_PROD
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: Optional[str] = None
        self._exp: float = 0.0
        self._session = requests.Session()

    # ------------------------------------------------------------------
    def _get_token(self) -> str:
        if self._token and time.time() < self._exp - 30:
            return self._token
        auth = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        resp = self._session.post(
            f"{self.base}/oauth/token",
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/json",
            },
            json={"grant_type": "client_credentials"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._exp = time.time() + int(data.get("expires_in", 3600))
        return self._token

    def _request(self, method: str, path: str, **kwargs) -> dict:
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._get_token()}"
        headers.setdefault("Content-Type", "application/json")
        resp = self._session.request(
            method, f"{self.base}{path}", headers=headers, timeout=60, **kwargs
        )
        resp.raise_for_status()
        return resp.json() if resp.text else {}

    # ------------------------------------------------------------------
    # READ
    # ------------------------------------------------------------------
    def listar_cobrancas(
        self,
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
        vencimento_de: Optional[str] = None,
        vencimento_ate: Optional[str] = None,
    ) -> dict:
        """GET /v1/charges (cobranças = boletos/carnês)."""
        params: dict = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if vencimento_de:
            params["vencimento_de"] = vencimento_de
        if vencimento_ate:
            params["vencimento_ate"] = vencimento_ate
        return self._request("GET", "/v1/charges", params=params)

    def listar_todas_cobrancas(self, page_size: int = 100, **filtros) -> Iterator[dict]:
        """Itera todas as cobranças paginando automaticamente."""
        offset = 0
        while True:
            page = self.listar_cobrancas(limit=page_size, offset=offset, **filtros)
            data = page.get("data", []) if isinstance(page, dict) else []
            if not data:
                break
            for item in data:
                yield item
            if len(data) < page_size:
                break
            offset += len(data)

    def get_cobranca(self, charge_id: int | str) -> dict:
        return self._request("GET", f"/v1/charge/{charge_id}")

    def get_historico(self, charge_id: int | str) -> dict:
        return self._request("GET", f"/v1/charge/{charge_id}/history")

    def listar_vencidas(self, dias_atraso_min: int = 1) -> Iterator[dict]:
        """Cobranças com status 'unpaid'/'expired' e vencimento <= hoje - N dias."""
        limite = (datetime.now() - timedelta(days=dias_atraso_min)).strftime("%Y-%m-%d")
        for status in ("unpaid", "expired"):
            try:
                for c in self.listar_todas_cobrancas(status=status):
                    venc = (
                        c.get("expire_at")
                        or c.get("vencimento")
                        or c.get("expireAt")
                    )
                    if venc and str(venc)[:10] <= limite:
                        yield c
            except requests.HTTPError:
                # Alguns ambientes não aceitam todos os filtros; ignora silenciosamente
                continue


# ============================================================================
# 2) Efí Pix — cob, cobv, pix
# ============================================================================
class EfiPixClient:
    """Cliente para a API Pix (BACEN) da Efí com mTLS.

    Endpoints usados:
      POST /oauth/token
      GET  /v2/cob
      GET  /v2/cob/:txid
      GET  /v2/cobv
      GET  /v2/cobv/:txid
      GET  /v2/pix
    """

    BASE_PROD = "https://pix.api.efipay.com.br"
    BASE_SBX = "https://pix-h.api.efipay.com.br"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        cert_path: str,
        key_path: Optional[str] = None,
        sandbox: bool = False,
    ):
        if not client_id or not client_secret:
            raise ValueError("EFI_CLIENT_ID e EFI_CLIENT_SECRET são obrigatórios")
        if not cert_path or not os.path.exists(cert_path):
            raise FileNotFoundError(
                f"Certificado PIX não encontrado em: {cert_path}"
            )
        self.base = self.BASE_SBX if sandbox else self.BASE_PROD
        self.client_id = client_id
        self.client_secret = client_secret
        # requests aceita: cert="arquivo.pem" (combinado) ou cert=(crt, key)
        self.cert = (cert_path, key_path) if key_path else cert_path
        self._token: Optional[str] = None
        self._exp: float = 0.0
        self._session = requests.Session()

    # ------------------------------------------------------------------
    def _get_token(self) -> str:
        if self._token and time.time() < self._exp - 30:
            return self._token
        auth = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        resp = self._session.post(
            f"{self.base}/oauth/token",
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/json",
            },
            json={"grant_type": "client_credentials"},
            cert=self.cert,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._exp = time.time() + int(data.get("expires_in", 3600))
        return self._token

    def _request(self, method: str, path: str, **kwargs) -> dict:
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._get_token()}"
        headers.setdefault("Content-Type", "application/json")
        resp = self._session.request(
            method,
            f"{self.base}{path}",
            headers=headers,
            cert=self.cert,
            timeout=60,
            **kwargs,
        )
        resp.raise_for_status()
        return resp.json() if resp.text else {}

    # ------------------------------------------------------------------
    @staticmethod
    def _iso_utc(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def listar_cob(
        self,
        inicio: str,
        fim: str,
        cpf: Optional[str] = None,
        cnpj: Optional[str] = None,
        status: Optional[str] = None,
        pagina: int = 0,
        itens_por_pagina: int = 100,
    ) -> dict:
        """GET /v2/cob — cobranças PIX imediatas."""
        params: dict = {
            "inicio": inicio,
            "fim": fim,
            "paginacao.paginaAtual": pagina,
            "paginacao.itensPorPagina": itens_por_pagina,
        }
        if cpf:
            params["cpf"] = "".join(filter(str.isdigit, cpf))
        if cnpj:
            params["cnpj"] = "".join(filter(str.isdigit, cnpj))
        if status:
            params["status"] = status
        return self._request("GET", "/v2/cob", params=params)

    def listar_cobv(
        self,
        inicio: str,
        fim: str,
        cnpj: Optional[str] = None,
        status: Optional[str] = None,
        pagina: int = 0,
        itens_por_pagina: int = 100,
    ) -> dict:
        """GET /v2/cobv — cobranças PIX com vencimento."""
        params: dict = {
            "inicio": inicio,
            "fim": fim,
            "paginacao.paginaAtual": pagina,
            "paginacao.itensPorPagina": itens_por_pagina,
        }
        if cnpj:
            params["cnpj"] = "".join(filter(str.isdigit, cnpj))
        if status:
            params["status"] = status
        return self._request("GET", "/v2/cobv", params=params)

    def listar_pix_recebidos(
        self, inicio: str, fim: str, **extras
    ) -> dict:
        params = {"inicio": inicio, "fim": fim, **extras}
        return self._request("GET", "/v2/pix", params=params)

    def get_cob(self, txid: str) -> dict:
        return self._request("GET", f"/v2/cob/{txid}")

    def get_cobv(self, txid: str) -> dict:
        return self._request("GET", f"/v2/cobv/{txid}")

    # ------------------------------------------------------------------
    def listar_cobv_vencidas(
        self,
        dias_atraso_min: int = 1,
        lookback_dias: int = 90,
    ) -> Iterator[dict]:
        """Itera cobranças com vencimento (cobv) que estão ATIVA e atrasadas."""
        fim = self._iso_utc(datetime.now(timezone.utc))
        inicio = self._iso_utc(
            datetime.now(timezone.utc) - timedelta(days=lookback_dias)
        )
        pagina = 0
        hoje = datetime.now().date()
        while True:
            resp = self.listar_cobv(inicio, fim, pagina=pagina)
            cobs = resp.get("cobs", []) if isinstance(resp, dict) else []
            if not cobs:
                break
            for c in cobs:
                status = c.get("status")
                cal = c.get("calendario", {}) or {}
                venc = cal.get("dataDeVencimento")
                validade = int(cal.get("validadeAposVencimento", 0) or 0)
                if not venc:
                    continue
                try:
                    venc_date = datetime.fromisoformat(venc).date()
                except ValueError:
                    continue
                dias_atraso = (hoje - venc_date).days
                if status in ("ATIVA",) and dias_atraso >= dias_atraso_min:
                    yield {**c, "_dias_atraso": dias_atraso, "_validade_apos_venc": validade}
            parametros = resp.get("parametros", {}) if isinstance(resp, dict) else {}
            total_pag = (
                parametros.get("paginacao", {}).get("quantidadeDePaginas", 1)
            )
            pagina += 1
            if pagina >= total_pag:
                break


# ============================================================================
# 3) Wrapper unificado — consolida Pagamentos + PIX por CNPJ
# ============================================================================
class EfiClient:
    """Wrapper que une EfiPagamentosClient + EfiPixClient.

    Uso típico:
        from efi_client import EfiClient
        cli = EfiClient()                              # lê .env
        inad = cli.consolidar_todos_inadimplentes()    # dict por CNPJ
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        pix_cert: Optional[str] = None,
        pix_key: Optional[str] = None,
        sandbox: Optional[bool] = None,
    ):
        client_id = client_id or os.getenv("EFI_CLIENT_ID")
        client_secret = client_secret or os.getenv("EFI_CLIENT_SECRET")
        pix_cert = pix_cert or os.getenv("EFI_PIX_CERT_PATH") or None
        pix_key = pix_key or os.getenv("EFI_PIX_KEY_PATH") or None
        if sandbox is None:
            sandbox = os.getenv("EFI_SANDBOX", "false").lower() == "true"

        self.pagamentos = EfiPagamentosClient(
            client_id, client_secret, sandbox=sandbox
        )
        self.pix: Optional[EfiPixClient] = None
        if pix_cert:
            try:
                self.pix = EfiPixClient(
                    client_id, client_secret, pix_cert, pix_key, sandbox=sandbox
                )
            except FileNotFoundError as exc:
                print(f"[efi_client] Aviso: PIX desabilitado ({exc})")

    # ------------------------------------------------------------------
    @staticmethod
    def _so_digitos(valor) -> str:
        return "".join(filter(str.isdigit, str(valor or "")))

    @staticmethod
    def _extrai_cnpj_boleto(boleto: dict) -> str:
        cust = boleto.get("customer", {}) or {}
        jur = cust.get("juridical_person", {}) or {}
        return EfiClient._so_digitos(
            jur.get("corporate_number") or cust.get("cnpj") or ""
        )

    @staticmethod
    def _extrai_cnpj_cobv(cobv: dict) -> str:
        dev = cobv.get("devedor", {}) or {}
        return EfiClient._so_digitos(dev.get("cnpj") or "")

    @staticmethod
    def _valor_boleto(boleto: dict) -> float:
        # API antiga retorna em centavos
        return float(boleto.get("total", 0)) / 100.0

    @staticmethod
    def _valor_cobv(cobv: dict) -> float:
        return float((cobv.get("valor", {}) or {}).get("original", 0))

    # ------------------------------------------------------------------
    def listar_inadimplentes_por_cnpj(
        self, cnpj: str, dias_atraso_min: Optional[int] = None
    ) -> dict:
        """Retorna {cnpj, boletos[], pix_cobv[], total_aberto} para um CNPJ."""
        if dias_atraso_min is None:
            dias_atraso_min = int(os.getenv("EFI_DIAS_ATRASO_MIN", "1"))
        alvo = self._so_digitos(cnpj)
        out = {"cnpj": alvo, "boletos": [], "pix_cobv": [], "total_aberto": 0.0}

        for b in self.pagamentos.listar_vencidas(dias_atraso_min=dias_atraso_min):
            if self._extrai_cnpj_boleto(b) == alvo:
                out["boletos"].append(b)
                out["total_aberto"] += self._valor_boleto(b)

        if self.pix:
            for c in self.pix.listar_cobv_vencidas(dias_atraso_min=dias_atraso_min):
                if self._extrai_cnpj_cobv(c) == alvo:
                    out["pix_cobv"].append(c)
                    out["total_aberto"] += self._valor_cobv(c)

        return out

    def consolidar_todos_inadimplentes(
        self, dias_atraso_min: Optional[int] = None
    ) -> dict:
        """Retorna dict {cnpj: {boletos, pix_cobv, total_aberto, dias_max}}."""
        if dias_atraso_min is None:
            dias_atraso_min = int(os.getenv("EFI_DIAS_ATRASO_MIN", "1"))
        agreg: dict = {}

        for b in self.pagamentos.listar_vencidas(dias_atraso_min=dias_atraso_min):
            doc = self._extrai_cnpj_boleto(b)
            if not doc:
                continue
            entry = agreg.setdefault(
                doc,
                {"boletos": [], "pix_cobv": [], "total_aberto": 0.0, "dias_max": 0},
            )
            entry["boletos"].append(b)
            entry["total_aberto"] += self._valor_boleto(b)

        if self.pix:
            for c in self.pix.listar_cobv_vencidas(dias_atraso_min=dias_atraso_min):
                doc = self._extrai_cnpj_cobv(c)
                if not doc:
                    continue
                entry = agreg.setdefault(
                    doc,
                    {"boletos": [], "pix_cobv": [], "total_aberto": 0.0, "dias_max": 0},
                )
                entry["pix_cobv"].append(c)
                entry["total_aberto"] += self._valor_cobv(c)
                entry["dias_max"] = max(entry["dias_max"], int(c.get("_dias_atraso", 0)))

        return agreg


# ============================================================================
# CLI rápida — útil para teste manual
# ============================================================================
if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    cli = EfiClient()
    print("[efi_client] Consolidando inadimplentes...")
    inad = cli.consolidar_todos_inadimplentes()
    print(f"  CNPJs inadimplentes: {len(inad)}")
    for cnpj, dados in sorted(
        inad.items(), key=lambda kv: kv[1]["total_aberto"], reverse=True
    )[:20]:
        print(
            f"  {cnpj}: R$ {dados['total_aberto']:>12,.2f}"
            f"  ({len(dados['boletos'])} boletos + {len(dados['pix_cobv'])} pix)"
        )
