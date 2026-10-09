"""
DocFiller — Página de Automação
===============================
Controla o robô Selenium. Lê os fluxos YAML, inicia o preenchimento,
e exibe um terminal de log na tela. Inclui o tratamento de CAPTCHA via Modal.
"""

import sys
import glob
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                               QTextEdit, QMessageBox)

try:
    from qfluentwidgets import (TitleLabel, SubtitleLabel, BodyLabel, 
                                PrimaryPushButton, ComboBox, InfoBar)
    
    sys.path.append(str(Path(__file__).parent.parent))
    from automation.browser_gemini import BrowserManager
    from automation.form_filler_gemini import FormFiller
    from core.database_gemini import DatabaseManager
    from core.organizer_gemini import DocumentOrganizer
    from core.masker_gemini import DataMasker
    from .state_gemini import AppState
except ImportError:
    pass

# =====================================================================
# WORKER: Roda o Selenium em background
# =====================================================================
class AutomationWorker(QThread):
    log_msg = Signal(str)
    pause_requested = Signal(str) # Sinaliza a UI que precisamos de intervenção manual
    finished = Signal(bool)
    
    def __init__(self, yaml_path: str):
        super().__init__()
        self.yaml_path = yaml_path
        self.browser = None

    def run(self):
        try:
            self.log_msg.emit(">>> Iniciando Preparação dos Dados...")
            
            # 1. Puxa os dados recentes e consolida
            db = DatabaseManager()
            extractions = db.get_recent_extractions(limit=5) # No cenário real, teríamos filtro
            
            if not extractions:
                self.log_msg.emit("[ERRO] Nenhum dado extraído no banco para preencher.")
                self.finished.emit(False)
                return
                
            self.log_msg.emit(">>> Desmascarando e Consolidando Dados com Segurança LGPD...")
            masker = DataMasker()
            import json
            
            flat_payload = {}
            for row in extractions:
                try:
                    payload = json.loads(row["extracted_data_json"])
                    dados = payload.get("dados", {})
                    token_map = payload.get("token_map", {})
                    
                    # [LEGACY]: Não chamava demask_dict, repassando tokens como [NOME_001] e [CPF_001] crus para a web
                    # [GEMINI - CORREÇÃO C2]: Desmascara todos os dados em memória usando o token_map local do SQLite
                    if token_map:
                        dados = masker.demask_dict(dados, token_map)
                        
                    # [LEGACY]: Mapeava apenas 3 campos manuais de pessoa, descartando todos os outros dados
                    # [GEMINI - CORREÇÃO H2]: Achata recursivamente todos os campos (filiação, cartórios, imóveis, etc.)
                    def _flatten(d: dict, prefix: str = ""):
                        for k, v in d.items():
                            if k == "tipo": continue
                            key = f"{prefix}{k}" if prefix else k
                            if isinstance(v, dict):
                                _flatten(v, f"{key}_")
                            elif isinstance(v, list):
                                for idx, item in enumerate(v):
                                    if isinstance(item, dict):
                                        _flatten(item, f"{key}_{idx}_")
                                    elif item is not None:
                                        flat_payload[f"{key}_{idx}"] = str(item)
                                        # Atalho para primeiro item
                                        if idx == 0 and key not in flat_payload:
                                            flat_payload[key] = str(item)
                            elif v is not None:
                                flat_payload[key] = str(v)

                    _flatten(dados)

                except Exception as parse_err:
                    self.log_msg.emit(f"[AVISO] Falha ao processar dados do doc ID {row.get('id')}: {parse_err}")

            if not flat_payload:
                self.log_msg.emit("[ERRO] Nenhum dado estruturado pôde ser consolidado.")
                self.finished.emit(False)
                return

            self.log_msg.emit(f">>> {len(flat_payload)} campos desmascarados prontos para injeção. Iniciando Robô...")
            
            # 2. Inicia o Browser
            self.browser = BrowserManager(
                headless=AppState.HEADLESS_MODE, 
                profile_dir=Path("data/browser_profile").absolute()
            )
            
            # CALLBACK: Quando o browser pausar por CAPTCHA, avisa a UI
            def on_pause(reason):
                self.log_msg.emit(f"[PAUSA SOLICITADA] Motivo: {reason}")
                self.pause_requested.emit(reason) # Grita pra UI mostrar o Modal
                
            self.browser.on_pause_callback = on_pause
            
            self.browser.start()
            
            # 3. Executa o Preenchimento
            filler = FormFiller(self.browser, flat_payload)
            success = filler.run_flow(self.yaml_path)
            
            self.log_msg.emit(f">>> Automação finalizada com status: {'SUCESSO' if success else 'FALHA'}")
            
            # 4. Registra histórico com o nome do site real
            site_name = Path(self.yaml_path).stem
            db.log_form_fill(site_name, "SUCESSO" if success else "FALHA", flat_payload)
            
            self.finished.emit(success)
            
        except Exception as e:
            self.log_msg.emit(f"[ERRO FATAL] {str(e)}")
            self.finished.emit(False)
        finally:
            if self.browser:
                # self.browser.stop() # Mantém aberto para o usuário ver o resultado
                pass


