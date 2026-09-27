"""
Testes automatizados para a Sincronização por NSU (distNSU) em Lote SEFAZ.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Adiciona sefaz_python_client ao path
sys.path.insert(0, str(Path(__file__).parent.parent / "sefaz_python_client"))

from core.batch_processor import NsuDocumentItem, NsuSyncManager, parse_nsu_doc_xml
from core.constants import UF_IBGE_MAP
from core.models import SefazQueryResponse
from core.registry import SefazLocalRegistry
from core.soap_client import build_soap_envelope_by_nsu


SAMPLE_PROC_NFE = """<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <NFe>
    <infNFe Id="NFe35240112345678000195550010000000011000000019" versao="4.00">
      <ide>
        <cUF>35</cUF>
        <mod>55</mod>
        <serie>1</serie>
        <nNF>9988</nNF>
        <dhEmi>2024-03-20T14:30:00-03:00</dhEmi>
      </ide>
      <emit>
        <CNPJ>12345678000195</CNPJ>
        <xNome>FORNECEDOR MATERIAIS LTDA</xNome>
      </emit>
      <total>
        <ICMSTot>
          <vNF>15250.75</vNF>
        </ICMSTot>
      </total>
    </infNFe>
  </NFe>
</nfeProc>"""

SAMPLE_PROC_CTE = """<cteProc xmlns="http://www.portalfiscal.inf.br/cte" versao="4.00">
  <CTe>
    <infCte Id="CTe35240198765432000199570010000000021000000020" versao="4.00">
      <ide>
        <cUF>35</cUF>
        <mod>57</mod>
        <serie>1</serie>
        <nCT>5544</nCT>
        <dhEmi>2024-03-20T16:00:00-03:00</dhEmi>
      </ide>
      <emit>
        <CNPJ>98765432000199</CNPJ>
        <xNome>TRANSPORTADORA RAPIDA LTDA</xNome>
      </emit>
      <vPrest>
        <vTPrest>1850.00</vTPrest>
      </vPrest>
    </infCte>
  </CTe>
</cteProc>"""

SAMPLE_RES_NFE = """<resNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">
  <chNFe>35240111222333000144550010000001231000001234</chNFe>
  <CNPJ>11222333000144</CNPJ>
  <xNome>SUPERMERCADO CENTRAL S/A</xNome>
  <IE>123456789012</IE>
  <dhEmi>2024-03-18T09:15:00-03:00</dhEmi>
  <tpNF>1</tpNF>
  <vNF>4500.00</vNF>
  <digVal>abcdef123456=</digVal>
  <dhRecbto>2024-03-18T09:16:00-03:00</dhRecbto>
  <nProt>135240001234567</nProt>
  <cSitNFe>1</cSitNFe>
</resNFe>"""

SAMPLE_EVENTO = """<procEventoNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00">
  <evento versao="1.00">
    <infEvento Id="ID1101113524011234567800019555001000000001100000001901">
      <cOrgao>35</cOrgao>
      <CNPJ>12345678000195</CNPJ>
      <chNFe>35240112345678000195550010000000011000000019</chNFe>
      <dhEvento>2024-03-21T10:00:00-03:00</dhEvento>
      <tpEvento>110111</tpEvento>
      <nSeqEvento>1</nSeqEvento>
      <detEvento versao="1.00">
        <descEvento>Cancelamento</descEvento>
        <xJust>Cancelamento por erro de faturamento</xJust>
      </detEvento>
    </infEvento>
  </evento>
