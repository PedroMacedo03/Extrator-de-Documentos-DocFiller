"""
DocFiller — Gerenciador de Sessões
==================================

Auxiliar para salvar e restaurar cookies explícitos. 
Embora o BrowserManager use um `user-data-dir` para manter
logins naturalmente, em alguns sites do governo é mais seguro
injetar os cookies da sessão ativa diretamente.
"""

import json
from pathlib import Path
from typing import Optional

try:
    from selenium.webdriver.remote.webdriver import WebDriver
except ImportError:
    pass

class SessionManager:
    def __init__(self, sessions_dir: str | Path = "data/sessions"):
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def save_session(self, driver: 'WebDriver', site_name: str) -> None:
        """Salva os cookies atuais de uma página."""
        cookies = driver.get_cookies()
        
        file_path = self.sessions_dir / f"{site_name}_cookies.json"
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=2)
            
        print(f"[SESSION] Cookies de {site_name} salvos ({len(cookies)} cookies).")

    def load_session(self, driver: 'WebDriver', site_name: str, domain_url: str) -> bool:
        """
        Injeta os cookies na sessão atual. 
        O driver já deve estar no domínio (domain_url) correto antes de injetar.
        """
        file_path = self.sessions_dir / f"{site_name}_cookies.json"
        
        if not file_path.exists():
            return False
            
        # O Selenium exige estar no domínio antes de carregar o cookie
        driver.get(domain_url)
        
        with open(file_path, "r", encoding="utf-8") as f:
            cookies = json.load(f)
            
        for cookie in cookies:
            try:
                driver.add_cookie(cookie)
            except Exception as e:
                print(f"[SESSION] Erro ao adicionar cookie {cookie.get('name')}: {e}")
                
        # Atualiza a página para aplicar os cookies
        driver.refresh()
        print(f"[SESSION] Sessão de {site_name} restaurada.")
        return True
