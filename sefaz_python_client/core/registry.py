"""
Gerenciamento de cache local persistente e controle de taxas (cStat 656 e 137).
Garante persistência integral em disco (registry.json) mesmo que o app seja fechado e reaberto.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .constants import DFE_POINT_QUERY_LIMITS
from .models import DistributionDirective


def parse_query_timestamp(entry: Any) -> datetime | None:
    """Extrai e converte timestamp de string ISO ou dicionário."""
    if isinstance(entry, dict):
        raw = entry.get("timestamp", "")
    elif isinstance(entry, str):
        raw = entry
    else:
        return None

    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


class SefazLocalRegistry:
    """
    Armazenamento local persistente em disco (registry.json) para registrar:
    - XMLs já baixados por chave (evitando reconsultas e cStat 656);
    - Histórico de consultas na última hora com janela deslizante de 60 minutos;
    - Travas de bloqueio temporário por consumo indevido (cStat 137 ou 656).
    """

    @staticmethod
    def get_default_data_dir() -> Path:
        """
        Localiza a pasta sefaz_data canônica e absoluta do projeto.
        Garante que qualquer executável (.bat, .pyw, CLI, GUI) utilize o mesmo arquivo.
        """
        module_path = Path(__file__).resolve()
        core_dir = module_path.parent
        pkg_dir = core_dir.parent
        workspace_dir = pkg_dir.parent

        # 1. Raiz do projeto (busca_XML/sefaz_data)
        ws_data = workspace_dir / "sefaz_data"
        if ws_data.exists():
            return ws_data.resolve()

        # 2. Pasta do pacote (busca_XML/sefaz_python_client/sefaz_data)
        pkg_data = pkg_dir / "sefaz_data"
        if pkg_data.exists():
            return pkg_data.resolve()

        # 3. Padrão: cria na raiz do projeto
        return ws_data.resolve()

    def __init__(self, base_dir: Path | str | None = None):
        if base_dir is None:
            self.base_dir = self.get_default_data_dir()
        else:
            self.base_dir = Path(base_dir).resolve()

        self.xml_dir = self.base_dir / "xmls"
        self.db_file = self.base_dir / "registry.json"
        self._ensure_dirs()
        self.data = self._load()

    def _ensure_dirs(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.xml_dir.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        """Carrega os dados persistidos do arquivo JSON."""
        if self.db_file.exists():
            try:
                content = self.db_file.read_text(encoding="utf-8")
                loaded = json.loads(content)
                # Garante estrutura padrão
                loaded.setdefault("cached_keys", {})
                loaded.setdefault("query_history", [])
                loaded.setdefault("blocked_until", None)
                loaded.setdefault("block_reason", None)
                loaded.setdefault("nsu_by_cnpj", {})
                return loaded
            except Exception:
                pass

        return {
            "cached_keys": {},       # access_key -> { filepath, downloaded_at, cStat }
            "query_history": [],     # list of { timestamp, key, cnpj } or ISO strings
            "blocked_until": None,   # ISO timestamp when block expires
            "block_reason": None,
            "nsu_by_cnpj": {},       # clean_cnpj -> { ult_nsu, max_nsu, last_sync }
        }

    def _save(self) -> None:
        """Grava imediatamente no disco para persistência resiliente."""
        temp_file = self.db_file.with_suffix(".tmp")
        try:
            temp_file.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
            temp_file.replace(self.db_file)
        except Exception:
            # Fallback caso replace atômico falhe
            self.db_file.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")

    def get_cached_xml(self, access_key: str) -> Path | None:
        """Verifica se o XML da chave já foi baixado anteriormente."""
        info = self.data.get("cached_keys", {}).get(access_key)
        if info and "filepath" in info:
            p = Path(info["filepath"])
            if p.exists():
                return p
        return None

    def check_rate_limit(self) -> tuple[bool, str]:
        """
        Garante que o cliente não dispare requisições além do teto da SEFAZ
        ou antes do fim de bloqueios por consumo indevido (65 minutos).
        Mantém o histórico ativo em janela deslizante de 60 minutos.
        """
        now = datetime.now(timezone.utc)

        # 1. Verifica trava ativa (ex: cStat 656 ou 137)
        blocked_until = self.data.get("blocked_until")
        if blocked_until:
            try:
                expiry = datetime.fromisoformat(blocked_until.replace("Z", "+00:00"))
                if now < expiry:
                    minutes_left = max(1, int((expiry - now).total_seconds() / 60))
                    reason = self.data.get("block_reason", "AGUARDO_OBRIGATORIO")
                    local_time = expiry.astimezone().strftime("%H:%M:%S")
                    return False, f"Bloqueio ativo da SEFAZ ({reason}). Aguarde mais {minutes_left} minutos (até {local_time})."
                else:
                    # Trava expirou: remove bloqueio
                    self.data["blocked_until"] = None
                    self.data["block_reason"] = None
                    self._save()
            except Exception:
                pass

        # 2. Janela deslizante de 60 minutos (1 hora)
        one_hour_ago = now - timedelta(hours=1)
        one_day_ago = now - timedelta(hours=24)

        active_queries = []
        recent_history = []

        for item in self.data.get("query_history", []):
            ts = parse_query_timestamp(item)
            if ts:
                # Mantém no histórico do JSON registros das últimas 24h para auditoria
                if ts > one_day_ago:
                    recent_history.append(item)
                # Consultas ativas na janela de 1 hora
                if ts > one_hour_ago:
                    active_queries.append(item)

        # Atualiza e salva histórico limpo em disco
        if len(recent_history) != len(self.data.get("query_history", [])):
            self.data["query_history"] = recent_history
            self._save()

        max_allowed = DFE_POINT_QUERY_LIMITS["normal_per_hour"]
        if len(active_queries) >= max_allowed:
            # Identifica a consulta mais antiga para calcular quando um slot será liberado
            oldest_ts = min([parse_query_timestamp(x) for x in active_queries if parse_query_timestamp(x) is not None])
            frees_at = oldest_ts + timedelta(hours=1)
            wait_seconds = max(1, int((frees_at - now).total_seconds()))
            wait_min = max(1, (wait_seconds + 59) // 60)
            local_time = frees_at.astimezone().strftime("%H:%M")
            return False, (
                f"Limite de consultas atingido ({len(active_queries)}/{max_allowed} na última hora). "
                f"Próxima consulta disponível em {wait_min} min (às {local_time}). "
                "Histórico persistido em disco para evitar cStat 656."
            )

        return True, ""

    def get_seconds_until_next_slot(self) -> int:
        """
        Retorna o tempo em segundos até que o próximo slot de consulta seja liberado.
        Leva em consideração travas ativas da SEFAZ (blocked_until) e a janela deslizante
        de 60 minutos (teto de 15 consultas/hora). Retorna 0 se livre imediatamente.
        """
        now = datetime.now(timezone.utc)

        # 1. Trava ativa (cStat 656 ou 137)
        blocked_until = self.data.get("blocked_until")
        if blocked_until:
            try:
                expiry = datetime.fromisoformat(blocked_until.replace("Z", "+00:00"))
                if now < expiry:
                    return max(1, int((expiry - now).total_seconds()))
                else:
                    self.data["blocked_until"] = None
                    self.data["block_reason"] = None
                    self._save()
            except Exception:
                pass

        # 2. Janela de 60 minutos
        one_hour_ago = now - timedelta(hours=1)
        active_queries = []
        for item in self.data.get("query_history", []):
            ts = parse_query_timestamp(item)
            if ts and ts > one_hour_ago:
                active_queries.append(ts)

        max_allowed = DFE_POINT_QUERY_LIMITS["normal_per_hour"]
        if len(active_queries) >= max_allowed:
            oldest_ts = min(active_queries)
            frees_at = oldest_ts + timedelta(hours=1)
            wait_seconds = max(1, int((frees_at - now).total_seconds()))
            return wait_seconds

        return 0

    def get_status_summary(self) -> dict[str, Any]:
        """Retorna resumo detalhado para a interface gráfica."""
        now = datetime.now(timezone.utc)
        one_hour_ago = now - timedelta(hours=1)

        active_timestamps = []
        for item in self.data.get("query_history", []):
            ts = parse_query_timestamp(item)
            if ts and ts > one_hour_ago:
                active_timestamps.append(ts)

        blocked_until = self.data.get("blocked_until")
        is_blocked = False
        minutes_left = 0
        if blocked_until:
            try:
                expiry = datetime.fromisoformat(blocked_until.replace("Z", "+00:00"))
                if now < expiry:
                    is_blocked = True
                    minutes_left = max(1, int((expiry - now).total_seconds() / 60))
            except Exception:
                pass

        # Cálculo do próximo slot liberado
        next_slot_str = "Disponível agora"
        next_slot_min = 0
        max_allowed = DFE_POINT_QUERY_LIMITS["normal_per_hour"]

        if len(active_timestamps) >= max_allowed:
            oldest_ts = min(active_timestamps)
            frees_at = oldest_ts + timedelta(hours=1)
            wait_sec = max(1, int((frees_at - now).total_seconds()))
            next_slot_min = max(1, (wait_sec + 59) // 60)
            local_time = frees_at.astimezone().strftime("%H:%M")
            next_slot_str = f"Em {next_slot_min} min (às {local_time})"
        elif active_timestamps:
            oldest_ts = min(active_timestamps)
            frees_at = oldest_ts + timedelta(hours=1)
            wait_sec = max(1, int((frees_at - now).total_seconds()))
            next_slot_min = max(1, (wait_sec + 59) // 60)
            local_time = frees_at.astimezone().strftime("%H:%M")
            next_slot_str = f"Livre ({len(active_timestamps)}/{max_allowed}) - Reseta às {local_time}"

        return {
            "queries_last_hour": len(active_timestamps),
            "max_queries_allowed": max_allowed,
            "is_blocked": is_blocked,
            "blocked_until": blocked_until if is_blocked else None,
            "block_reason": self.data.get("block_reason") if is_blocked else None,
            "minutes_left": minutes_left,
            "next_slot_str": next_slot_str,
            "next_slot_min": next_slot_min,
            "total_cached_keys": len(self.data.get("cached_keys", {})),
            "database_file": str(self.db_file.resolve()),
        }

    def register_query_attempt(self, access_key: str = "", cnpj: str = "") -> None:
        """Registra uma tentativa de consulta e persiste imediatamente em disco."""
        now_iso = datetime.now(timezone.utc).isoformat()
        entry = {
            "timestamp": now_iso,
            "key": access_key,
            "cnpj": cnpj,
        }
        self.data.setdefault("query_history", []).append(entry)
        self._save()

    def register_directive(self, directive: DistributionDirective) -> None:
        """Registra diretivas de bloqueio (cStat 137 ou 656) e persiste no disco."""
        if directive.action in ("WAIT", "BLOCK") and directive.next_allowed_at:
            self.data["blocked_until"] = directive.next_allowed_at
            self.data["block_reason"] = directive.reason
        elif directive.action == "PROCESS":
            self.data["blocked_until"] = None
            self.data["block_reason"] = None
        self._save()

    def store_xml(self, access_key: str, xml_content: str, c_stat: int = 138) -> Path:
        """Salva o arquivo XML no disco e grava o registro em registry.json."""
        filename = f"{access_key}.xml"
        file_path = self.xml_dir / filename
        file_path.write_text(xml_content, encoding="utf-8")
        self.data.setdefault("cached_keys", {})[access_key] = {
            "filepath": str(file_path.resolve()),
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "cStat": c_stat,
        }
        self._save()
        return file_path

    def get_nsu_state(self, cnpj: str) -> dict[str, Any]:
        """Recupera o cursor de NSU persistido para o CNPJ."""
        clean = re.sub(r"\D", "", cnpj)
        nsu_dict = self.data.setdefault("nsu_by_cnpj", {})
        return nsu_dict.get(clean, {
            "ult_nsu": "000000000000000",
            "max_nsu": "000000000000000",
            "last_sync": None,
        })

    def update_nsu_state(self, cnpj: str, ult_nsu: str | int, max_nsu: str | int) -> None:
        """Salva o progresso da sincronização de NSU no disco."""
        clean = re.sub(r"\D", "", cnpj)
        nsu_dict = self.data.setdefault("nsu_by_cnpj", {})
        nsu_dict[clean] = {
            "ult_nsu": str(ult_nsu).zfill(15),
            "max_nsu": str(max_nsu).zfill(15),
            "last_sync": datetime.now(timezone.utc).isoformat(),
        }
        self._save()

    def reset_nsu(self, cnpj: str) -> None:
        """Reinicia o ponteiro de NSU para zero."""
        clean = re.sub(r"\D", "", cnpj)
        nsu_dict = self.data.setdefault("nsu_by_cnpj", {})
        if clean in nsu_dict:
            nsu_dict[clean]["ult_nsu"] = "000000000000000"
            self._save()

