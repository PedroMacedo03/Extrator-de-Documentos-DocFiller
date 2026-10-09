"""
DocFiller — Manipuladores de Campos (Field Handlers)
====================================================

Funções especializadas para interagir com diferentes tipos de 
campos HTML usando Selenium, reproduzindo comportamento humano
e lidando com frameworks reativos (React, Vue).
"""

import time
from typing import Optional

try:
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import Select
    from selenium.common.exceptions import NoSuchElementException
except ImportError:
    pass

class FieldHandlers:
    """Coleção de métodos para preencher campos no Selenium."""

    @staticmethod
    def fill_text(driver: 'WebDriver', element: 'WebElement', value: str) -> None:
        """
        Preenche campos de texto/números.
        Limpa o campo usando Ctrl+A + Backspace para garantir que disparadores
        JavaScript de frameworks reativos percebam a mudança.
        """
        # Limpeza robusta (React/Vue amigável)
        element.send_keys(Keys.CONTROL + "a")
        element.send_keys(Keys.BACKSPACE)
        time.sleep(0.1)
        
        # Digitação
        element.send_keys(value)
        
        # Dispara eventos js blur/change para forçar validação de front-end
        driver.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", element)
        driver.execute_script("arguments[0].dispatchEvent(new Event('blur', { bubbles: true }));", element)

    @staticmethod
    def fill_date(driver: 'WebDriver', element: 'WebElement', value: str) -> None:
        """
        Preenche campos de data. Em alguns sistemas governamentais,
        o campo é readonly ou possui máscara pesada.
        """
        # Tenta remover readonly caso exista
        driver.execute_script("arguments[0].removeAttribute('readonly')", element)
        
        element.send_keys(Keys.CONTROL + "a")
        element.send_keys(Keys.BACKSPACE)
        time.sleep(0.1)
        
        # Envia a data formatada (o form_filler já deve passar formatado)
        element.send_keys(value)
        
        driver.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", element)

    @staticmethod
    def select_native(driver: 'WebDriver', element: 'WebElement', visible_text: str) -> bool:
        """
        Seleciona uma opção em um elemento <select> nativo que já 
        possui a lista pré-populada.
        
        Tenta buscar exatamente pelo texto (ignorando case).
        Retorna True se conseguiu encontrar, False caso contrário.
        """
        select = Select(element)
        options = select.options
        
        # 1. Tenta correspondência exata de texto (case insensitive)
        target_lower = visible_text.lower().strip()
        for opt in options:
            if opt.text.lower().strip() == target_lower:
                select.select_by_visible_text(opt.text)
                driver.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", element)
                return True
                
        # 2. Fallback: Se o texto extraído do doc for "São Paulo" e o option for "SP - São Paulo"
        for opt in options:
            if target_lower in opt.text.lower().strip():
                select.select_by_visible_text(opt.text)
                driver.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", element)
                return True
                
        print(f"[HANDLERS] Opção '{visible_text}' não encontrada no select nativo.")
        return False

    @staticmethod
    def fill_checkbox(driver: 'WebDriver', element: 'WebElement', check: bool = True) -> None:
        """Marca ou desmarca um checkbox se o estado atual for diferente do desejado."""
        is_checked = element.is_selected()
        if (check and not is_checked) or (not check and is_checked):
            element.click()

    @staticmethod
    def file_upload(driver: 'WebDriver', element: 'WebElement', absolute_path: str) -> None:
        """
        Faz upload de arquivo. O elemento não pode estar escondido (display: none).
        Se estiver escondido por causa de um botão "bonito", tentamos torná-lo visível via JS.
        """
        try:
            if not element.is_displayed():
                driver.execute_script("arguments[0].style.display = 'block';", element)
                
            element.send_keys(absolute_path)
        except Exception as e:
            print(f"[HANDLERS] Falha ao injetar arquivo no campo: {e}")
