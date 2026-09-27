"""
Testes unitários para o gerador de DACTE (CT-e Modelo 57) e despachante fiscal automático.
"""

import sys
import tempfile
from pathlib import Path

# Garante acesso aos módulos do cliente
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sefaz_python_client"))

from core.dacte_generator import extract_dacte_data, generate_dacte_pdf
from core.danfe_generator import detect_document_type, generate_fiscal_document_pdf


SAMPLE_CTE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<cteProc xmlns="http://www.portalfiscal.inf.br/cte" versao="4.00">
  <CTe>
    <infCte Id="CTe52260922686175001370570090000005521002455603" versao="4.00">
      <ide>
        <cUF>52</cUF>
        <cCT>00245560</cCT>
        <CFOP>5353</CFOP>
        <natOp>PREST. DE SERV DE TRANSPORTE A ESTAB.</natOp>
        <mod>57</mod>
        <serie>9</serie>
        <nCT>552</nCT>
        <dhEmi>2026-09-18T09:39:19-03:00</dhEmi>
        <tpImp>1</tpImp>
        <tpEmis>1</tpEmis>
        <cDV>3</cDV>
        <tpAmb>1</tpAmb>
        <tpCTe>0</tpCTe>
        <procEmi>0</procEmi>
        <verProc>4.0.0</verProc>
        <indGlobalizado>0</indGlobalizado>
        <modal>01</modal>
        <tpServ>0</tpServ>
        <cMunIni>5218805</cMunIni>
        <xMunIni>RIO VERDE</xMunIni>
        <UFIni>GO</UFIni>
        <cMunFim>5207402</cMunFim>
        <xMunFim>EDEALINA</xMunFim>
        <UFFim>GO</UFFim>
        <toma3>
          <toma>0</toma>
        </toma3>
      </ide>
      <emit>
        <CNPJ>22686175001370</CNPJ>
        <IE>201749106</IE>
        <xNome>CARVALHO COMERCIO E TRANSPORTES LTDA - POSSE</xNome>
        <enderEmit>
          <xLgr>RODOVIA BR-060, SN KM 388, SALA 152</xLgr>
          <nro>SN</nro>
          <xBairro>RIO VERDE</xBairro>
          <cMun>5218805</cMun>
          <xMun>RIO VERDE</xMun>
          <CEP>75900031</CEP>
          <UF>GO</UF>
          <fone>07736398111</fone>
        </enderEmit>
      </emit>
      <rem>
        <CNPJ>01849036002231</CNPJ>
        <IE>109418581</IE>
        <xNome>PROTEC PRODUTOS AGRICOLAS LTDA</xNome>
        <enderReme>
          <xLgr>AV SAO FELIX</xLgr>
          <nro>SN</nro>
          <xCpl>QUADRA 29 LOTE 18/19</xCpl>
          <xBairro>JARDIM SANTA PAULA</xBairro>
          <cMun>5208905</cMun>
          <xMun>GOIATUBA</xMun>
          <CEP>75600000</CEP>
          <UF>GO</UF>
          <fone>03432567400</fone>
        </enderReme>
      </rem>
      <dest>
        <CPF>83660828149</CPF>
        <IE>115857290</IE>
        <xNome>ANNA CAROLYNNA DE REZENDE SOUZA</xNome>
        <enderDest>
          <xLgr>RODOVIA GO 215, 2 - SN, A EDEA KM 12 A ESQUERDA</xLgr>
          <nro>SN</nro>
          <cMun>5207402</cMun>
          <xMun>EDEALINA</xMun>
          <CEP>75945000</CEP>
          <UF>GO</UF>
          <fone>03333333333</fone>
        </enderDest>
      </dest>
      <exped>
        <CNPJ>02227264001007</CNPJ>
        <IE>108342964</IE>
        <xNome>ANDALI</xNome>
        <enderExped>
          <xLgr>RODOVIA ROD.BR 452 KM 21,5 A ESQUERDA</xLgr>
          <nro>SN</nro>
          <cMun>5218805</cMun>
          <xMun>RIO VERDE</xMun>
          <CEP>75913899</CEP>
          <UF>GO</UF>
        </enderExped>
      </exped>
      <receb>
        <CPF>83660828149</CPF>
        <IE>115857290</IE>
        <xNome>ANNA CAROLYNNA DE REZENDE SOUZA</xNome>
        <enderReceb>
          <xLgr>RODOVIA GO 215, 2 - SN, A EDEA KM 12 A ESQUERDA</xLgr>
          <nro>SN</nro>
          <cMun>5207402</cMun>
          <xMun>EDEALINA</xMun>
          <CEP>75945000</CEP>
          <UF>GO</UF>
        </enderReceb>
      </receb>
      <vPrest>
        <vTPrest>3450.00</vTPrest>
        <vRec>3450.00</vRec>
        <Comp>
          <xNome>FRETE</xNome>
          <vComp>3450.00</vComp>
        </Comp>
        <Comp>
          <xNome>Valor IBS UF</xNome>
          <vComp>3.45</vComp>
        </Comp>
        <Comp>
          <xNome>Valor CBS</xNome>
          <vComp>31.05</vComp>
        </Comp>
      </vPrest>
      <imp>
        <ICMS>
          <ICMS45>
            <CST>40</CST>
          </ICMS45>
        </ICMS>
      </imp>
      <infCTeNorm>
        <infCarga>
          <vCarga>100500.00</vCarga>
          <proPred>FERT. GRAN. CIBRAFERTIL CLORETO DE</proPred>
          <xOutCat>BIG BAG</xOutCat>
          <infQ>
            <cUnid>01</cUnid>
            <tpMed>KG</tpMed>
            <qCarga>30000.0000</qCarga>
          </infQ>
        </infCarga>
        <infDoc>
          <infNFe>
            <chave>52260901849036002231550010000128331024426272</chave>
          </infNFe>
        </infDoc>
        <seg>
          <respSeg>5</respSeg>
          <xSeg>MAPFRE SEGUROS GERAIS S.A.</xSeg>
          <nApol>55/260/2010900000655</nApol>
          <vAver>100500.00</vAver>
          <nAver>062381026226861750013705700900000552108</nAver>
        </seg>
        <rodo>
          <RNTRC>048824131</RNTRC>
          <veic>
            <placa>KEG4H45</placa>
            <RENAVAM>00736498583</RENAVAM>
            <UF>GO</UF>
          </veic>
          <moto>
            <xNome>JEREMIAS DA SILVA PINHEIRO</xNome>
            <CPF>59119454104</CPF>
          </moto>
        </rodo>
      </infCTeNorm>
      <compl>
        <xObs>Transporte Subcontratado com JEREMIAS DA SILVA PINHEIRO, CPF: 59119454104. ISENTO CONF. ARTIGO 70, INCISO XLI, DO ANEXO IX DO RCTE/GO</xObs>
      </compl>
    </infCte>
  </CTe>
  <protCTe versao="4.00">
    <infProt>
      <tpAmb>1</tpAmb>
      <verAplic>4.0.0</verAplic>
      <chCTe>52260922686175001370570090000005521002455603</chCTe>
      <dhRecbto>2026-09-18T09:39:19-03:00</dhRecbto>
      <nProt>352260166254479</nProt>
      <cStat>100</cStat>
      <xMotivo>Autorizado o uso do CT-e</xMotivo>
    </infProt>
  </protCTe>