# =====================================================================
# INTERFACE GRÁFICA: Automation Page
# =====================================================================
class AutomationPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("AutomationPage")
        
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(40, 40, 40, 40)
        self.vBoxLayout.setSpacing(20)
        
        self.titleLabel = TitleLabel("Automação Web", self)
        self.vBoxLayout.addWidget(self.titleLabel)
        
        # Seletor de Site
        self.vBoxLayout.addWidget(SubtitleLabel("1. Selecione o Site Alvo:"))
        self.siteCombo = ComboBox(self)
        self._load_yaml_configs()
        self.vBoxLayout.addWidget(self.siteCombo)
        
        # Botão Iniciar
        self.btnStart = PrimaryPushButton("INICIAR PREENCHIMENTO DO SITE", self)
        self.btnStart.clicked.connect(self.start_automation)
        self.vBoxLayout.addWidget(self.btnStart)
        
        # Console Log
        self.vBoxLayout.addWidget(SubtitleLabel("Terminal de Execução:"))
        self.console = QTextEdit(self)
        self.console.setReadOnly(True)
        self.console.setStyleSheet("background-color: #1e1e1e; color: #00ff00; font-family: Consolas; padding: 10px;")
        self.vBoxLayout.addWidget(self.console)
        
        self.worker = None

    def _load_yaml_configs(self):
        """Varre a pasta config/sites em busca de arquivos YAML."""
        config_dir = Path(__file__).parent.parent / "config" / "sites"
        config_dir.mkdir(parents=True, exist_ok=True)
        
        yamls = glob.glob(str(config_dir / "*.yaml"))
        if not yamls:
            self.siteCombo.addItem("Nenhum YAML encontrado.", userData=None)
            self.btnStart.setEnabled(False)
            return
            
        for y in yamls:
            name = Path(y).stem
            self.siteCombo.addItem(name, userData=y)

    def log(self, msg: str):
        """Escreve no console virtual da tela."""
        self.console.append(msg)

    def start_automation(self):
        yaml_path = self.siteCombo.currentData()
        if not yaml_path:
            return
            
        self.console.clear()
        self.btnStart.setEnabled(False)
        self.btnStart.setText("Automação em Andamento...")
        
        self.worker = AutomationWorker(yaml_path)
        self.worker.log_msg.connect(self.log)
        self.worker.pause_requested.connect(self.handle_captcha_pause)
        self.worker.finished.connect(self.automation_finished)
        
        self.worker.start()

    def handle_captcha_pause(self, reason: str):
        """Disparado quando o robô detecta CAPTCHA."""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Intervenção Manual Necessária")
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setText(
            f"O robô pausou!\nMotivo: {reason}\n\n"
            "Vá para a janela do Chrome aberta, resolva o desafio de segurança "
            "e depois clique em OK (ou feche este aviso) para retomar a automação."
        )
        # [LEGACY]: msg_box.buttonClicked.connect(lambda: self.worker.browser.resume_automation())
        # [GEMINI - CORREÇÃO H4]: msg_box.exec() bloqueia até o fechamento. Em seguida,
        # chamamos resume_automation() incondicionalmente para nunca travar a worker thread.
        msg_box.exec()
        if self.worker and self.worker.browser:
            self.worker.browser.resume_automation()

    def automation_finished(self, success: bool):
        self.btnStart.setEnabled(True)
        self.btnStart.setText("INICIAR PREENCHIMENTO DO SITE")
        
        if success:
            InfoBar.success("Sucesso", "Todos os passos da automação foram concluídos!", parent=self)
        else:
            InfoBar.error("Aviso", "A automação encerrou com erros. Verifique o terminal.", parent=self)
