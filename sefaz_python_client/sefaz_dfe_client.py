"""
SEFAZ Distribuição DF-e - Cliente em Python
===========================================
Ponto de entrada compatível para linha de comando, modo interativo e automação.
As implementações especializadas residem no pacote modular 'core/'.

Uso via Linha de Comando:
    python sefaz_dfe_client.py --chave 35240112345678000195550010000000011000000010 --cnpj 12345678000195 --cert meu_cert.pfx --senha 123456 [--homologacao]

Uso Interativo (Terminal):
    python sefaz_dfe_client.py

Interface Gráfica:
    python sefaz_dfe_client.py --gui
    (ou execute main_gui.py / run_app.bat)

Autoteste de regras fiscais:
    python sefaz_dfe_client.py --test
"""

import argparse
import json
import sys
from pathlib import Path

# Adiciona o diretório atual ao sys.path para importação de core
_CURRENT_DIR = Path(__file__).resolve().parent
if str(_CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(_CURRENT_DIR))

# Configura codificação do terminal Windows para UTF-8 seguro
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Reexportação para compatibilidade retroativa total com qualquer script dependente
from core.constants import DFE_POINT_QUERY_LIMITS, SEFAZ_ENDPOINTS, SOAP_ACTION, VALID_UF_CODES
from core.models import DistributionDirective, NfeAccessKeyValidation, SefazQueryResponse
from core.rules import (
    calculate_nfe_access_key_digit,
    classify_transport_eligibility,
    distribution_directive,
    normalize_fiscal_identity,
    validate_nfe_access_key,
)
from core.certificate import load_pkcs12_ssl_context
from core.registry import SefazLocalRegistry
from core.soap_client import build_soap_envelope_by_key, execute_sefaz_query, parse_sefaz_response
from core.service import run_self_tests, search_nfe_xml
from core.xml_validator import XmlValidationReport, inspect_and_validate_xml, validate_xml_file


def interactive_mode() -> None:
    """Menu guiado via terminal."""
    print("=" * 65)
    print("  SEFAZ DF-e - Busca e Download de XML (Cliente Python)")
    print("=" * 65)

    registry = SefazLocalRegistry()
    allowed, msg = registry.check_rate_limit()
    if not allowed:
        print(f"\n[ALERTA DE SEGURANÇA]: {msg}\n")

    access_key = input("Informe a chave de acesso da NF-e (44 números): ").strip()
    val = validate_nfe_access_key(access_key)
    if not val.valid:
        print(f"\n[ERRO]: Chave inválida -> {', '.join(val.errors)}")
        return

    print(f"\n[OK] Chave válida: {val.normalized}")
    cached = registry.get_cached_xml(val.normalized)
    if cached:
        print(f"[*] Encontrado no cache local: {cached}")
        view = input("Deseja exibir o conteúdo do XML? (s/N): ").strip().lower()
        if view == "s":
            print("\n" + cached.read_text(encoding="utf-8")[:1000] + "\n...")
        return

    cnpj = input("Informe o CNPJ do estabelecimento consulente (apenas números): ").strip()
    cert_path = input("Caminho para o certificado digital A1 (.pfx ou .p12): ").strip()
    cert_pass = input("Senha do certificado A1: ").strip()
    amb = input("Ambiente: (1) Produção | (2) Homologação [Padrão: 1]: ").strip()
    is_homologation = (amb == "2")

    print("\nConsultando a SEFAZ com autenticação mTLS...")
    result = search_nfe_xml(
        access_key=val.normalized,
        cnpj=cnpj,
        cert_path=cert_path,
        cert_password=cert_pass,
        is_homologation=is_homologation,
        registry=registry,
    )

    print("\n" + "=" * 65)
    print(f"Resultado: {result['status']}")
    print(f"Mensagem:  {result['message']}")
    if "saved_files" in result:
        print(f"Arquivos:  {', '.join(result['saved_files'])}")
    print("=" * 65)


