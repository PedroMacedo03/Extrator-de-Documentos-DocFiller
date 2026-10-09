"""
DocFiller — Motor de Preenchimento (Form Filler)
================================================

Lê os arquivos YAML de configuração de cada site e executa
os passos da automação. Integra com o BrowserManager para respeitar
as pausas de CAPTCHA e com o FieldHandlers para digitar os dados.
"""

import time
from typing import Dict, Any
import yaml

try:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from .browser_gemini import BrowserManager
    from .field_handlers_gemini import FieldHandlers
except ImportError:
    pass

class FormFiller:
    """Motor declarativo de preenchimento baseado em YAML."""

    def __init__(self, browser: 'BrowserManager', payload: Dict[str, Any]):
        self.browser = browser
        self.payload = payload  # Dicionário COM OS DADOS REAIS desmascarados
        # [LEGACY]: self.driver = browser.driver
        # Se o browser ainda não tivesse sido iniciado, self.driver ficava None para sempre,
        # gerando TypeError: driver must be an instance of WebDriver, got NoneType.
        # [GEMINI - CORREÇÃO C1]: Agora gerenciado via @property dinâmico abaixo.

    @property
    def driver(self):
        """[GEMINI - CORREÇÃO C1]: Acesso dinâmico ao driver atualizado do BrowserManager."""
        return self.browser.driver

    def load_config(self, yaml_path: str) -> Dict[str, Any]:
        """Carrega e parseia o arquivo YAML de configuração do site."""
        with open(yaml_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def run_flow(self, yaml_path: str) -> bool:
        """Executa todos os steps definidos no YAML sequencialmente."""
        config = self.load_config(yaml_path)
        site_name = config.get("site", {}).get("name", "Site Desconhecido")
        steps = config.get("steps", [])
        
        print(f"=== Iniciando Automação para: {site_name} ===")
        
        current_step_name = "inicialização"
        try:
            for i, step in enumerate(steps):
                # 1. Antes de qualquer step, garantimos que não há pausa ativa (CAPTCHA)
                self.browser.wait_before_action()
                
                current_step_name = step.get("name", f"Step {i+1}")
                print(f"-> Executando: {current_step_name}")
                
                self._execute_step(step)
                
            print("=== Automação Concluída com Sucesso! ===")
            return True
            
        except Exception as e:
            # [GEMINI - CORREÇÃO M3]: Uso de current_step_name para evitar UnboundLocalError caso falhe antes do loop
            print(f"[ERRO] Falha durante automação no step '{current_step_name}': {e}")
            return False

    def _execute_step(self, step: Dict[str, Any]):
        """Roteador de tipos de passos da automação."""
        step_type = step.get("type", "fill") # Padrão original era fill se não tiver type
        
        if step_type == "navigate":
            self.browser.navigate(step["url"])
            
        elif step_type == "click" or step_type == "download":
            self._do_click(step)
            
        elif step_type == "wait":
            self._do_wait(step)
            
        elif step_type == "pause":
            reason = step.get("reason", "Pausa manual solicitada pelo fluxo")
            self.browser.pause_automation(reason)
            
        elif step_type == "fill":
            # Caso antigo compatível: pode ter url na própria raiz do step
            if "url" in step:
                self.browser.navigate(step["url"])
            self._do_fill(step)
            
        else:
            print(f"[AVISO] Tipo de step desconhecido: {step_type}")

    def _do_click(self, step: Dict[str, Any]):
        """Clica em um elemento na tela."""
        by_method = self._get_by(step.get("by", "css"))
        selector = step["selector"]
        
        # Espera o elemento ficar clicável
        wait = WebDriverWait(self.driver, 10)
        el = wait.until(EC.element_to_be_clickable((by_method, selector)))
        el.click()

    def _do_wait(self, step: Dict[str, Any]):
        """Espera explícita por um elemento."""
        wait_info = step.get("wait_for", {})
        if not wait_info:
            return
            
        by_method = self._get_by(wait_info.get("by", "id"))
        selector = wait_info["selector"]
        condition = wait_info.get("condition", "visible")
        timeout = wait_info.get("timeout", 15)
        
        wait = WebDriverWait(self.driver, timeout)
        
        if condition == "visible":
            wait.until(EC.visibility_of_element_located((by_method, selector)))
        elif condition == "invisible":
            wait.until(EC.invisibility_of_element_located((by_method, selector)))
        elif condition == "clickable":
            wait.until(EC.element_to_be_clickable((by_method, selector)))

    def _do_fill(self, step: Dict[str, Any]):
        """Preenche uma lista de campos em um formulário."""
        fields = step.get("fields", [])
        
        for field in fields:
            self.browser.wait_before_action() # Checa pausa manual/captcha entre campos
            
            data_key = field["data_key"]
            value_to_fill = self.payload.get(data_key)
            
            # Se o dado não existir no payload, ignora o campo e avisa
            if value_to_fill is None:
                print(f"[AVISO] Dado '{data_key}' ausente no payload. Pulando preenchimento do campo.")
                continue

            # Para campos com dependência (Estado -> Cidade)
            if "depends_on" in field:
                # O preenchimento do dependente (Estado) já ocorreu e disparou o evento onChange.
                # Aqui damos um pequeno tempo explícito para a requisição AJAX das cidades finalizar.
                # (Num sistema de produção robusto, usaríamos um wait customizado).
                time.sleep(1.5) 
            
            by_method = self._get_by(field.get("by", "id"))
            selector = field["selector"]
            field_type = field.get("field_type", "text")
            
            # Localiza o elemento
            wait = WebDriverWait(self.driver, 5)
            el = wait.until(EC.presence_of_element_located((by_method, selector)))
            
            # Roteia para o Handler correto
            if field_type == "text":
                FieldHandlers.fill_text(self.driver, el, str(value_to_fill))
            elif field_type == "date":
                # Opcional: formatar data_nascimento se necessário
                FieldHandlers.fill_date(self.driver, el, str(value_to_fill))
            elif field_type == "select_text":
                FieldHandlers.select_native(self.driver, el, str(value_to_fill))
            elif field_type == "checkbox":
                # value_to_fill idealmente é booleano (true/false) neste contexto
                val_bool = str(value_to_fill).lower() in ["true", "1", "sim", "yes"]
                FieldHandlers.fill_checkbox(self.driver, el, val_bool)
            else:
                print(f"[AVISO] Tipo de campo {field_type} não implementado.")
                
            time.sleep(0.3) # Ritmo humano natural

        # Clica no submit se houver
        if "submit" in step:
            self.browser.wait_before_action()
            sub_by = self._get_by(step["submit"].get("by", "css"))
            sub_sel = step["submit"]["selector"]
            # [LEGACY]: btn = self.driver.find_element(sub_by, sub_sel)
            # [GEMINI - CORREÇÃO M2]: Espera explícita com WebDriverWait para evitar ElementClickInterceptedException
            btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((sub_by, sub_sel))
            )
            btn.click()
            time.sleep(1) # Aguarda após submeter

    def _get_by(self, by_str: str):
        """Converte string YAML para constante do Selenium By."""
        by_str = by_str.lower()
        if by_str == "id": return By.ID
        if by_str == "name": return By.NAME
        if by_str == "css": return By.CSS_SELECTOR
        if by_str == "xpath": return By.XPATH
        if by_str == "class": return By.CLASS_NAME
        return By.ID # fallback
