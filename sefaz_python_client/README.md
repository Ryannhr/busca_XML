# SEFAZ DF-e Client & Validador de XML NF-e (Python Desktop)

Aplicação modular em Python para validação, consulta, download e inspeção detalhada de XML de NF-e na **SEFAZ Nacional (SVRS / Distribuição DF-e)** com interface gráfica desktop (**Tkinter**) e suporte a linha de comando (CLI).

Totalmente desacoplado, com arquitetura modular, 100% de paridade das regras fiscais e salvaguardas rigorosas contra bloqueios por consumo indevido (`cStat 656` e `cStat 137`).

---

## 1. Pré-requisitos e Instalação

Instale as dependências necessárias no seu ambiente Python:

```bash
pip install httpx cryptography reportlab pillow
```

*(O `tkinter` já vem incluído por padrão nas instalações oficiais do Python para Windows).*

---

## 2. Estrutura Modular do Projeto

O projeto foi dividido em módulos independentes para facilitar manutenções, testes e extensões:

```text
busca_XML/
│
├── sefaz_python_client/
│   ├── core/                       # Núcleo de lógica e regras fiscais
│   │   ├── __init__.py             # Exportações centralizadas do pacote
│   │   ├── constants.py            # Endpoints da SEFAZ, limites e UFs
│   │   ├── models.py               # Dataclasses de Validação, Diretivas e Retornos
│   │   ├── rules.py                # Módulo 11 (cálculo de DV), validação 44 dígitos, elegibilidade
│   │   ├── certificate.py          # Autenticação mTLS e leitura segura do certificado A1 (.pfx/.p12)
│   │   ├── registry.py             # Cache local persistente (registry.json) e controle de taxas
│   │   ├── soap_client.py          # Requisição SOAP 1.2 e descompressão gzip de nós docZip
│   │   ├── service.py              # Orquestrador do fluxo (search_nfe_xml) e autotestes
│   │   ├── xml_validator.py        # Motor de validação e inspeção de XMLs de NF-e
│   │   ├── batch_processor.py      # Gestor de fila de lote e auditoria de pastas
│   │   └── danfe_generator.py      # Gerador autônomo de DANFE (PDF) com código de barras Code 128
│   │
│   ├── gui/                        # Interface Gráfica Desktop (Tkinter)
│   │   ├── __init__.py
│   │   ├── app.py                  # Janela principal com sistema de abas
│   │   ├── tab_query.py            # Aba de Consulta e Download na SEFAZ (com mTLS)
│   │   └── tab_validator.py        # Aba/Janela de Validação e Inspeção de XML
│   │
│   ├── main_gui.py                 # Lançador direto da GUI
│   ├── sefaz_dfe_client.py         # Ponto de entrada CLI e retrocompatibilidade
│   └── README.md                   # Esta documentação
│
├── sefaz_data/                     # Diretório de dados persistentes
│   ├── registry.json               # Cache local, histórico de consultas e travas de 65 min
│   └── xmls/                       # Pasta onde os arquivos .xml baixados são gravados
│
├── main_gui.py                     # Atalho de inicialização na raiz
├── app.pyw                         # Executável silencioso para Windows (sem tela preta de terminal)
├── run_app.bat                     # Arquivo em lote para iniciar com duplo clique no Windows
└── build_exe.bat                   # Script para compilar em executável standalone (.exe) via PyInstaller
```

---

## 3. Como Executar

### A. Interface Gráfica Desktop (Recomendado)

Você pode abrir a interface gráfica de 3 maneiras práticas no Windows:

1. **Duplo clique em `app.pyw`**: Abre o aplicativo silenciosamente sem janela de terminal (ideal para uso diário).
2. **Duplo clique em `run_app.bat`**: Inicia a aplicação garantindo o ambiente e diretório corretos.
3. **Pelo terminal**:
   ```bash
   python main_gui.py
   # ou
   python sefaz_python_client/sefaz_dfe_client.py --gui
   ```

---

### B. Funcionalidades da Interface Gráfica

