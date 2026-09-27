"""
Testes de unidade para o motor de validação de XML de NF-e.
"""

import sys
from pathlib import Path

# Adiciona sefaz_python_client ao path
sys.path.insert(0, str(Path(__file__).parent.parent / "sefaz_python_client"))

from core.xml_validator import format_xml_string, inspect_and_validate_xml


def test_valid_nfe_xml():
    sample_xml = """<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
      <NFe>
        <infNFe Id="NFe35240112345678000195550010000000011000000019" versao="4.00">
          <ide>
            <cUF>35</cUF>
            <cNF>00000001</cNF>
            <natOp>VENDA DE MERCADORIAS</natOp>
            <mod>55</mod>
            <serie>1</serie>
            <nNF>12345</nNF>
            <dhEmi>2024-01-15T10:30:00-03:00</dhEmi>
            <tpNF>1</tpNF>
          </ide>
          <emit>
            <CNPJ>12345678000195</CNPJ>
            <xNome>DISTRIBUIDORA EXEMPLO S/A</xNome>
            <xFant>EXEMPLO DISTRIBUICAO</xFant>
            <enderEmit>
              <xMun>São Paulo</xMun>
              <UF>SP</UF>
            </enderEmit>
          </emit>
          <dest>
            <CNPJ>98765432000100</CNPJ>
            <xNome>CLIENTE DESTINO LTDA</xNome>
            <enderDest>
              <xMun>Campinas</xMun>
              <UF>SP</UF>
            </enderDest>
          </dest>
          <total>
            <ICMSTot>
              <vProd>2500.00</vProd>
              <vNF>2500.00</vNF>
              <vICMS>450.00</vICMS>
            </ICMSTot>
          </total>
          <transp>
            <modFrete>0</modFrete>
            <transporta>
              <CNPJ>11222333000144</CNPJ>
              <xNome>TRANSPORTADORA RAPIDA LTDA</xNome>
            </transporta>
          </transp>
        </infNFe>
      </NFe>
      <protNFe versao="4.00">
        <infProt>
          <tpAmb>1</tpAmb>
          <verAplic>SVRS2024</verAplic>
          <chNFe>35240112345678000195550010000000011000000019</chNFe>
          <dhRecbto>2024-01-15T10:31:00-03:00</dhRecbto>
          <nProt>135240000000001</nProt>
          <cStat>100</cStat>
          <xMotivo>Autorizado o uso da NF-e</xMotivo>
        </infProt>
      </protNFe>
    </nfeProc>"""

    report = inspect_and_validate_xml(sample_xml)
    assert report.is_valid_syntax, "Sintaxe deve ser válida"
    assert report.is_valid_key, "Chave deve ser válida"
    assert report.access_key == "35240112345678000195550010000000011000000019"
    assert report.doc_type == "nfeProc"
    assert report.nfe_data["nNF"] == "12345"
    assert report.nfe_data["vNF"] == "2500.00"
    assert report.nfe_data["emit_nome"] == "DISTRIBUIDORA EXEMPLO S/A"
    assert report.authorization_data["cStat"] == "100"
    assert report.key_details["uf_code"] == "35"
    assert report.key_details["dv_match"] is True

    print("[OK] Teste de validação de XML de NF-e completa passou com sucesso!")


def test_invalid_syntax():
    invalid_xml = "<nfeProc><NFe><infNFe></NFe>"  # Tag mal fechada
    report = inspect_and_validate_xml(invalid_xml)
    assert not report.is_valid_syntax
    assert any(m["level"] == "ERROR" for m in report.messages)
    print("[OK] Detecção de erro de sintaxe XML passou com sucesso!")


def test_invalid_check_digit_in_xml():
    # Chave com dígito alterado (era 9, vira 8)
    invalid_key_xml = """<NFe><infNFe Id="NFe35240112345678000195550010000000011000000018"><ide><nNF>100</nNF></ide></infNFe></NFe>"""
    report = inspect_and_validate_xml(invalid_key_xml)
    assert report.is_valid_syntax
    assert not report.is_valid_key
    assert report.key_details["dv_match"] is False
    print("[OK] Detecção de dígito verificador inválido no XML passou com sucesso!")


def test_gui_app():
    from gui.app import SefazApp
    app = SefazApp()
    app.update_idletasks()
    
    sample_xml = """<NFe><infNFe Id="NFe35240112345678000195550010000000011000000019"><ide><nNF>10</nNF></ide></infNFe></NFe>"""
    app.validator_tab.load_xml_content(sample_xml)
    app.update_idletasks()
    assert app.validator_tab.current_report is not None
    assert app.validator_tab.current_report.is_valid_syntax
    assert app.validator_tab.current_report.is_valid_key
    app.destroy()
    print("[OK] Teste de inicializacao e interacao da GUI Tkinter passou com sucesso!")


if __name__ == "__main__":
    test_valid_nfe_xml()
    test_invalid_syntax()
    test_invalid_check_digit_in_xml()
    test_gui_app()
    print("\nTodos os testes unitarios e de interface passaram com 100% de sucesso!")