def launch_gui() -> None:
    """Inicia a interface gráfica Tkinter."""
    from gui.app import launch_app
    launch_app()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cliente autônomo e modular em Python para busca e download de XML na SEFAZ (Distribuição DF-e).",
    )
    parser.add_argument("--chave", help="Chave de acesso de 44 dígitos da NF-e.")
    parser.add_argument("--cnpj", help="CNPJ do estabelecimento consulente.")
    parser.add_argument("--cert", help="Caminho para o certificado digital A1 (.pfx / .p12).")
    parser.add_argument("--senha", help="Senha do certificado A1.")
    parser.add_argument("--homologacao", action="store_true", help="Usar ambiente de homologação da SEFAZ.")
    parser.add_argument("--dry-run", action="store_true", help="Apenas valida a chave e regras sem conectar na SEFAZ.")
    parser.add_argument("--test", action="store_true", help="Executa autoteste de regras e paridade.")
    parser.add_argument("--gui", action="store_true", help="Abre a interface gráfica do usuário (Tkinter).")
    parser.add_argument("--validate-xml", help="Caminho para um arquivo .xml local para validação e inspeção.")
    parser.add_argument("--danfe", help="Caminho do arquivo PDF de saída para gerar o DANFE a partir do XML.")
    parser.add_argument("--validar-pasta", help="Caminho para uma pasta contendo arquivos .xml para auditoria em lote.")
    parser.add_argument("--export-csv", help="Caminho do arquivo CSV de saída para exportar a auditoria da pasta.")
    parser.add_argument("--gerar-danfes", help="Caminho da pasta onde serão salvos os DANFEs (PDF) de todos os XMLs válidos da auditoria.")
    parser.add_argument("--lote-chaves", help="Caminho para arquivo TXT ou CSV com lista de chaves de 44 dígitos.")
    parser.add_argument("--auto-wait", action="store_true", help="No processamento em lote de chaves, aguarda automaticamente a liberação de cota (15/h) e continua sozinho.")
    parser.add_argument("--sync-nsu", action="store_true", help="Executa sincronização oficial por NSU (distNSU) para baixar todos os XMLs emitidos contra o CNPJ.")
    parser.add_argument("--ult-nsu", help="NSU inicial para a sincronização (padrão: continua do último salvo no registro ou '0').")
    parser.add_argument("--uf", default="SP", help="Sigla da UF autorizadora para o cUFAutor (padrão: SP).")
    parser.add_argument("--max-lotes", type=int, default=None, help="Limite máximo de requisições de lotes NSU a executar (opcional).")

    args = parser.parse_args()

    if args.test:
        run_self_tests()
        return

    if args.gui:
        launch_gui()
        return

    if args.validar_pasta:
        from core.batch_processor import BatchFolderValidator
        print(f"\nAuditando pasta de XMLs: {args.validar_pasta}...")
        rows = BatchFolderValidator.scan_and_validate_directory(args.validar_pasta)
        print(f"Total de arquivos XML analisados: {len(rows)}")
        for r in rows:
            print(f"[{r.status}] {r.file_name} -> NF {r.nfe_number} Série {r.series} | Valor: R$ {r.total_value} | Emit: {r.emit_name[:25]}")

        if args.export_csv:
            csv_path = BatchFolderValidator.export_to_csv(rows, args.export_csv)
            print(f"\n[OK] Relatório exportado com sucesso para: {csv_path}")

        if args.gerar_danfes:
            print(f"\nGerando DANFEs em PDF para os XMLs válidos na pasta: {args.gerar_danfes}...")
            res = BatchFolderValidator.generate_danfes_for_rows(rows, args.gerar_danfes)
            print(f"[OK] Concluído: {res['generated_count']} DANFEs gerados com sucesso | {res['error_count']} erros.")
            print(f"Destino dos PDFs: {res['output_directory']}")
        return

    if args.lote_chaves:
        from core.batch_processor import BatchQueryManager, extract_keys_from_file
        if not args.cnpj or not args.cert or args.senha is None:
            print("ERRO: Para processar lote de chaves na SEFAZ, informe também --cnpj, --cert e --senha.", file=sys.stderr)
            return

        keys = extract_keys_from_file(args.lote_chaves)
        print(f"\nCarregadas {len(keys)} chaves de acesso a partir de: {args.lote_chaves}")

        manager = BatchQueryManager(
            registry=SefazLocalRegistry(),
            cnpj=args.cnpj,
            cert_path=args.cert,
            cert_password=args.senha,
            is_homologation=args.homologacao,
        )
        items = manager.load_keys(keys)

        def print_update(idx, it):
            print(f"[{idx + 1}/{len(items)}] [{it.status}] {it.access_key[:8]}...{it.access_key[-6:]} -> {it.message}")

        def on_wait(sec, msg):
            mins = sec // 60
            secs = sec % 60
            print(f"\r[AGUARDANDO LIBERAÇÃO DE COTA SEFAZ] Próximo slot em {mins:02d}:{secs:02d} min...  ", end="", flush=True)

        summary = manager.process(
            on_item_updated=print_update,
            auto_wait_quota=args.auto_wait,
            on_waiting=on_wait,
        )
        print("\n" + "=" * 60)
        print(f"Resultado do Lote: {summary['downloaded']} baixadas | {summary['cache_hits']} em cache | {summary['errors']} erros")
        print("=" * 60)
        return

    if args.sync_nsu:
        from core.batch_processor import NsuSyncManager
        from core.constants import UF_IBGE_MAP
        if not args.cnpj or not args.cert or args.senha is None:
            print("ERRO: Para sincronização por NSU, informe também --cnpj, --cert e --senha.", file=sys.stderr)
            return

        uf_ibge = UF_IBGE_MAP.get(args.uf.upper(), "35")
        registry = SefazLocalRegistry()
        print(f"\nIniciando Sincronização por NSU para o CNPJ {args.cnpj} (UF: {args.uf.upper()} - cUFAutor: {uf_ibge})...")

        manager = NsuSyncManager(
            registry=registry,
            cnpj=args.cnpj,
            cert_path=args.cert,
            cert_password=args.senha,
            c_uf_autor=uf_ibge,
            is_homologation=args.homologacao,
        )

        def on_batch(nsu_val, b_num):
            print(f"[*] Requisitando lote #{b_num} (ultNSU: {nsu_val})...")

        def on_doc(doc):
            saved = f" -> Salvo em {Path(doc.file_path).name}" if doc.file_path else ""
            print(f"  [{doc.nsu}] {doc.doc_type} | Chave: {doc.access_key[:8]}...{doc.access_key[-6:]} | {doc.emit_name[:25]} | R$ {doc.total_value}{saved}")

        def on_prog(cur_nsu, max_nsu, total):
            print(f"Progresso: NSU atual: {cur_nsu} / Max: {max_nsu} (Total docs: {total})")

        summary = manager.sync(
            start_nsu=args.ult_nsu,
            max_batches=args.max_lotes,
            on_batch_start=on_batch,
            on_doc_received=on_doc,
            on_progress=on_prog,
        )

        print("\n" + "=" * 65)
        print(f"Sincronização NSU Finalizada! (cStat {summary.get('last_c_stat', '-')})")
        print(f"• Documentos processados: {summary['total_docs']}")
        print(f"• XMLs completos salvos em disco: {summary['full_xmls_saved']}")
        print(f"• Resumos de notas: {summary['resumos_count']}")
        print(f"• Eventos: {summary['eventos_count']}")
        print(f"• Cursor atualizado: {summary['ult_nsu']} (maxNSU SEFAZ: {summary['max_nsu']})")
        print("=" * 65)
        return

    if args.validate_xml:
        report = validate_xml_file(args.validate_xml)
        print(f"\n--- RELATÓRIO DE VALIDAÇÃO: {args.validate_xml} ---")
        print(f"Sintaxe Válida:   {'SIM' if report.is_valid_syntax else 'NÃO'}")
        print(f"Tipo Documento:   <{report.doc_type}>")
        print(f"Chave de Acesso:  {report.access_key or 'Não identificada'}")
        print(f"Chave Válida:     {'SIM' if report.is_valid_key else 'NÃO'}")
        if report.nfe_data:
            print(f"NF-e:             Nº {report.nfe_data.get('nNF')} | Série {report.nfe_data.get('serie')} | Valor Total: R$ {report.nfe_data.get('vNF')}")
            print(f"Emitente:         {report.nfe_data.get('emit_nome')} ({report.nfe_data.get('emit_doc')})")
            print(f"Destinatário:     {report.nfe_data.get('dest_nome')} ({report.nfe_data.get('dest_doc')})")
        print(f"Assinatura X.509: {'SIM' if report.signature_found else 'NÃO'}")
        print("\nDiagnósticos:")
        for msg in report.messages:
            print(f" [{msg['level']}] {msg['text']}")

        if args.danfe:
            p = Path(args.validate_xml)
            if not p.exists():
                print(f"\n[ERRO]: Arquivo '{args.validate_xml}' não encontrado para gerar documento auxiliar.", file=sys.stderr)
            elif not report.is_valid_syntax:
                print(f"\n[ERRO]: Arquivo '{args.validate_xml}' não possui sintaxe XML válida para gerar documento auxiliar.", file=sys.stderr)
            else:
                from core.danfe_generator import generate_fiscal_document_pdf
                try:
                    xml_txt = p.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    xml_txt = p.read_text(encoding="latin-1")
                doc_type, pdf_path = generate_fiscal_document_pdf(xml_txt, args.danfe)
                doc_name = "DACTE" if doc_type == "CTE" else "DANFE"
                print(f"\n[OK] {doc_name} em PDF gerado com sucesso: {pdf_path}")
        return

    if args.chave and args.cnpj and (args.dry_run or (args.cert and args.senha is not None)):
        result = search_nfe_xml(
            access_key=args.chave,
            cnpj=args.cnpj,
            cert_path=args.cert or "",
            cert_password=args.senha or "",
            is_homologation=args.homologacao,
            dry_run=args.dry_run,
        )
        if args.danfe and result.get("content"):
            from core.danfe_generator import generate_fiscal_document_pdf
            doc_type, pdf_path = generate_fiscal_document_pdf(result["content"], args.danfe)
            doc_name = "DACTE" if doc_type == "CTE" else "DANFE"
            result["fiscal_pdf"] = str(pdf_path)
            print(f"\n[OK] {doc_name} em PDF gerado com sucesso: {pdf_path}")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    # Modo interativo padrão
    interactive_mode()


if __name__ == "__main__":
    main()