</cteProc>
"""


def test_dacte_extraction():
    data = extract_dacte_data(SAMPLE_CTE_XML)

    assert data["key"] == "52260922686175001370570090000005521002455603"
    assert data["nCT"] == "552"
    assert data["serie"] == "9"
    assert data["modal"] == "RODOVIÁRIO"
    assert data["tpCTe"] == "NORMAL"
    assert data["cfop"] == "5353"
    assert data["xMunIni"] == "RIO VERDE"
    assert data["xMunFim"] == "EDEALINA"
    assert "CARVALHO COMERCIO" in data["emit"]["nome"]
    assert "PROTEC PRODUTOS" in data["rem"]["nome"]
    assert "ANNA CAROLYNNA" in data["dest"]["nome"]
    assert data["tomador_tipo"] == "REMETENTE"
    assert data["vTPrest"] == "3.450,00"
    assert len(data["componentes"]) == 3
    assert "40 - ICMS Isenção" in data["cst_desc"]
    assert data["proPred"] == "FERT. GRAN. CIBRAFERTIL CLORETO DE"
    assert len(data["docs_originarios"]) == 1
    assert data["docs_originarios"][0]["tipo"] == "NFE"
    assert data["rntrc"] == "048824131"
    assert len(data["veiculos"]) == 1
    assert data["veiculos"][0]["placa"] == "KEG4H45"

    print("[OK] Extração de campos do CT-e (DACTE): OK")


def test_dacte_pdf_generation():
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        pdf_path = Path(tf.name)

    try:
        out_file = generate_dacte_pdf(SAMPLE_CTE_XML, output_pdf_path=pdf_path)
        assert out_file.exists()
        size = out_file.stat().st_size
        assert size > 3000, f"PDF gerado muito pequeno ({size} bytes)"

        with open(out_file, "rb") as f:
            header = f.read(5)
            assert header == b"%PDF-", "Cabeçalho do PDF inválido"

        print(f"[OK] Geração do DACTE em PDF com sucesso ({size} bytes): OK")
    finally:
        if pdf_path.exists():
            pdf_path.unlink()


def test_fiscal_document_dispatcher():
    # 1. Teste de detecção pela chave
    key_nfe = "35240112345678000195550010000000011000000019"  # mod 55
    key_cte = "52260922686175001370570090000005521002455603"  # mod 57

    assert detect_document_type(key_nfe) == "NFE"
    assert detect_document_type(key_cte) == "CTE"

    # 2. Teste de detecção pelo XML
    assert detect_document_type(SAMPLE_CTE_XML) == "CTE"
    sample_nfe_xml = """<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe><infNFe Id="NFe35240112345678000195550010000000011000000019"><ide><nNF>1</nNF></ide></infNFe></NFe></nfeProc>"""
    assert detect_document_type(sample_nfe_xml) == "NFE"

    # 3. Teste de geração pelo despachante
    with tempfile.TemporaryDirectory() as tmpdir:
        cte_pdf = Path(tmpdir) / "teste_cte.pdf"
        doc_type, out_p = generate_fiscal_document_pdf(SAMPLE_CTE_XML, cte_pdf)
        assert doc_type == "CTE"
        assert out_p.exists()
        assert out_p.stat().st_size > 3000

    print("[OK] Despachante inteligente e detecção automática de NF-e vs CT-e: OK")


if __name__ == "__main__":
    test_dacte_extraction()
    test_dacte_pdf_generation()
    test_fiscal_document_dispatcher()
    print("\nTodos os testes de DACTE (CT-e) passaram com 100% de sucesso!")

