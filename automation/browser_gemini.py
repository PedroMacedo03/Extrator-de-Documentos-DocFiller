"""
DocFiller — Gerenciador do Browser (Selenium)
=============================================

Responsável por inicializar e controlar a sessão do navegador.
Implementa:
- Evasão básica de detecção de bots
- Persistência de perfil de usuário (mantém logins)
- Mecanismo de PAUSA para resolução manual de CAPTCHAs
"""

import time
import threading
from typing import Callable, Optional
from pathlib import Path

# Tentando importar Selenium. Se falhar, é preciso instalar no environment do usuário.
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
except ImportError:
    webdriver = None

class BrowserManager:
    def __init__(self, headless: bool = False, profile_dir: str | Path = "data/browser_profile"):
        if webdriver is None:
            raise ImportError("Selenium não instalado. Execute: pip install selenium")
            
        self.headless = headless
        self.profile_dir = Path(profile_dir).absolute()
        self.driver = None
        
        # Evento de thread para controlar a pausa por CAPTCHA
        self.resume_event = threading.Event()
        self.resume_event.set() # Inicialmente liberado (não pausado)
        
        # Callback opcional para a GUI exibir alerta
        self.on_pause_callback: Optional[Callable[[str], None]] = None

    def start(self):
        """Inicializa o WebDriver do Chrome via Selenium Manager."""
        options = Options()
        
        if self.headless:
            options.add_argument("--headless=new")
            
        # Manter sessão de login
        self.profile_dir.parent.mkdir(parents=True, exist_ok=True)
        # [LEGACY]: options.add_argument(f"user-data-dir={self.profile_dir}")
        # [GEMINI - CORREÇÃO M1]: Flag Chromium padronizada com duplo traço (--user-data-dir)
        options.add_argument(f"--user-data-dir={self.profile_dir}")
        
        # Anti-detecção básica
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        
        # Selenium Manager no 4.x baixa o driver automaticamente
        self.driver = webdriver.Chrome(options=options)
        
        # Remove a flag webdriver do navigator via CDP
        self.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"}
        )

    def stop(self):
        """Encerra o browser."""
        if self.driver:
            self.driver.quit()
            self.driver = None

    def navigate(self, url: str):
        """Navega para a URL."""
        if not self.driver:
            self.start()
        self.driver.get(url)
        self.check_for_captcha()

    def pause_automation(self, reason: str = "Pausa solicitada pelo usuário"):
        """Pausa a execução até que resume_automation() seja chamado."""
        print(f"[PAUSA] Automação parada: {reason}")
        self.resume_event.clear()
        
        if self.on_pause_callback:
            self.on_pause_callback(reason)
            
        # Bloqueia a thread atual (worker) até que o botão "Retomar" seja clicado na GUI
        self.resume_event.wait()
        print("[PAUSA] Automação retomada!")

    def resume_automation(self):
        """Libera a thread e retoma o preenchimento."""
        self.resume_event.set()

    def check_for_captcha(self):
        """
        Verifica a presença de iframes ou elementos clássicos de CAPTCHA.
        Se detectado, pausa automaticamente e aguarda o usuário resolver.
        """
        if not self.driver:
            return

        captcha_detected = False
        reason = ""

        # Verifica iframes típicos (reCAPTCHA, hCaptcha, Turnstile)
        try:
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes:
                src = iframe.get_attribute("src") or ""
                if "recaptcha" in src:
                    captcha_detected = True
                    reason = "Google reCAPTCHA detectado"
                    break
                elif "hcaptcha" in src:
                    captcha_detected = True
                    reason = "hCaptcha detectado"
                    break
                elif "cf-turnstile" in src:
                    captcha_detected = True
                    reason = "Cloudflare Turnstile detectado"
                    break
        except Exception:
            pass
            
        # Alguns sites também colocam alertas explícitos no HTML
        if not captcha_detected:
            page_source = self.driver.page_source.lower()
            if "please solve the captcha" in page_source or "por favor, resolva o captcha" in page_source:
                captcha_detected = True
                reason = "Texto de CAPTCHA detectado na página"

        if captcha_detected:
            # Traz janela do Chrome pra frente para facilitar para o usuário (Windows)
            # Obs: Requer pywin32 em cenários mais robustos, mas vamos apenas pausar a lógica.
            self.pause_automation(reason)
            
            # Quando a pausa for liberada (usuário resolveu e clicou retomar), 
            # não assumimos instantaneamente que deu certo, mas continuamos o fluxo.

    def wait_before_action(self):
        """
        Deve ser chamado antes de qualquer clique ou digitação pelo FormFiller.
        Garante que se estivermos no meio de uma pausa (seja manual ou por Captcha),
        a automação espere.
        """
        self.resume_event.wait()