#### 1. Aba: Consulta e Download SEFAZ
- Digitação da **Chave de Acesso** com validação em tempo real (UF, Modelo, Dígito Verificador).
- Entrada de **CNPJ do Consulente**.
- Seleção visual do **Certificado A1 (`.pfx` / `.p12`)** via botão `Procurar...`.
- Campo de **Senha mascarada** com opção de exibir/ocultar.
- Alternância entre **Ambiente de Produção** e **Homologação**.
- **Painel de Monitoramento de Cota**: Exibe o total de consultas na última hora (limite de 15/h) e o status de eventuais bloqueios da SEFAZ.
- Botão **"Validar / Dry-Run"**: Testa a validade da chave e verifica se o XML já está no cache local antes de gastar chamada.
- Botão **"Consultar SEFAZ & Baixar XML"**: Executa a requisição em segundo plano (thread) sem congelar a interface.
- **Pergunta Interativa de Geração de DANFE**: Ao concluir o download do XML da SEFAZ com sucesso, o sistema abre automaticamente um diálogo perguntando se o usuário deseja gerar o DANFE em PDF na hora.
- Botão **"Gerar DANFE (PDF)"**: Gera o Documento Auxiliar em PDF seguindo o padrão oficial da NF-e (layout oficial, canhoto de recebimento, código de barras Code 128 da chave, impostos e produtos).
- Botão **"Inspecionar XML no Validador Dedicado"**: Transfere o XML baixado diretamente para a aba de validação.

#### 2. Aba: Validador e Inspetor de XML
- Botão **"Abrir Arquivo .XML"** para selecionar qualquer XML fiscal do computador.
- Botão **"Validar Pasta Inteira (Lote)"**: Audita todos os XMLs de uma pasta e permite exportar relatório analítico em CSV.
- Botão **"📄 Gerar DANFE (PDF)"**: Gera o PDF de qualquer XML que esteja carregado ou colado no validador.
- Área de texto para **colar ou visualizar o código XML**.
- **Banner de Status Visual**:
  - Verde: XML bem-formado, chave consistente e protocolo de autorização presente.
  - Amarelo: Alerta de inconsistência ou documento sem protocolo.
  - Vermelho: Erro de sintaxe XML ou divergência matemática no dígito verificador da chave.
- **Tabela de Diagnósticos**: Lista detalhada de cada verificação realizada.
- **Decomposição da Chave de Acesso**: Extrai UF, Ano/Mês, CNPJ Emitente, Modelo, Série, Número, Tipo de Emissão e compara o Dígito Verificador do XML com o recalculo do Módulo 11.
- **Dados Comerciais e Autorização**: Identifica Razão Social e CNPJ do Emitente e Destinatário, Número da Nota, Série, Data de Emissão, Valor Total (R$), Número do Protocolo de Autorização e Assinatura Digital X.509 (`<Signature>`).
- **Visualizador Formatado**: Exibe o XML com recuo/indentação (*pretty print*) e botões para **Copiar**, **Salvar** ou **Gerar DANFE (PDF)**.

---

### C. Modo Linha de Comando (CLI)

O arquivo `sefaz_dfe_client.py` continua 100% funcional para integrações automatizadas:

```bash
# Autoteste de paridade de regras fiscais:
python sefaz_python_client/sefaz_dfe_client.py --test

# Validação e inspeção direta de um arquivo XML pelo terminal com geração de DANFE (PDF):
python sefaz_python_client/sefaz_dfe_client.py --validate-xml nota.xml --danfe danfe_nota.pdf

# Auditoria em lote de pasta de XMLs com exportação para CSV:
python sefaz_python_client/sefaz_dfe_client.py --validar-pasta caminho/para/pasta --export-csv auditoria.csv

# Consulta direta via linha de comando gerando DANFE:
python sefaz_python_client/sefaz_dfe_client.py --chave 35240112345678000195550010000000011000000019 --cnpj 12345678000195 --cert C:\certificados\empresa.pfx --senha 123456 --danfe danfe.pdf

---

## 4. Geração de Executável Binário (.EXE)

Para compilar a aplicação em um arquivo executável standalone `.exe` para distribuição no Windows:

Execute o script:
```cmd
build_exe.bat
```
O script instalará o `pyinstaller` (caso não esteja instalado) e compilará o aplicativo para a pasta `dist\SefazDFeClient\SefazDFeClient.exe`.

---

## 5. Salvaguardas Fiscais Contra Consumo Indevido (cStat 656)

1. **Validação Prévia Local**: Nenhuma requisição é enviada à SEFAZ se a chave não tiver 44 dígitos válidos e dígito verificador correto.
2. **Cache Local Inteligente**: Se a nota já foi baixada anteriormente, ela é recuperada da pasta `sefaz_data/xmls/` com consumo zero na SEFAZ.
3. **Janela Deslizante de 1 Hora**: Monitora consultas recentes para não ultrapassar o teto seguro de 15 chamadas por hora.
4. **Bloqueio Automático de 65 Minutos**: Caso a SEFAZ retorne `cStat 137` (Nenhum documento localizado) ou `cStat 656` (Consumo indevido), o sistema aplica uma trava automática e bloqueia novas tentativas até o fim da janela exigida pelo Fisco.
