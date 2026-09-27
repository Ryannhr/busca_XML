"""
Testes de unidade e integração para o processamento em lote.
"""

import csv
import sys
import tempfile
from pathlib import Path

# Adiciona o diretório sefaz_python_client ao path
sys.path.insert(0, str(Path(__file__).parent.parent / "sefaz_python_client"))

from core.batch_processor import (
    BatchFolderValidator,
    BatchQueryManager,
    extract_keys_from_file,
    extract_keys_from_text,
)
from core.registry import SefazLocalRegistry


def test_key_extraction():
    sample_text = """
    Chave 1: 35240112345678000195550010000000011000000019
    35240112345678000195550010000000011000000019 (duplicada)
    Outra nota fiscal: 35240112345678000195550010000000021000000020
    Chave incompleta: 123456
    """
    keys = extract_keys_from_text(sample_text)
    assert len(keys) == 2, f"Esperava 2 chaves únicas, obteve {len(keys)}"
    assert keys[0] == "35240112345678000195550010000000011000000019"
    assert keys[1] == "35240112345678000195550010000000021000000020"
    print("[OK] Extração e desduplicação de chaves em lote: OK")


def test_batch_query_manager_cache_resolution():
    with tempfile.TemporaryDirectory() as tmpdir:
        reg = SefazLocalRegistry(base_dir=tmpdir)

        # Simula uma chave salva no cache
        cached_key = "35240112345678000195550010000000011000000019"
        reg.store_xml(cached_key, "<NFe>teste</NFe>")

        # Chave válida mas não em cache (dígito verificador correto = 4)
        new_key = "35240112345678000195550010000000021000000024"

        # Chave inválida
        invalid_key = "00000000000000000000000000000000000000000000"

        manager = BatchQueryManager(
            registry=reg,
            cnpj="12345678000195",
            cert_path="",
            cert_password="",
        )
        items = manager.load_keys([cached_key, new_key, invalid_key])

        assert len(items) == 3
        assert items[0].status == "EM_CACHE"
        assert items[0].source == "CACHE_LOCAL"
        assert items[1].status == "PENDENTE"
        assert items[2].status == "ERRO"
        assert items[2].source == "FALHA_VALIDACAO"

        print("[OK] Resolução prévia de lote (Cache vs Pendente vs Inválida): OK")


def test_batch_folder_validation_and_csv_export():
    with tempfile.TemporaryDirectory() as tmpdir:
        folder = Path(tmpdir)

        # Cria 2 XMLs válidos
        xml1 = """<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe><infNFe Id="NFe35240112345678000195550010000000011000000019"><ide><nNF>101</nNF><serie>1</serie></ide><emit><CNPJ>12345678000195</CNPJ><xNome>FORNECEDOR A</xNome></emit><total><ICMSTot><vNF>500.00</vNF></ICMSTot></total></infNFe></NFe><protNFe><infProt><cStat>100</cStat><nProt>1352401</nProt></infProt></protNFe></nfeProc>"""
        xml2 = """<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe><infNFe Id="NFe35240112345678000195550010000000021000000024"><ide><nNF>102</nNF><serie>1</serie></ide><emit><CNPJ>12345678000195</CNPJ><xNome>FORNECEDOR B</xNome></emit><total><ICMSTot><vNF>750.50</vNF></ICMSTot></total></infNFe></NFe></nfeProc>"""

        (folder / "nota_101.xml").write_text(xml1, encoding="utf-8")
        (folder / "nota_102.xml").write_text(xml2, encoding="utf-8")

        # Cria 1 CT-e válido (Modelo 57)
        from test_dacte import SAMPLE_CTE_XML
        (folder / "cte_552.xml").write_text(SAMPLE_CTE_XML, encoding="utf-8")

        # Cria 1 XML corrompido
        (folder / "nota_invalida.xml").write_text("<NFe><erro>", encoding="utf-8")

        rows = BatchFolderValidator.scan_and_validate_directory(folder)
        assert len(rows) == 4

        statuses = {r.file_name: r.status for r in rows}
        assert statuses["nota_101.xml"] in ("VÁLIDO", "ALERTA")
        assert statuses["cte_552.xml"] in ("VÁLIDO", "ALERTA")
        assert statuses["nota_invalida.xml"] == "ERRO"

        # Teste de exportação para CSV
        csv_file = folder / "relatorio.csv"
        BatchFolderValidator.export_to_csv(rows, csv_file)

        assert csv_file.exists()
        csv_content = csv_file.read_text(encoding="utf-8-sig")
        assert "FORNECEDOR A" in csv_content
        assert "500,00" in csv_content
        print("[OK] Auditoria em lote de pasta e exportação de CSV: OK")

        # Teste de geração em lote de DANFEs e DACTEs em PDF para a pasta
        danfe_dir = folder / "danfes_pdf"
        danfe_res = BatchFolderValidator.generate_danfes_for_rows(rows, danfe_dir)
        assert danfe_res["generated_count"] == 3
        assert danfe_res["error_count"] == 0
        pdf_files = list(danfe_dir.glob("*.pdf"))
        assert len(pdf_files) == 3

        # Verifica se gerou tanto DANFE (para NF-e) quanto DACTE (para CT-e)
        pdf_names = [p.name for p in pdf_files]
        assert any(n.startswith("DANFE_") for n in pdf_names), "Deveria ter gerado arquivo DANFE_*.pdf"
        assert any(n.startswith("DACTE_") for n in pdf_names), "Deveria ter gerado arquivo DACTE_*.pdf"

        for pdf_p in pdf_files:
            assert pdf_p.stat().st_size > 1000  # Garante que o PDF foi gerado e tem conteúdo
        print("[OK] Conversão mista em lote de XMLs (DANFE para NF-e e DACTE para CT-e): OK")


