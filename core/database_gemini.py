"""
DocFiller — Banco de Dados e Gerenciamento de Arquivos
======================================================

Responsável por:
1. Copiar/salvar arquivos enviados para uma pasta estruturada local 
   (`data/documents/YYYY-MM-DD/`) para que possam ser revisitados.
2. Persistir o histórico de extrações, tipos de documentos e dados brutos 
   em um banco de dados SQLite local.
3. Persistir entidades reconhecidas por sessão (Pessoas e Imóveis), vínculos
   de documentos (`extraction_links`) e edições manuais (`overrides_json`).
4. Persistir o histórico de preenchimentos de formulários web.
"""

import sqlite3
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now_local_str() -> str:
    """# [Opus - v1.1 Sessions Redesign]: Timestamp local (horário da máquina) no formato YYYY-MM-DD HH:MM:SS."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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
        # [Opus - v1.1 Sessions Redesign]: Adicionado seq_number fixo em sessions e tabelas
        # session_persons, session_properties e extraction_links.
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Tabela de sessões / processos
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    seq_number INTEGER,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Migração automática: verifica se seq_number existe em sessions
            cursor.execute("PRAGMA table_info(sessions)")
            session_cols = [col[1] for col in cursor.fetchall()]
            if "seq_number" not in session_cols:
                cursor.execute("ALTER TABLE sessions ADD COLUMN seq_number INTEGER")

            # Garante que sessões existentes tenham seq_number fixo
            cursor.execute("SELECT id FROM sessions WHERE seq_number IS NULL ORDER BY id ASC")
            null_seq_rows = cursor.fetchall()
            if null_seq_rows:
                cursor.execute("SELECT COALESCE(MAX(seq_number), 0) FROM sessions")
                current_max = cursor.fetchone()[0] or 0
                for (sid,) in null_seq_rows:
                    current_max += 1
                    cursor.execute("UPDATE sessions SET seq_number = ? WHERE id = ?", (current_max, sid))
            
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

            # [Opus - v1.1 Sessions Redesign]: Tabela de Pessoas reconhecidas na sessão
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS session_persons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL REFERENCES sessions(id),
                    display_name TEXT NOT NULL,
                    cpf_key TEXT DEFAULT '',
                    rg_key TEXT DEFAULT '',
                    name_key TEXT DEFAULT '',
                    overrides_json TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # [Opus - v1.1 Sessions Redesign]: Tabela de Imóveis reconhecidos na sessão
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS session_properties (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL REFERENCES sessions(id),
                    label TEXT NOT NULL,
                    matricula_key TEXT DEFAULT '',
                    inscricao_key TEXT DEFAULT '',
                    address_key TEXT DEFAULT '',
                    cep_key TEXT DEFAULT '',
                    overrides_json TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # [Opus - v1.1 Sessions Redesign]: Vínculos entre extrações e entidades (Pessoas / Imóveis)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS extraction_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    extraction_id INTEGER NOT NULL REFERENCES extractions(id),
                    entity_type TEXT NOT NULL CHECK (entity_type IN ('PERSON', 'PROPERTY')),
                    entity_id INTEGER NOT NULL,
                    role TEXT DEFAULT 'TITULAR',
                    json_path TEXT DEFAULT 'documento.pessoa'
                )
            ''')
            
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

    def touch_session(self, session_id: int) -> None:
        """
        # [Opus - v1.1 Sessions Redesign]: Atualiza apenas o timestamp updated_at da sessão,
        # sem JAMAIS alterar seu nome ou sua posição (seq_number) na lista.
        """
        if not session_id:
            return
        now_str = _now_local_str()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now_str, session_id),
            )
            conn.commit()

    # [LEGACY]: def log_extraction(self, saved_file_path: Path, original_name: str, doc_type: str, extracted_data: Dict[str, Any]) -> int
    # [GEMINI - FASE 6]: Suporte a session_id para vincular o documento à sua respectiva sessão/processo
    # [Opus - v1.1 Sessions Redesign]: Registra extração, atualiza updated_at (sem mudar ordem) e executa EntityResolver
    def log_extraction(
        self,
        saved_file_path: Path,
        original_name: str,
        doc_type: str,
        extracted_data: Dict[str, Any],
        session_id: Optional[int] = None,
    ) -> int:
        """
        Salva os dados de uma extração concluída no SQLite, vinculando a uma sessão
        e resolvendo automaticamente as Pessoas e Imóveis correspondentes.
        """
        if session_id is None:
            session_id = self.get_or_create_default_session()

        data_json = json.dumps(extracted_data, ensure_ascii=False)
        now_str = _now_local_str()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT INTO extractions (file_path, original_name, document_type, extracted_data_json, session_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (str(saved_file_path), original_name, doc_type, data_json, session_id, now_str)
            )
            extraction_id = cursor.lastrowid
            cursor.execute(
                '''UPDATE sessions SET updated_at = ? WHERE id = ?''',
                (now_str, session_id)
            )
            conn.commit()

        # [Opus - v1.1 Sessions Redesign]: Vincula automaticamente às Pessoas e Imóveis da sessão
        try:
            from core.entity_resolver_gemini import EntityResolver
            resolver = EntityResolver(self)
            resolver.link_extraction(session_id, extraction_id, doc_type, extracted_data)
        except Exception as e:
            print(f"[EntityResolver] Aviso ao vincular entidades da extração {extraction_id}: {e}")

        return extraction_id

    # [GEMINI - FASE 6]: Métodos de Gerenciamento de Sessões / Processos
    # [Opus - v1.1 Sessions Redesign]: seq_number fixo na criação; nome nunca é alterado automaticamente
    def get_next_session_seq_number(self) -> int:
        """Retorna o próximo número sequencial fixo para criação de uma sessão."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COALESCE(MAX(seq_number), 0) + 1 FROM sessions")
            row = cursor.fetchone()
            return int(row[0]) if row and row[0] else 1

    def create_session(self, name: Optional[str] = None, description: str = "") -> int:
        """Cria uma nova sessão com número de ordem fixo (seq_number) e timestamps locais."""
        next_seq = self.get_next_session_seq_number()
        if not name or not name.strip():
            name = f"Sessão {next_seq}"
        name = name.strip()
        now_str = _now_local_str()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT INTO sessions (seq_number, name, description, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)''',
                (next_seq, name, description, now_str, now_str)
            )
            conn.commit()
            return cursor.lastrowid

    def get_or_create_default_session(self) -> int:
        """Retorna a última sessão criada (por ordem fixa) ou cria uma nova se nenhuma existir."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM sessions ORDER BY COALESCE(seq_number, id) DESC, id DESC LIMIT 1')
            row = cursor.fetchone()
            if row:
                return row[0]
            
        return self.create_session()

    def rename_session(self, session_id: int, new_name: str) -> bool:
        """Renomeia manualmente uma sessão existente (única forma de alterar o nome da sessão)."""
        if not new_name or not new_name.strip():
            return False
        now_str = _now_local_str()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''UPDATE sessions SET name = ?, updated_at = ? WHERE id = ?''',
                (new_name.strip(), now_str, session_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_all_sessions(self, search: str = "") -> List[Dict[str, Any]]:
        """
        # [Opus - v1.1 Sessions Redesign]: Recupera todas as sessões em ORDEM DE CRIAÇÃO FIXA
        # (ORDER BY COALESCE(s.seq_number, s.id) ASC, s.id ASC), garantindo que edições posteriores
        # nunca mudem a posição da sessão na lista.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if search.strip():
                query = '''
                    SELECT s.id, COALESCE(s.seq_number, s.id) AS seq_number,
                           s.name, s.description, s.created_at, s.updated_at,
                           COUNT(e.id) as doc_count
                    FROM sessions s
                    LEFT JOIN extractions e ON s.id = e.session_id
                    WHERE s.name LIKE ? OR CAST(COALESCE(s.seq_number, s.id) AS TEXT) LIKE ?
                    GROUP BY s.id
                    ORDER BY COALESCE(s.seq_number, s.id) ASC, s.id ASC
                '''
                term = f"%{search.strip()}%"
                cursor.execute(query, (term, term))
            else:
                query = '''
                    SELECT s.id, COALESCE(s.seq_number, s.id) AS seq_number,
                           s.name, s.description, s.created_at, s.updated_at,
                           COUNT(e.id) as doc_count
                    FROM sessions s
                    LEFT JOIN extractions e ON s.id = e.session_id
                    GROUP BY s.id
                    ORDER BY COALESCE(s.seq_number, s.id) ASC, s.id ASC
                '''
                cursor.execute(query)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_session(self, session_id: int) -> Optional[Dict[str, Any]]:
        """Recupera informações detalhadas de uma sessão única."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, COALESCE(seq_number, id) AS seq_number, name, description, created_at, updated_at FROM sessions WHERE id = ?',
                (session_id,)
            )
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
        """Exclui a sessão, suas entidades (Pessoas/Imóveis), vínculos e documentos."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''DELETE FROM extraction_links WHERE extraction_id IN (
                       SELECT id FROM extractions WHERE session_id = ?
                   )''',
                (session_id,)
            )
            cursor.execute('DELETE FROM session_persons WHERE session_id = ?', (session_id,))
            cursor.execute('DELETE FROM session_properties WHERE session_id = ?', (session_id,))
            cursor.execute('DELETE FROM extractions WHERE session_id = ?', (session_id,))
            cursor.execute('DELETE FROM sessions WHERE id = ?', (session_id,))
            conn.commit()
            return cursor.rowcount > 0

    def delete_extraction(self, extraction_id: int) -> bool:
        """
        # [Opus - v1.1 Sessions Redesign]: Exclui um documento extraído, remove seus vínculos em
        # extraction_links, limpa Pessoas/Imóveis que ficaram sem nenhum documento vinculado e
        # atualiza updated_at da sessão.
        """
        now_str = _now_local_str()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT session_id FROM extractions WHERE id = ?', (extraction_id,))
            row = cursor.fetchone()
            session_id = row[0] if row else None

            cursor.execute('DELETE FROM extraction_links WHERE extraction_id = ?', (extraction_id,))
            cursor.execute('DELETE FROM extractions WHERE id = ?', (extraction_id,))
            deleted = cursor.rowcount > 0

            if session_id:
                # Remove pessoas órfãs (sem nenhum link na sessão)
                cursor.execute(
                    '''DELETE FROM session_persons
                       WHERE session_id = ?
                         AND id NOT IN (
                             SELECT entity_id FROM extraction_links WHERE entity_type = 'PERSON'
                         )''',
                    (session_id,)
                )
                # Remove imóveis órfãos (sem nenhum link na sessão)
                cursor.execute(
                    '''DELETE FROM session_properties
                       WHERE session_id = ?
                         AND id NOT IN (
                             SELECT entity_id FROM extraction_links WHERE entity_type = 'PROPERTY'
                         )''',
                    (session_id,)
                )
                cursor.execute('UPDATE sessions SET updated_at = ? WHERE id = ?', (now_str, session_id))

            conn.commit()
            return deleted

    def update_extraction_data(self, extraction_id: int, new_dados: Dict[str, Any]) -> bool:
        """
        Salva alterações manuais feitas pelo usuário no payload estruturado ('dados') do documento.
        """
        now_str = _now_local_str()
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
                    'UPDATE sessions SET updated_at = ? WHERE id = ?',
                    (now_str, session_id)
                )
            conn.commit()
            return True

    # ──────────────────────────────────────────────────────────────────
    # [Opus - v1.1 Sessions Redesign]: Métodos de Pessoas, Imóveis e Links
    # ──────────────────────────────────────────────────────────────────

    def get_session_persons(self, session_id: int) -> List[Dict[str, Any]]:
        """Retorna todas as pessoas reconhecidas na sessão (em ordem de criação)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                '''SELECT p.*, COUNT(l.id) AS doc_count
                   FROM session_persons p
                   LEFT JOIN extraction_links l
                     ON l.entity_type = 'PERSON' AND l.entity_id = p.id
                   WHERE p.session_id = ?
                   GROUP BY p.id
                   ORDER BY p.id ASC''',
                (session_id,)
            )
            return [dict(r) for r in cursor.fetchall()]

    def get_session_properties(self, session_id: int) -> List[Dict[str, Any]]:
        """Retorna todos os imóveis reconhecidos na sessão (em ordem de criação)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                '''SELECT pr.*, COUNT(l.id) AS doc_count
                   FROM session_properties pr
                   LEFT JOIN extraction_links l
                     ON l.entity_type = 'PROPERTY' AND l.entity_id = pr.id
                   WHERE pr.session_id = ?
                   GROUP BY pr.id
                   ORDER BY pr.id ASC''',
                (session_id,)
            )
            return [dict(r) for r in cursor.fetchall()]

    def get_person(self, person_id: int) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM session_persons WHERE id = ?', (person_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_property(self, property_id: int) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM session_properties WHERE id = ?', (property_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_entity_extractions(self, entity_type: str, entity_id: int) -> List[Dict[str, Any]]:
        """
        Retorna todos os documentos (extractions) vinculados a uma Pessoa ('PERSON')
        ou Imóvel ('PROPERTY'), incluindo metadados do vínculo (link_id, role, json_path).
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                '''SELECT e.*, l.id AS link_id, l.role AS link_role, l.json_path AS link_json_path
                   FROM extraction_links l
                   JOIN extractions e ON e.id = l.extraction_id
                   WHERE l.entity_type = ? AND l.entity_id = ?
                   ORDER BY e.id ASC, l.id ASC''',
                (entity_type.upper(), entity_id)
            )
            return [dict(r) for r in cursor.fetchall()]

    def get_session_links(self, session_id: int) -> List[Dict[str, Any]]:
        """Retorna todos os vínculos de documentos de uma sessão."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                '''SELECT l.*
                   FROM extraction_links l
                   JOIN extractions e ON e.id = l.extraction_id
                   WHERE e.session_id = ?
                   ORDER BY l.id ASC''',
                (session_id,)
            )
            return [dict(r) for r in cursor.fetchall()]

    def create_person(
        self,
        session_id: int,
        display_name: str,
        cpf_key: str = "",
        rg_key: str = "",
        name_key: str = "",
    ) -> int:
        now_str = _now_local_str()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT INTO session_persons (session_id, display_name, cpf_key, rg_key, name_key, overrides_json, created_at)
                   VALUES (?, ?, ?, ?, ?, '{}', ?)''',
                (session_id, display_name.upper().strip(), cpf_key, rg_key, name_key, now_str)
            )
            cursor.execute('UPDATE sessions SET updated_at = ? WHERE id = ?', (now_str, session_id))
            conn.commit()
            return cursor.lastrowid

    def update_person_keys(
        self,
        person_id: int,
        display_name: Optional[str] = None,
        cpf_key: Optional[str] = None,
        rg_key: Optional[str] = None,
        name_key: Optional[str] = None,
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM session_persons WHERE id = ?', (person_id,))
            row = cursor.fetchone()
            if not row:
                return
            new_disp = (display_name.upper().strip() if display_name else row["display_name"])
            new_cpf = cpf_key if cpf_key is not None else row["cpf_key"]
            new_rg = rg_key if rg_key is not None else row["rg_key"]
            new_name_k = name_key if name_key is not None else row["name_key"]
            cursor.execute(
                '''UPDATE session_persons
                   SET display_name = ?, cpf_key = ?, rg_key = ?, name_key = ?
                   WHERE id = ?''',
                (new_disp, new_cpf, new_rg, new_name_k, person_id)
            )
            conn.commit()

    def create_property(
        self,
        session_id: int,
        label: str,
        matricula_key: str = "",
        inscricao_key: str = "",
        address_key: str = "",
        cep_key: str = "",
    ) -> int:
        now_str = _now_local_str()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT INTO session_properties
                   (session_id, label, matricula_key, inscricao_key, address_key, cep_key, overrides_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, '{}', ?)''',
                (session_id, label.upper().strip(), matricula_key, inscricao_key, address_key, cep_key, now_str)
            )
            cursor.execute('UPDATE sessions SET updated_at = ? WHERE id = ?', (now_str, session_id))
            conn.commit()
            return cursor.lastrowid

    def update_property_keys(
        self,
        property_id: int,
        label: Optional[str] = None,
        matricula_key: Optional[str] = None,
        inscricao_key: Optional[str] = None,
        address_key: Optional[str] = None,
        cep_key: Optional[str] = None,
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM session_properties WHERE id = ?', (property_id,))
            row = cursor.fetchone()
            if not row:
                return
            new_label = label.upper().strip() if label else row["label"]
            new_mat = matricula_key if matricula_key is not None else row["matricula_key"]
            new_insc = inscricao_key if inscricao_key is not None else row["inscricao_key"]
            new_addr = address_key if address_key is not None else row["address_key"]
            new_cep = cep_key if cep_key is not None else row["cep_key"]
            cursor.execute(
                '''UPDATE session_properties
                   SET label = ?, matricula_key = ?, inscricao_key = ?, address_key = ?, cep_key = ?
                   WHERE id = ?''',
                (new_label, new_mat, new_insc, new_addr, new_cep, property_id)
            )
            conn.commit()

    def add_extraction_link(
        self,
        extraction_id: int,
        entity_type: str,
        entity_id: int,
        role: str = "TITULAR",
        json_path: str = "documento.pessoa",
    ) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Evita duplicar o mesmo link para a mesma extração e json_path
            cursor.execute(
                '''SELECT id FROM extraction_links
                   WHERE extraction_id = ? AND entity_type = ? AND entity_id = ? AND json_path = ?''',
                (extraction_id, entity_type.upper(), entity_id, json_path)
            )
            existing = cursor.fetchone()
            if existing:
                return existing[0]
            cursor.execute(
                '''INSERT INTO extraction_links (extraction_id, entity_type, entity_id, role, json_path)
                   VALUES (?, ?, ?, ?, ?)''',
                (extraction_id, entity_type.upper(), entity_id, role.upper(), json_path)
            )
            conn.commit()
            return cursor.lastrowid

    def set_entity_override(
        self,
        entity_type: str,
        entity_id: int,
        field_key: str,
        value: Optional[str],
    ) -> bool:
        """
        # [Opus - v1.1 Sessions Redesign]: Grava (ou remove, se value=None) um override manual
        # de atributo na Pessoa ou no Imóvel, preservando o JSON original do documento intacto.
        """
        table = "session_persons" if entity_type.upper() == "PERSON" else "session_properties"
        now_str = _now_local_str()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(f"SELECT session_id, overrides_json FROM {table} WHERE id = ?", (entity_id,))
            row = cursor.fetchone()
            if not row:
                return False
            session_id = row["session_id"]
            try:
                overrides = json.loads(row["overrides_json"] or "{}")
            except Exception:
                overrides = {}

            if value is None:
                overrides.pop(field_key, None)
            else:
                clean_val = value.strip().upper()
                overrides[field_key] = clean_val
                # Se editou o nome completo da pessoa ou o endereço do imóvel, reflete no rótulo da lista
                if entity_type.upper() == "PERSON" and field_key == "nome_completo" and clean_val:
                    cursor.execute("UPDATE session_persons SET display_name = ? WHERE id = ?", (clean_val, entity_id))
                elif entity_type.upper() == "PROPERTY" and field_key == "endereco_completo" and clean_val:
                    cursor.execute("UPDATE session_properties SET label = ? WHERE id = ?", (clean_val, entity_id))

            cursor.execute(
                f"UPDATE {table} SET overrides_json = ? WHERE id = ?",
                (json.dumps(overrides, ensure_ascii=False), entity_id)
            )
            cursor.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now_str, session_id))
            conn.commit()
            return True

    def rename_person(self, person_id: int, new_name: str) -> bool:
        if not new_name or not new_name.strip():
            return False
        clean = new_name.strip().upper()
        now_str = _now_local_str()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT session_id FROM session_persons WHERE id = ?", (person_id,))
            row = cursor.fetchone()
            if not row:
                return False
            session_id = row[0]
            cursor.execute("UPDATE session_persons SET display_name = ? WHERE id = ?", (clean, person_id))
            cursor.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now_str, session_id))
            conn.commit()
            return True

    def rename_property(self, property_id: int, new_label: str) -> bool:
        if not new_label or not new_label.strip():
            return False
        clean = new_label.strip().upper()
        now_str = _now_local_str()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT session_id FROM session_properties WHERE id = ?", (property_id,))
            row = cursor.fetchone()
            if not row:
                return False
            session_id = row[0]
            cursor.execute("UPDATE session_properties SET label = ? WHERE id = ?", (clean, property_id))
            cursor.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now_str, session_id))
            conn.commit()
            return True

    def merge_persons(self, target_person_id: int, source_person_id: int) -> bool:
        """Mescla source_person_id dentro de target_person_id (transfere links e overrides)."""
        if target_person_id == source_person_id:
            return False
        now_str = _now_local_str()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM session_persons WHERE id = ?", (target_person_id,))
            target = cursor.fetchone()
            cursor.execute("SELECT * FROM session_persons WHERE id = ?", (source_person_id,))
            source = cursor.fetchone()
            if not target or not source:
                return False

            session_id = target["session_id"]
            try:
                t_ov = json.loads(target["overrides_json"] or "{}")
            except Exception:
                t_ov = {}
            try:
                s_ov = json.loads(source["overrides_json"] or "{}")
            except Exception:
                s_ov = {}
            merged_ov = {**s_ov, **t_ov}

            cpf_key = target["cpf_key"] or source["cpf_key"]
            rg_key = target["rg_key"] or source["rg_key"]
            name_key = target["name_key"] or source["name_key"]

            cursor.execute(
                '''UPDATE extraction_links
                   SET entity_id = ?
                   WHERE entity_type = 'PERSON' AND entity_id = ?''',
                (target_person_id, source_person_id)
            )
            cursor.execute(
                '''UPDATE session_persons
                   SET cpf_key = ?, rg_key = ?, name_key = ?, overrides_json = ?
                   WHERE id = ?''',
                (cpf_key, rg_key, name_key, json.dumps(merged_ov, ensure_ascii=False), target_person_id)
            )
            cursor.execute("DELETE FROM session_persons WHERE id = ?", (source_person_id,))
            cursor.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now_str, session_id))
            conn.commit()
            return True

    def reassign_extraction_link(self, link_id: int, new_entity_id: int) -> bool:
        """Move um vínculo de documento para outra Pessoa ou Imóvel."""
        now_str = _now_local_str()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''SELECT e.session_id
                   FROM extraction_links l
                   JOIN extractions e ON e.id = l.extraction_id
                   WHERE l.id = ?''',
                (link_id,)
            )
            row = cursor.fetchone()
            session_id = row[0] if row else None
            cursor.execute("UPDATE extraction_links SET entity_id = ? WHERE id = ?", (new_entity_id, link_id))
            if session_id:
                cursor.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now_str, session_id))
            conn.commit()
            return cursor.rowcount > 0

    def delete_person(self, person_id: int) -> bool:
        now_str = _now_local_str()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT session_id FROM session_persons WHERE id = ?", (person_id,))
            row = cursor.fetchone()
            session_id = row[0] if row else None
            cursor.execute("DELETE FROM extraction_links WHERE entity_type = 'PERSON' AND entity_id = ?", (person_id,))
            cursor.execute("DELETE FROM session_persons WHERE id = ?", (person_id,))
            if session_id:
                cursor.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now_str, session_id))
            conn.commit()
            return cursor.rowcount > 0

    def delete_property(self, property_id: int) -> bool:
        now_str = _now_local_str()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT session_id FROM session_properties WHERE id = ?", (property_id,))
            row = cursor.fetchone()
            session_id = row[0] if row else None
            cursor.execute("DELETE FROM extraction_links WHERE entity_type = 'PROPERTY' AND entity_id = ?", (property_id,))
            cursor.execute("DELETE FROM session_properties WHERE id = ?", (property_id,))
            if session_id:
                cursor.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now_str, session_id))
            conn.commit()
            return cursor.rowcount > 0

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
