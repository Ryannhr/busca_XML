"""
Testes de persistência de histórico e respeito à regra de teto de consultas da SEFAZ
ao fechar e reabrir o aplicativo.
"""

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Adiciona o diretório sefaz_python_client ao path
sys.path.insert(0, str(Path(__file__).parent.parent / "sefaz_python_client"))

from core.registry import SefazLocalRegistry


def test_persistence_across_app_restarts():
    with tempfile.TemporaryDirectory() as tmpdir:
        # === SIMULAÇÃO 1: Usuário abre o app, faz 3 consultas e fecha o app ===
        reg_session_1 = SefazLocalRegistry(base_dir=tmpdir)
        reg_session_1.register_query_attempt(access_key="35240112345678000195550010000000011000000019", cnpj="12345678000195")
        reg_session_1.register_query_attempt(access_key="35240112345678000195550010000000021000000024", cnpj="12345678000195")
        reg_session_1.register_query_attempt(access_key="35240112345678000195550010000000031000000030", cnpj="12345678000195")

        s1 = reg_session_1.get_status_summary()
        assert s1["queries_last_hour"] == 3
        del reg_session_1  # Fecha o aplicativo!

        # === SIMULAÇÃO 2: Usuário reabre o aplicativo após 10 minutos ===
        reg_session_2 = SefazLocalRegistry(base_dir=tmpdir)
        s2 = reg_session_2.get_status_summary()
        assert s2["queries_last_hour"] == 3, f"Esperava 3 consultas mantidas, obteve {s2['queries_last_hour']}"
        print("[OK] Reabertura de app manteve as 3 consultas no histórico persistente: OK")

        # === SIMULAÇÃO 3: Usuário atinge o teto de 15 consultas por hora ===
        for i in range(4, 16):
            reg_session_2.register_query_attempt(access_key=f"35240112345678000195550010000000{i:02d}1000000000", cnpj="12345678000195")

        allowed, msg = reg_session_2.check_rate_limit()
        assert not allowed, "Deveria ter bloqueado após 15 consultas na hora"
        assert "Limite de consultas atingido" in msg
        assert "Próxima consulta disponível em" in msg
        del reg_session_2  # Fecha o aplicativo com limite ativo!

        # === SIMULAÇÃO 4: Usuário fecha o app e reabre tentando burlar o limite ===
        reg_session_3 = SefazLocalRegistry(base_dir=tmpdir)
        s3 = reg_session_3.get_status_summary()
        assert s3["queries_last_hour"] == 15

        allowed_after_restart, restart_msg = reg_session_3.check_rate_limit()
        assert not allowed_after_restart, "Ao reabrir o app, o limite de 15/h DEVE continuar ativo!"
        print("[OK] Limite de 15/h continuou ativo e impediu consultas mesmo após fechar e reabrir o app: OK")

        # === SIMULAÇÃO 5: Travas da SEFAZ (cStat 656 ou 137 com 65 min) ===
        from core.models import DistributionDirective
        directive_block = DistributionDirective(
            action="BLOCK",
            next_allowed_at=(datetime.now(timezone.utc) + timedelta(minutes=65)).isoformat(),
            reason="UNDUE_CONSUMPTION_BLOCK_ALL_METHODS",
        )
        reg_session_3.register_directive(directive_block)
        del reg_session_3  # Fecha o app com bloqueio da SEFAZ

        reg_session_4 = SefazLocalRegistry(base_dir=tmpdir)
        s4 = reg_session_4.get_status_summary()
        assert s4["is_blocked"] is True
        assert s4["minutes_left"] >= 60

        allowed_block, block_msg = reg_session_4.check_rate_limit()
        assert not allowed_block
        assert "Bloqueio ativo da SEFAZ" in block_msg
        print("[OK] Trava legal da SEFAZ de 65 minutos mantida perfeitamente após reinicialização: OK")


if __name__ == "__main__":
    test_persistence_across_app_restarts()
    print("\nTodos os testes de persistência entre reinicializações passaram com 100% de sucesso!")