def test_batch_gui_components():
    from gui.app import SefazApp
    app = SefazApp()
    app.update_idletasks()

    # Testa carregamento de chaves no lote da QueryTab
    sample_keys = [
        "35240112345678000195550010000000011000000019",
        "35240112345678000195550010000000021000000024",
    ]
    app.query_tab._load_batch_keys(sample_keys, "Teste")
    app.update_idletasks()
    assert len(app.query_tab.batch_items) == 2

    # Testa alternância para visualização da pasta na ValidatorTab
    app.validator_tab.sub_notebook.select(2)
    app.update_idletasks()

    app.destroy()
    print("[OK] Componentes visuais do processamento em lote da GUI: OK")


def test_certificate_prevalidation():
    from datetime import datetime, timedelta, timezone
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from core.service import search_nfe_xml
    from core.certificate import inspect_certificate

    # Gera chave e certificado expirado (ontem)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "EMPRESA TESTE EXPIRADA")]))
        .issuer_name(x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "AC TESTE")]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=30))
        .not_valid_after(now - timedelta(days=1))  # Expirou ontem!
        .sign(key, hashes.SHA256())
    )

    pfx_data = pkcs12.serialize_key_and_certificates(
        b"cert", key, cert, None,
        serialization.BestAvailableEncryption(b"senha123")
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        pfx_file = Path(tmpdir) / "cert_expirado.pfx"
        pfx_file.write_bytes(pfx_data)

        # 1. Verifica inspect_certificate
        info = inspect_certificate(pfx_file, "senha123")
        assert info["is_expired"] is True
        assert info["valid"] is False

        # 2. Testa senha errada
        try:
            inspect_certificate(pfx_file, "senha_errada")
            assert False, "Deveria ter falhado com senha errada"
        except ValueError as e:
            assert "senha" in str(e).lower()

        # 3. Testa se search_nfe_xml bloqueia e NÃO gasta chamada na SEFAZ
        reg = SefazLocalRegistry(base_dir=tmpdir)
        res = search_nfe_xml(
            access_key="35240112345678000195550010000000011000000019",
            cnpj="12345678000195",
            cert_path=str(pfx_file),
            cert_password="senha123",
            registry=reg,
        )
        assert res["status"] == "CERTIFICATE_EXPIRED"
        # Garante que ZERO requisições foram registradas
        assert len(reg.data["query_history"]) == 0
        print("[OK] Pré-validação de certificado expirado (zero consumo de cota): OK")


def test_batch_resume_and_auto_wait():
    with tempfile.TemporaryDirectory() as tmpdir:
        reg = SefazLocalRegistry(base_dir=tmpdir)

        # 1. Testa get_seconds_until_next_slot
        assert reg.get_seconds_until_next_slot() == 0

        # Registra 15 consultas para esgotar cota
        for i in range(15):
            reg.register_query_attempt(f"key_{i}", "12345678000195")

        wait_sec = reg.get_seconds_until_next_slot()
        assert wait_sec > 0, f"Deveria requerer tempo de espera, mas retornou {wait_sec}"

        # 2. Testa reset_paused_or_blocked para continuar de onde parou
        manager = BatchQueryManager(
            registry=reg,
            cnpj="12345678000195",
            cert_path="",
            cert_password="",
        )
        keys = [
            "35240112345678000195550010000000011000000019",
            "35240112345678000195550010000000021000000024",
            "35240112345678000195550010000000031000000030",
        ]
        items = manager.load_keys(keys)
        items[0].status = "CONCLUIDO"
        items[1].status = "BLOQUEADO"
        items[2].status = "PAUSADO"

        reactivated = manager.reset_paused_or_blocked()
        assert reactivated == 2, f"Esperava 2 itens reativados, obteve {reactivated}"
        assert items[0].status == "CONCLUIDO"
        assert items[1].status == "PENDENTE"
        assert items[2].status == "PENDENTE"

        print("[OK] Continuidade de lote (reset_paused_or_blocked) e cálculo de slots: OK")


if __name__ == "__main__":
    test_key_extraction()
    test_batch_query_manager_cache_resolution()
    test_batch_folder_validation_and_csv_export()
    test_batch_gui_components()
    test_certificate_prevalidation()
    test_batch_resume_and_auto_wait()
    print("\nTodos os testes de processamento em lote passaram com 100% de sucesso!")
