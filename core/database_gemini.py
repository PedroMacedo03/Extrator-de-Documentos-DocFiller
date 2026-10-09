"""
DocFiller — Banco de Dados e Gerenciamento de Arquivos
======================================================

Responsável por:
1. Copiar/salvar arquivos enviados para uma pasta estruturada local 
   (`data/documents/YYYY-MM-DD/`) para que possam ser revisitados.
2. Persistir o histórico de extrações, tipos de documentos e dados brutos 
   em um banco de dados SQLite local.
3. Persistir o histórico de preenchimentos de formulários web.
"""

import sqlite3
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

class DatabaseManager:
    """
    Gerenciador de armazenamento local persistente (Arquivos + SQLite).
    """

    # [Opus - v1.0 Prep]: base_dir utiliza o DATA_DIR centralizado de core.paths,
    # garantindo que o SQLite e arquivos sejam salvos no local correto tanto em modo script quanto .exe
    def __init__(self, base_dir: str | Path | None = None):
        if base_dir is None:
            from core.paths import DATA_DIR
            self.base_dir = DATA_DIR
        else:
            self.base_dir = Path(base_dir)
        self.docs_dir = self.base_dir / "documents"
        self.db_path = self.base_dir / "docfiller.db"
        
        # Garante que as pastas existem
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Inicializa as tabelas do SQLite se não existirem."""
        # [LEGACY]: Criava apenas extractions e fill_history sem suporte a sessões/processos.
        # [GEMINI - FASE 6]: Criação da tabela sessions e migração com session_id em extractions
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Tabela de sessões / processos
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Tabela de histórico de extrações
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS extractions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    extracted_data_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Migração automática: verifica se session_id existe em extractions
            cursor.execute("PRAGMA table_info(extractions)")
            cols = [col[1] for col in cursor.fetchall()]
            if "session_id" not in cols:
                cursor.execute("ALTER TABLE extractions ADD COLUMN session_id INTEGER REFERENCES sessions(id)")
            
            # Tabela de histórico de automações web
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS fill_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    evidence_path TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()

    def save_file_locally(self, source_path: str | Path) -> Path:
        """
        Copia o arquivo original para a estrutura data/documents/YYYY-MM-DD/
        Mantém o arquivo disponível para ser revisitado na GUI.
        """
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {source}")

        # Cria pasta com a data de hoje
        today = datetime.now().strftime("%Y-%m-%d")
        dest_dir = self.docs_dir / today
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Evita sobrescrever arquivos com mesmo nome adicionando timestamp
        timestamp = datetime.now().strftime("%H%M%S")
        safe_name = f"{source.stem}_{timestamp}{source.suffix}"
        
        dest_path = dest_dir / safe_name
        shutil.copy2(source, dest_path)
        
        return dest_path

    # [LEGACY]: def log_extraction(self, saved_file_path: Path, original_name: str, doc_type: str, extracted_data: Dict[str, Any]) -> int
    # [GEMINI - FASE 6]: Suporte a session_id para vincular o documento à sua respectiva sessão/processo
    def log_extraction(self, saved_file_path: Path, original_name: str, doc_type: str, extracted_data: Dict[str, Any], session_id: Optional[int] = None) -> int:
        """
        Salva os dados de uma extração concluída no SQLite, vinculando a uma sessão.
        """
        if session_id is None:
            session_id = self.get_or_create_default_session()

        data_json = json.dumps(extracted_data, ensure_ascii=False)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT INTO extractions (file_path, original_name, document_type, extracted_data_json, session_id)
                   VALUES (?, ?, ?, ?, ?)''',
                (str(saved_file_path), original_name, doc_type, data_json, session_id)
            )
            # Atualiza a data da sessão para subir na ordenação
            cursor.execute(
                '''UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?''',
                (session_id,)
            )
            conn.commit()
            return cursor.lastrowid

    # [GEMINI - FASE 6]: Métodos de Gerenciamento de Sessões / Processos
    def create_session(self, name: Optional[str] = None, description: str = "") -> int:
        """Cria uma nova sessão. Se o nome não for informado, gera com Data/Hora atual."""
        # [GEMINI]: Formato estrito solicitado pelo usuário: HH/MM - DD/MM/AA
        if not name or not name.strip():
            name = datetime.now().strftime("Sessão %H/%M - %d/%m/%y")
        name = name.strip()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT INTO sessions (name, description, created_at, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
                (name, description)
            )
            conn.commit()
            return cursor.lastrowid

    def get_or_create_default_session(self) -> int:
        """Retorna a sessão mais recente ou cria uma nova se nenhuma existir."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM sessions ORDER BY updated_at DESC LIMIT 1')
            row = cursor.fetchone()
            if row:
                return row[0]
            
        return self.create_session()

    def rename_session(self, session_id: int, new_name: str) -> bool:
        """Renomeia uma sessão existente."""
        if not new_name or not new_name.strip():
            return False
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''UPDATE sessions SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?''',
                (new_name.strip(), session_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_all_sessions(self, search: str = "") -> List[Dict[str, Any]]:
        """Recupera todas as sessões com contagem de documentos anexados e busca por nome."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if search.strip():
                query = '''
                    SELECT s.id, s.name, s.description, s.created_at, s.updated_at,
                           COUNT(e.id) as doc_count
                    FROM sessions s
                    LEFT JOIN extractions e ON s.id = e.session_id
                    WHERE s.name LIKE ?
                    GROUP BY s.id
                    ORDER BY s.updated_at DESC
                '''
                cursor.execute(query, (f"%{search.strip()}%",))
            else:
                query = '''
                    SELECT s.id, s.name, s.description, s.created_at, s.updated_at,
                           COUNT(e.id) as doc_count
                    FROM sessions s
                    LEFT JOIN extractions e ON s.id = e.session_id
                    GROUP BY s.id
                    ORDER BY s.updated_at DESC
                '''
                cursor.execute(query)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_session(self, session_id: int) -> Optional[Dict[str, Any]]:
        """Recupera informações detalhadas de uma sessão única."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM sessions WHERE id = ?', (session_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_session_extractions(self, session_id: int) -> List[Dict[str, Any]]:
        """Recupera todos os documentos extraídos vinculados a uma sessão específica."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                '''SELECT * FROM extractions WHERE session_id = ? ORDER BY id ASC''',
                (session_id,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def delete_session(self, session_id: int) -> bool:
        """Exclui a sessão e todos os documentos vinculados a ela."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM extractions WHERE session_id = ?', (session_id,))
            cursor.execute('DELETE FROM sessions WHERE id = ?', (session_id,))
            conn.commit()
            return cursor.rowcount > 0

    def delete_extraction(self, extraction_id: int) -> bool:
        """Exclui um documento extraído específico."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM extractions WHERE id = ?', (extraction_id,))
            conn.commit()
            return cursor.rowcount > 0

    def update_extraction_data(self, extraction_id: int, new_dados: Dict[str, Any]) -> bool:
        """
        Salva alterações manuais feitas pelo usuário no payload estruturado ('dados') do documento.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT extracted_data_json, session_id FROM extractions WHERE id = ?', (extraction_id,))
            row = cursor.fetchone()
            if not row:
                return False
            
            raw_json = row["extracted_data_json"]
            session_id = row["session_id"]
            try:
                payload = json.loads(raw_json)
            except Exception:
                payload = {}

            # Atualiza os dados
            payload["dados"] = new_dados
            updated_json = json.dumps(payload, ensure_ascii=False)

            cursor.execute(
                'UPDATE extractions SET extracted_data_json = ? WHERE id = ?',
                (updated_json, extraction_id)
            )
            if session_id:
                cursor.execute(
                    'UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                    (session_id,)
                )
            conn.commit()
            return True

    def log_form_fill(self, site_url: str, status: str, payload: Dict[str, Any], evidence_path: Optional[str] = None) -> int:
        """
        Salva o histórico de uma execução do robô (com sucesso ou falha).
        """
        payload_json = json.dumps(payload, ensure_ascii=False)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT INTO fill_history (site_url, status, payload_json, evidence_path)
                   VALUES (?, ?, ?, ?)''',
                (site_url, status, payload_json, evidence_path)
            )
            conn.commit()
            return cursor.lastrowid

    def get_recent_extractions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Recupera histórico recente de extrações para mostrar na GUI."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM extractions ORDER BY created_at DESC LIMIT ?', (limit,))
            rows = cursor.fetchall()
            
            return [dict(row) for row in rows]

# ──────────────────────────────────────────────────────────────────
# Teste Rápido
# ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Módulo de Banco de Dados inicializado.")
    # db = DatabaseManager()
    # print(f"Banco de dados em: {db.db_path}")
