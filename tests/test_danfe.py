"""
Testes automatizados para geração de DANFE em PDF.
"""

import sys
import tempfile
from pathlib import Path

# Adiciona sefaz_python_client ao path
sys.path.insert(0, str(Path(__file__).parent.parent / "sefaz_python_client"))

from core.danfe_generator import extract_danfe_data, generate_danfe_pdf


SAMPLE_NFE_XML = """<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <NFe>
    <infNFe Id="NFe35240112345678000195550010000000011000000019" versao="4.00">
      <ide>
        <cUF>35</cUF>
        <cNF>00000001</cNF>
        <natOp>VENDA DE MERCADORIAS ADQUIRIDAS DE TERCEIROS</natOp>
        <mod>55</mod>
        <serie>1</serie>
        <nNF>12345</nNF>
        <dhEmi>2024-01-15T10:30:00-03:00</dhEmi>
        <dhSaiEnt>2024-01-15T11:00:00-03:00</dhSaiEnt>
        <tpNF>1</tpNF>
      </ide>
      <emit>
        <CNPJ>12345678000195</CNPJ>
        <xNome>DISTRIBUIDORA EXEMPLO DE PRODUTOS S/A</xNome>
        <xFant>EXEMPLO DISTRIBUICAO</xFant>
        <enderEmit>
          <xLgr>Av. Paulista</xLgr>
          <nro>1000</nro>
          <xCpl>Conj 101</xCpl>
          <xBairro>Bela Vista</xBairro>
          <xMun>São Paulo</xMun>
          <UF>SP</UF>
          <CEP>01310100</CEP>
          <fone>1133334444</fone>
        </enderEmit>
        <IE>123456789012</IE>
        <CRT>3</CRT>
      </emit>
      <dest>
        <CNPJ>98765432000100</CNPJ>
        <xNome>CLIENTE DESTINATARIO EXEMPLO LTDA</xNome>
        <enderDest>
          <xLgr>Rua das Flores</xLgr>
          <nro>50</nro>
          <xBairro>Centro</xBairro>
          <xMun>Campinas</xMun>
          <UF>SP</UF>
          <CEP>13010000</CEP>
          <fone>1932321122</fone>
        </enderDest>
        <IE>987654321098</IE>
      </dest>
      <total>
        <ICMSTot>
          <vBC>2500.00</vBC>
          <vICMS>450.00</vICMS>
          <vBCST>0.00</vBCST>
          <vST>0.00</vST>
          <vProd>2500.00</vProd>
          <vFrete>50.00</vFrete>
          <vSeg>0.00</vSeg>
          <vDesc>0.00</vDesc>
          <vOutro>0.00</vOutro>
          <vIPI>0.00</vIPI>
          <vNF>2550.00</vNF>
        </ICMSTot>
      </total>
      <transp>
        <modFrete>0</modFrete>
        <transporta>
          <CNPJ>11222333000144</CNPJ>
          <xNome>TRANSPORTADORA RAPIDA LTDA</xNome>
          <IE>111222333444</IE>
          <xEnder>Rodovia Anhanguera, km 100</xEnder>
          <xMun>Campinas</xMun>
          <UF>SP</UF>
        </transporta>
        <veicTransp>
          <placa>ABC1D23</placa>
          <UF>SP</UF>
        </veicTransp>
        <vol>
          <qVol>10</qVol>
          <esp>VOLUMES</esp>
          <pesoB>150.500</pesoB>
          <pesoL>140.000</pesoL>
        </vol>
      </transp>
      <det nItem="1">
        <prod>
          <cProd>PRD-001</cProd>
          <xProd>NOTEBOOK CORPORATIVO INTEL I7 16GB SSD 512GB</xProd>
          <NCM>84713012</NCM>
          <CFOP>5102</CFOP>
          <uCom>UN</uCom>
          <qCom>1.0000</qCom>
          <vUnCom>2000.00</vUnCom>
          <vProd>2000.00</vProd>
        </prod>
        <imposto>
          <ICMS>
            <ICMS00>
              <orig>0</orig>
              <CST>00</CST>
              <vBC>2000.00</vBC>
              <pICMS>18.00</pICMS>
              <vICMS>360.00</vICMS>
            </ICMS00>
          </ICMS>
        </imposto>
      </det>
      <det nItem="2">
        <prod>
          <cProd>PRD-002</cProd>
          <xProd>MONITOR LED 27 POL FULL HD HDMI</xProd>
          <NCM>85285200</NCM>
          <CFOP>5102</CFOP>
          <uCom>UN</uCom>
          <qCom>1.0000</qCom>
          <vUnCom>500.00</vUnCom>
          <vProd>500.00</vProd>
        </prod>
        <imposto>
          <ICMS>
            <ICMS00>
              <orig>0</orig>
              <CST>00</CST>
              <vBC>500.00</vBC>
              <pICMS>18.00</pICMS>
              <vICMS>90.00</vICMS>
            </ICMS00>
          </ICMS>
        </imposto>
      </det>
      <infAdic>
        <infCpl>DOCUMENTO EMITIDO POR ME OU EPP OPTANTE PELO SIMPLES NACIONAL. VALOR APROX TRIBUTOS FEDERAIS R$ 320,00 ESTADUAIS R$ 450,00 FONTE IBPT.</infCpl>
      </infAdic>
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


def test_extract_danfe_data():
    data = extract_danfe_data(SAMPLE_NFE_XML)
    assert data["nNF"] == "12345"
    assert data["serie"] == "1"
    assert data["key"] == "35240112345678000195550010000000011000000019"
    assert data["emit"]["nome"] == "DISTRIBUIDORA EXEMPLO DE PRODUTOS S/A"
    assert data["dest"]["nome"] == "CLIENTE DESTINATARIO EXEMPLO LTDA"
    assert data["totais"]["vNF"] == "2550.00"
    assert len(data["items"]) == 2
    assert data["items"][0]["cProd"] == "PRD-001"
    assert data["prot"]["nProt"] == "135240000000001"
    print("[OK] Extração de dados da NF-e para o DANFE: OK")


def test_generate_danfe_pdf():
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "danfe_teste.pdf"
        out = generate_danfe_pdf(SAMPLE_NFE_XML, output_pdf_path=pdf_path)

        assert out.exists()
        assert out.stat().st_size > 1000

        # Verifica cabeçalho PDF
        pdf_bytes = out.read_bytes()
        assert pdf_bytes.startswith(b"%PDF-"), "Arquivo gerado deve ser um PDF válido"
        print(f"[OK] Geração do DANFE em PDF com sucesso ({out.stat().st_size} bytes): OK")


if __name__ == "__main__":
    test_extract_danfe_data()
    test_generate_danfe_pdf()
    print("\nTodos os testes do DANFE em PDF passaram com 100% de sucesso!")