</procEventoNFe>"""


class TestNsuSync(unittest.TestCase):
    def test_uf_ibge_map(self):
        """Verifica se o mapeamento de UFs contém todos os 27 estados."""
        self.assertEqual(len(UF_IBGE_MAP), 27)
        self.assertEqual(UF_IBGE_MAP["SP"], "35")
        self.assertEqual(UF_IBGE_MAP["MG"], "31")
        self.assertEqual(UF_IBGE_MAP["RJ"], "33")
        self.assertEqual(UF_IBGE_MAP["RS"], "43")

    def test_build_soap_envelope_by_nsu(self):
        """Testa montagem correta do envelope SOAP distNSU com os parâmetros exigidos pela SEFAZ."""
        xml = build_soap_envelope_by_nsu(
            cnpj="12345678000195",
            ult_nsu="150",
            c_uf_autor="35",
            is_homologation=False,
        )
        self.assertIn("<distDFeInt", xml)
        self.assertIn("<cUFAutor>35</cUFAutor>", xml)
        self.assertIn("<CNPJ>12345678000195</CNPJ>", xml)
        self.assertIn("<distNSU>", xml)
        self.assertIn("<ultNSU>000000000000150</ultNSU>", xml)
        self.assertIn("</distNSU>", xml)

    def test_parse_nsu_doc_xml_proc_nfe(self):
        """Testa parsing de NF-e completa retornada via docZip."""
        item = parse_nsu_doc_xml(schema="procNFe_v4.00.xsd", nsu="000000000000101", xml_content=SAMPLE_PROC_NFE)
        self.assertEqual(item.nsu, "000000000000101")
        self.assertEqual(item.doc_type, "NF-e (Completa)")
        self.assertEqual(item.access_key, "35240112345678000195550010000000011000000019")
        self.assertEqual(item.nfe_number, "9988")
        self.assertEqual(item.emit_name, "FORNECEDOR MATERIAIS LTDA")
        self.assertEqual(item.total_value, "15250.75")

    def test_parse_nsu_doc_xml_proc_cte(self):
        """Testa parsing de CT-e completo retornado via docZip."""
        item = parse_nsu_doc_xml(schema="procCTe_v4.00.xsd", nsu="000000000000102", xml_content=SAMPLE_PROC_CTE)
        self.assertEqual(item.nsu, "000000000000102")
        self.assertEqual(item.doc_type, "CT-e (Completo)")
        self.assertEqual(item.access_key, "35240198765432000199570010000000021000000020")
        self.assertEqual(item.nfe_number, "5544")
        self.assertEqual(item.emit_name, "TRANSPORTADORA RAPIDA LTDA")
        self.assertEqual(item.total_value, "1850.00")

    def test_parse_nsu_doc_xml_res_nfe(self):
        """Testa parsing de Resumo de NF-e (resNFe)."""
        item = parse_nsu_doc_xml(schema="resNFe_v1.01.xsd", nsu="000000000000103", xml_content=SAMPLE_RES_NFE)
        self.assertEqual(item.nsu, "000000000000103")
        self.assertEqual(item.doc_type, "Resumo NF-e")
        self.assertEqual(item.access_key, "35240111222333000144550010000001231000001234")
        self.assertEqual(item.emit_name, "SUPERMERCADO CENTRAL S/A")
        self.assertEqual(item.total_value, "4500.00")

    def test_parse_nsu_doc_xml_evento(self):
        """Testa parsing de Evento (Cancelamento, Carta de Correção, etc.)."""
        item = parse_nsu_doc_xml(schema="procEventoNFe_v1.00.xsd", nsu="000000000000104", xml_content=SAMPLE_EVENTO)
        self.assertEqual(item.nsu, "000000000000104")
        self.assertIn("Evento", item.doc_type)
        self.assertEqual(item.access_key, "35240112345678000195550010000000011000000019")

    def test_registry_nsu_persistence(self):
        """Testa o armazenamento e reset do estado do cursor NSU por CNPJ no registry.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = SefazLocalRegistry(base_dir=tmpdir)

            cnpj = "12345678000195"
            # Estado inicial
            initial_state = reg.get_nsu_state(cnpj)
            self.assertEqual(initial_state["ult_nsu"], "000000000000000")
            self.assertEqual(initial_state["max_nsu"], "000000000000000")

            # Atualiza cursor
            reg.update_nsu_state(cnpj, ult_nsu="000000000000540", max_nsu="000000000002000")
            updated = reg.get_nsu_state(cnpj)
            self.assertEqual(updated["ult_nsu"], "000000000000540")
            self.assertEqual(updated["max_nsu"], "000000000002000")
            self.assertIsNotNone(updated["last_sync"])

            # Recarrega nova instância para garantir persistência em disco
            reg2 = SefazLocalRegistry(base_dir=tmpdir)
            reloaded = reg2.get_nsu_state(cnpj)
            self.assertEqual(reloaded["ult_nsu"], "000000000000540")
            self.assertEqual(reloaded["max_nsu"], "000000000002000")

            # Reset do cursor
            reg2.reset_nsu(cnpj)
            reset_state = reg2.get_nsu_state(cnpj)
            self.assertEqual(reset_state["ult_nsu"], "000000000000000")

    def test_nsu_sync_manager_loop_and_save(self):
        """Testa a esteira do NsuSyncManager iterando lotes, salvando XMLs completos e atualizando o cursor."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = SefazLocalRegistry(base_dir=tmpdir)
            xmls_dir = reg.xml_dir

            cnpj = "12345678000195"

            # Mock responses para 2 lotes simulados da SEFAZ
            resp_batch_1 = SefazQueryResponse(
                c_stat=138,
                x_motivo="Documento localizado",
                dh_resp="2024-03-21T12:00:00",
                ult_nsu="000000000000010",
                max_nsu="000000000000020",
                documents=[
                    {"schema": "procNFe_v4.00.xsd", "nsu": "000000000000005", "xml": SAMPLE_PROC_NFE},
                    {"schema": "resNFe_v1.01.xsd", "nsu": "000000000000010", "xml": SAMPLE_RES_NFE},
                ],
                directive="OK",
                raw_response="<mockResponse/>",
            )
            resp_batch_2 = SefazQueryResponse(
                c_stat=138,
                x_motivo="Documento localizado",
                dh_resp="2024-03-21T12:01:00",
                ult_nsu="000000000000020",
                max_nsu="000000000000020",
                documents=[
                    {"schema": "procCTe_v4.00.xsd", "nsu": "000000000000020", "xml": SAMPLE_PROC_CTE},
                ],
                directive="OK",
                raw_response="<mockResponse/>",
            )

            manager = NsuSyncManager(
                registry=reg,
                cnpj=cnpj,
                cert_path="fake_cert.pfx",
                cert_password="fake",
                c_uf_autor="35",
                delay_seconds=0.01,
            )

            with patch("core.batch_processor.execute_sefaz_nsu_query", side_effect=[resp_batch_1, resp_batch_2]):
                summary = manager.sync(start_nsu="0")

            # Valida sumário retornado
            self.assertEqual(summary["batches_processed"], 2)
            self.assertEqual(summary["total_docs"], 3)
            self.assertEqual(summary["full_xmls_saved"], 2)  # 1 NF-e completa + 1 CT-e completo
            self.assertEqual(summary["resumos_count"], 1)    # 1 Resumo NF-e
            self.assertEqual(summary["ult_nsu"], "000000000000020")
            self.assertEqual(summary["max_nsu"], "000000000000020")

            # Verifica se os arquivos foram salvos fisicamente no diretório de XMLs
            nfe_file = xmls_dir / "35240112345678000195550010000000011000000019.xml"
            cte_file = xmls_dir / "35240198765432000199570010000000021000000020.xml"
            self.assertTrue(nfe_file.exists())
            self.assertTrue(cte_file.exists())

            # Verifica se o cursor final está persistido no registro
            state = reg.get_nsu_state(cnpj)
            self.assertEqual(state["ult_nsu"], "000000000000020")


if __name__ == "__main__":
    unittest.main()
