# SEFAZ DF-e Client & Validador de XML NF-e (Python Desktop)

Aplicação modular em Python para validação, consulta, download e inspeção detalhada de XML de NF-e na **SEFAZ Nacional (SVRS / Distribuição DF-e)** com interface gráfica desktop (**Tkinter**) e suporte a linha de comando (CLI).

---

## Como Iniciar Rapidamente no Windows

- **Opção 1 (Sem console / Janela Silenciosa)**: Dê um duplo clique em [`app.pyw`](app.pyw).
- **Opção 2 (Arquivo Batch)**: Dê um duplo clique em [`run_app.bat`](run_app.bat).
- **Opção 3 (Terminal Python)**:
  ```bash
  python main_gui.py
  ```
- **Opção 4 (Compilar em .EXE Standalone)**:
  Execute [`build_exe.bat`](build_exe.bat) para compilar em executável único com PyInstaller.

---

## Estrutura Modular

```text
busca_XML/
│
├── sefaz_python_client/
│   ├── core/                       # Núcleo modular desacoplado
│   │   ├── constants.py            # Endpoints SEFAZ, limites e UFs
│   │   ├── models.py               # Dataclasses de Validação, Diretivas e Retornos
│   │   ├── rules.py                # Módulo 11 (cálculo de DV), validação 44 dígitos
│   │   ├── certificate.py          # Autenticação mTLS e leitura segura do certificado A1 (.pfx/.p12)
│   │   ├── registry.py             # Cache local persistente (registry.json) e controle de taxas
│   │   ├── soap_client.py          # Requisição SOAP 1.2 e descompressão gzip de nós docZip
│   │   ├── service.py              # Orquestrador do fluxo (search_nfe_xml) e autotestes
│   │   └── xml_validator.py        # Motor de validação e inspeção de XMLs de NF-e
│   │
│   ├── gui/                        # Interface Gráfica Desktop (Tkinter)
│   │   ├── app.py                  # Janela principal com sistema de abas
│   │   ├── tab_query.py            # Aba de Consulta e Download na SEFAZ (com mTLS)
│   │   └── tab_validator.py        # Aba/Janela de Validação e Inspeção de XML
│   │
│   ├── main_gui.py                 # Lançador direto da GUI
│   └── sefaz_dfe_client.py         # Ponto de entrada CLI e retrocompatibilidade
│
├── sefaz_data/                     # Diretório de dados persistentes
│   ├── registry.json               # Cache local, histórico de consultas e travas de 65 min
│   └── xmls/                       # Pasta onde os arquivos .xml baixados são gravados
│
├── tests/                          # Testes unitários e de integração
│   └── test_validator.py
│
├── main_gui.py                     # Atalho de inicialização na raiz
├── app.pyw                         # Executável silencioso para Windows (sem tela preta)
├── run_app.bat                     # Arquivo em lote para iniciar com duplo clique
└── build_exe.bat                   # Script de compilação em executável .exe
```

Consulte a documentação completa em [`sefaz_python_client/README.md`](sefaz_python_client/README.md).

