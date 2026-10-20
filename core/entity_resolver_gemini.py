"""
DocFiller — Resolução de Entidades (Pessoas e Imóveis) por Sessão
=================================================================

[Opus - v1.1 Sessions Redesign]:
Motor 100% local (pós-demask) responsável por:
1. Identificar Pessoas (APENAS titular, cônjuges, comprador e vendedor — nunca pais/avós,
   contribuinte de IPTU ou proprietários de certidão de imóvel) e Imóveis dentro de uma sessão.
2. Agrupar documentos que pertencem à mesma Pessoa (por CPF, RG + Nome ou Nome compatível,
   protegendo contra homônimos com CPFs diferentes) ou ao mesmo Imóvel (por Matrícula,
   Inscrição Municipal ou Endereço + CEP).
3. Consolidar os dados da Pessoa selecionada e do Imóvel selecionado segundo a prioridade
   de confiabilidade de cada tipo de documento, detectando divergências (⚠️) entre documentos
   e aplicando edições manuais (overrides) sem alterar o JSON original extraído.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.database_gemini import DatabaseManager
from core.masker_gemini import DataMasker


# Partículas de ligação ignoradas na comparação de nomes
_NAME_PARTICLES = {"DE", "DA", "DO", "DOS", "DAS", "E"}

# Tipos de documento que representam um único titular principal em 'dados["pessoa"]'
SINGLE_HOLDER_DOC_TYPES = {
    "RG", "CNH", "CIN", "CPF", "CTPS", "PASSAPORTE",
    "TITULO_ELEITOR", "CERTIFICADO_RESERVISTA", "CARTAO_SUS",
    "CARTEIRA_ESTUDANTE_DNE", "CARTEIRA_CONSELHO", "IDENTIDADE_FUNCIONAL",
    "CERTIFICADO_DIPLOMA", "NASCIMENTO", "OBITO", "OUTROS",
}

# Tipos de documento focados em Imóvel (contribuinte/proprietarios NÃO viram Pessoa conforme decisão do usuário)
PROPERTY_ONLY_PERSON_SKIP_TYPES = {"IPTU", "CERTIDAO_IMOVEL"}

# Prioridade de fonte documental por atributo de Pessoa (menor índice = maior prioridade)
PERSON_FIELD_PRIORITY: Dict[str, List[str]] = {
    "nome_completo": [
        "CIN", "RG", "CASAMENTO", "NASCIMENTO", "CNH", "PASSAPORTE",
        "CPF", "ESCRITURA", "IDENTIDADE_FUNCIONAL", "CARTEIRA_CONSELHO",
        "TITULO_ELEITOR", "CTPS", "CERTIFICADO_DIPLOMA", "CERTIFICADO_RESERVISTA",
        "CARTAO_SUS", "CARTEIRA_ESTUDANTE_DNE", "OBITO", "OUTROS",
    ],
    "data_nascimento": [
        "NASCIMENTO", "CIN", "RG", "CASAMENTO", "CNH", "PASSAPORTE",
        "CPF", "TITULO_ELEITOR", "IDENTIDADE_FUNCIONAL", "CARTEIRA_CONSELHO",
        "CERTIFICADO_RESERVISTA", "CARTAO_SUS", "CARTEIRA_ESTUDANTE_DNE",
        "CERTIFICADO_DIPLOMA", "OBITO", "ESCRITURA", "OUTROS",
    ],
    "data_obito": [
        "OBITO", "CASAMENTO", "ESCRITURA", "NASCIMENTO", "OUTROS",
    ],
    "nome_pais": [
        "NASCIMENTO", "RG", "CIN", "CASAMENTO", "CNH", "OBITO",
        "TITULO_ELEITOR", "IDENTIDADE_FUNCIONAL", "CARTEIRA_CONSELHO",
        "CERTIFICADO_RESERVISTA", "PASSAPORTE", "OUTROS",
    ],
    "cpf": [
        "CPF", "CIN", "RG", "CNH", "CASAMENTO", "ESCRITURA",
        "PASSAPORTE", "IDENTIDADE_FUNCIONAL", "CARTEIRA_CONSELHO",
        "TITULO_ELEITOR", "CTPS", "CERTIFICADO_DIPLOMA", "CERTIFICADO_RESERVISTA",
        "CARTAO_SUS", "CARTEIRA_ESTUDANTE_DNE", "NASCIMENTO", "OBITO", "OUTROS",
    ],
    "rg": [
        "RG", "CIN", "CNH", "CASAMENTO", "ESCRITURA", "IDENTIDADE_FUNCIONAL",
        "CARTEIRA_CONSELHO", "CTPS", "CERTIFICADO_DIPLOMA", "CERTIFICADO_RESERVISTA",
        "NASCIMENTO", "OBITO", "OUTROS",
    ],
}

# Prioridade de fonte documental por atributo de Imóvel
PROPERTY_FIELD_PRIORITY: Dict[str, List[str]] = {
    "endereco_completo": ["ESCRITURA", "CERTIDAO_IMOVEL", "IPTU", "OUTROS"],
    "inscricao_municipal": ["IPTU", "ESCRITURA", "CERTIDAO_IMOVEL", "OUTROS"],
    "matricula_imovel": ["CERTIDAO_IMOVEL", "ESCRITURA", "IPTU", "OUTROS"],
    "cep": ["IPTU", "ESCRITURA", "CERTIDAO_IMOVEL", "OUTROS"],
}

# Definição ordenada dos atributos exibidos no bloco "dados" (Pessoa) conforme mockup
PERSON_DISPLAY_FIELDS: List[Tuple[str, str]] = [
    ("nome_completo", "Nome Completo"),
    ("data_nascimento", "Data de Nascimento"),
    ("data_obito", "Data de Óbito"),
    ("nome_pais", "Nome dos Pais"),
    ("cpf", "CPF"),
    ("rg", "RG"),
]

# Definição ordenada dos atributos exibidos no bloco "dados imovel" (Imóvel) conforme mockup
PROPERTY_DISPLAY_FIELDS: List[Tuple[str, str]] = [
    ("endereco_completo", "Endereço + Complementos"),
    ("inscricao_municipal", "Inscrição Municipal"),
    ("matricula_imovel", "Matrícula do Imóvel"),
    ("cep", "CEP"),
]


@dataclass
class FieldAlternative:
    """Representa um valor candidato vindo de um documento específico."""
    value: str
    doc_id: int
    doc_name: str
    doc_type: str


@dataclass
class ConsolidatedField:
    """Representa um atributo consolidado pronto para exibição na GUI."""
    key: str
    label: str
    display_value: str                 # Valor final exibido (override ou melhor extraído)
    extracted_value: str               # Melhor valor extraído pelos documentos (vazio se não encontrado)
    source_doc_name: str = ""          # Nome do documento de onde veio o extracted_value
    source_doc_type: str = ""          # Tipo do documento de onde veio o extracted_value
    is_overridden: bool = False        # True se foi editado manualmente pelo usuário
    has_conflict: bool = False         # True se documentos diferentes trouxeram valores divergentes
    alternatives: List[FieldAlternative] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────
# Funções auxiliares de normalização e comparação
# ──────────────────────────────────────────────────────────────────

def strip_accents(text: str) -> str:
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_cpf_key(val: Optional[str]) -> str:
    if not val:
        return ""
    digits = re.sub(r"\D", "", str(val))
    return digits if len(digits) == 11 else ""


def format_cpf_display(val: Optional[str]) -> str:
    if not val:
        return ""
    digits = re.sub(r"\D", "", str(val))
    if len(digits) == 11:
        return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"
    return str(val).strip().upper()


def normalize_rg_key(val: Optional[str]) -> str:
    if not val:
        return ""
    cleaned = re.sub(r"[^0-9A-Z]", "", str(val).upper())
    # Ignora matrículas de 32 dígitos colocadas por engano
    if len(cleaned) < 5 or len(cleaned) > 14:
        return ""
    return cleaned.lstrip("0") or cleaned


def normalize_name_key(val: Optional[str]) -> str:
    if not val:
        return ""
    ascii_up = strip_accents(str(val).upper())
    words = re.findall(r"[A-Z]+", ascii_up)
    core_words = [w for w in words if w not in _NAME_PARTICLES and len(w) > 1]
    return " ".join(core_words)


def normalize_generic_key(val: Optional[str]) -> str:
    if not val:
        return ""
    ascii_up = strip_accents(str(val).upper())
    return re.sub(r"[^0-9A-Z]", "", ascii_up)


def names_are_compatible(name_key_a: str, name_key_b: str) -> bool:
    """
    Verifica se dois nomes normalizados pertencem plausivelmente à mesma pessoa.
    Cobre:
    - Nomes idênticos
    - Mudança de nome de casado(a) (ex: MARIA SILVA vs MARIA SILVA SANTOS),
      desde que os dois primeiros nomes coincidam e um seja subconjunto do outro.
    """
    if not name_key_a or not name_key_b:
        return False
    if name_key_a == name_key_b:
        return True
    tokens_a = name_key_a.split()
    tokens_b = name_key_b.split()
    if len(tokens_a) < 2 or len(tokens_b) < 2:
        return False
    # Os dois primeiros nomes próprios devem coincidir exatamente
    if tokens_a[0] != tokens_b[0] or tokens_a[1] != tokens_b[1]:
        return False
    set_a, set_b = set(tokens_a), set(tokens_b)
    return set_a.issubset(set_b) or set_b.issubset(set_a)


def _clean_extracted_value(val: Any) -> str:
    """Limpa valores nulos, placeholders ou tokens não resolvidos."""
    if val is None:
        return ""
    if isinstance(val, list):
        items = [_clean_extracted_value(x) for x in val]
        items = [x for x in items if x]
        return " / ".join(items)
    s = str(val).strip().upper()
    if s in ("", "-", "NULL", "NONE", "N/A", "NAO INFORMADO", "NÃO INFORMADO", "[REMOVIDO_LGPD]"):
        return ""
    if re.fullmatch(r"\[[A-Z_]+_\d{3}\]", s):
        return ""
    return s


class EntityResolver:
    """
    Motor de reconhecimento e consolidação de Pessoas e Imóveis por sessão.
    """

    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or DatabaseManager()
        self.masker = DataMasker()

    def unpack_extraction_payload(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Desempacota e desmascara o JSON de uma linha da tabela extractions."""
        raw_json = row.get("extracted_data_json") or "{}"
        try:
            payload = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
        except Exception:
            payload = {}

        if isinstance(payload, dict) and "dados" in payload:
            dados = payload.get("dados") or {}
            token_map = payload.get("token_map") or {}
            if token_map:
                dados = self.masker.demask_dict(dados, token_map)
        elif isinstance(payload, dict):
            dados = payload
        else:
            dados = {}

        return dados if isinstance(dados, dict) else {}

    def ensure_session_resolved(self, session_id: int) -> None:
        """
        Garante que todas as extrações da sessão já tenham sido processadas pelo EntityResolver.
        Útil para sessões criadas antes da v1.1 ou caso alguma extração não tenha vínculo.
        """
        extractions = self.db.get_session_extractions(session_id)
        if not extractions:
            return
        existing_links = self.db.get_session_links(session_id)
        linked_extraction_ids = {l["extraction_id"] for l in existing_links}

        for ext in extractions:
            if ext["id"] not in linked_extraction_ids:
                try:
                    raw_payload = json.loads(ext.get("extracted_data_json") or "{}")
                except Exception:
                    raw_payload = {}
                self.link_extraction(
                    session_id=session_id,
                    extraction_id=ext["id"],
                    doc_type=ext.get("document_type") or "OUTROS",
                    extracted_data=raw_payload,
                )

    def link_extraction(
        self,
        session_id: int,
        extraction_id: int,
        doc_type: str,
        extracted_data: Dict[str, Any],
    ) -> None:
        """
        Analisa uma extração recém-salva, identifica Pessoas (titular, cônjuges, comprador, vendedor)
        e Imóveis, faz o matching com as entidades já existentes na sessão e grava os vínculos.
        """
        if isinstance(extracted_data, dict) and "dados" in extracted_data:
            dados = extracted_data.get("dados") or {}
            token_map = extracted_data.get("token_map") or {}
            if token_map:
                dados = self.masker.demask_dict(dados, token_map)
        elif isinstance(extracted_data, dict):
            dados = extracted_data
        else:
            dados = {}

        tipo = str(doc_type or dados.get("tipo") or "OUTROS").strip().upper()

        # 1. Extrai candidatos a PESSOA (APENAS titular, cônjuges, comprador e vendedor)
        person_candidates = self._extract_person_candidates(tipo, dados)
        for role, json_path, p_dict in person_candidates:
            person_id = self._match_or_create_person(session_id, p_dict)
            if person_id:
                self.db.add_extraction_link(
                    extraction_id=extraction_id,
                    entity_type="PERSON",
                    entity_id=person_id,
                    role=role,
                    json_path=json_path,
                )

        # 2. Extrai candidato a IMÓVEL (se presente no documento)
        prop_dict = self._extract_property_candidate(tipo, dados)
        if prop_dict:
            prop_id = self._match_or_create_property(session_id, prop_dict)
            if prop_id:
                self.db.add_extraction_link(
                    extraction_id=extraction_id,
                    entity_type="PROPERTY",
                    entity_id=prop_id,
                    role=tipo,
                    json_path="documento.imovel",
                )

    def _extract_person_candidates(
        self,
        tipo: str,
        dados: Dict[str, Any],
    ) -> List[Tuple[str, str, Dict[str, Any]]]:
        """
        # [Opus - v1.1 Sessions Redesign]: Retorna lista de (role, json_path, person_dict).
        # Regra estrita definida pelo usuário:
        # Viram Pessoa APENAS: titular, cônjuges, comprador e vendedor.
        # Pais/avós ficam como atributo (nome_pais) do titular/cônjuge.
        # Contribuinte (IPTU) e proprietários (CERTIDAO_IMOVEL) NÃO viram Pessoa.
        """
        if tipo in PROPERTY_ONLY_PERSON_SKIP_TYPES:
            return []

        candidates: List[Tuple[str, str, Dict[str, Any]]] = []

        if tipo == "CASAMENTO":
            conjuges = dados.get("conjuges")
            if isinstance(conjuges, list) and conjuges:
                for idx, c in enumerate(conjuges):
                    if isinstance(c, dict) and self._has_person_identity(c):
                        candidates.append(("CONJUGE", f"documento.conjuges[{idx}]", c))
            elif isinstance(dados.get("pessoa"), dict) and self._has_person_identity(dados["pessoa"]):
                candidates.append(("CONJUGE", "documento.pessoa", dados["pessoa"]))
            return candidates

        if tipo in ("ESCRITURA", "ESCRITURA_COMPRA_VENDA"):
            compradores = dados.get("compradores")
            if isinstance(compradores, list) and compradores:
                for idx, comp in enumerate(compradores):
                    if isinstance(comp, dict) and self._has_person_identity(comp):
                        candidates.append(("COMPRADOR", f"documento.compradores[{idx}]", comp))
            elif isinstance(dados.get("pessoa"), dict) and self._has_person_identity(dados["pessoa"]):
                candidates.append(("COMPRADOR", "documento.pessoa", dados["pessoa"]))

            vendedores = dados.get("vendedores")
            if isinstance(vendedores, list) and vendedores:
                for idx, vend in enumerate(vendedores):
                    if isinstance(vend, dict) and self._has_person_identity(vend):
                        candidates.append(("VENDEDOR", f"documento.vendedores[{idx}]", vend))
            return candidates

        # Demais documentos pessoais (RG, CNH, CIN, CPF, NASCIMENTO, OBITO, etc.) -> TITULAR
        pessoa = dados.get("pessoa")
        if isinstance(pessoa, dict) and self._has_person_identity(pessoa):
            candidates.append(("TITULAR", "documento.pessoa", pessoa))

        return candidates

    @staticmethod
    def _has_person_identity(p_dict: Dict[str, Any]) -> bool:
        """Verifica se o dicionário da pessoa possui ao menos nome, CPF ou RG válido."""
        nome = _clean_extracted_value(p_dict.get("nome_completo"))
        cpf = normalize_cpf_key(p_dict.get("cpf"))
        rg = normalize_rg_key(p_dict.get("rg"))
        return bool(nome or cpf or rg)

    def _match_or_create_person(self, session_id: int, p_dict: Dict[str, Any]) -> Optional[int]:
        raw_name = _clean_extracted_value(p_dict.get("nome_completo"))
        cpf_key = normalize_cpf_key(p_dict.get("cpf"))
        rg_key = normalize_rg_key(p_dict.get("rg"))
        name_key = normalize_name_key(raw_name)

        if not (raw_name or cpf_key or rg_key):
            return None

        existing_persons = self.db.get_session_persons(session_id)
        matched_person: Optional[Dict[str, Any]] = None

        # 1. Busca por CPF idêntico (maior confiança)
        if cpf_key:
            for ep in existing_persons:
                if ep.get("cpf_key") and ep["cpf_key"] == cpf_key:
                    matched_person = ep
                    break

        # 2. Busca por RG idêntico (desde que não haja conflito de CPF e o nome seja compatível ou ausente)
        if not matched_person and rg_key:
            for ep in existing_persons:
                if cpf_key and ep.get("cpf_key") and ep["cpf_key"] != cpf_key:
                    continue
                if ep.get("rg_key") and ep["rg_key"] == rg_key:
                    if not name_key or not ep.get("name_key") or names_are_compatible(name_key, ep["name_key"]):
                        matched_person = ep
                        break

        # 3. Busca por Nome compatível (desde que não haja conflito de CPF)
        if not matched_person and name_key:
            for ep in existing_persons:
                if cpf_key and ep.get("cpf_key") and ep["cpf_key"] != cpf_key:
                    continue
                if ep.get("name_key") and names_are_compatible(name_key, ep["name_key"]):
                    matched_person = ep
                    break

        display_name = raw_name or (f"CPF {format_cpf_display(cpf_key)}" if cpf_key else f"RG {rg_key}")

        if matched_person:
            pid = matched_person["id"]
            # Enriquece chaves que estavam vazias na pessoa existente
            new_disp = matched_person["display_name"]
            if raw_name and (
                new_disp.startswith("CPF ")
                or new_disp.startswith("RG ")
                or len(raw_name) > len(new_disp)
            ):
                # Só atualiza o display_name automaticamente se o usuário não tiver feito override manual de nome_completo
                try:
                    ov = json.loads(matched_person.get("overrides_json") or "{}")
                except Exception:
                    ov = {}
                if "nome_completo" not in ov:
                    new_disp = raw_name

            self.db.update_person_keys(
                person_id=pid,
                display_name=new_disp,
                cpf_key=matched_person["cpf_key"] or cpf_key,
                rg_key=matched_person["rg_key"] or rg_key,
                name_key=matched_person["name_key"] or name_key,
            )
            return pid

        return self.db.create_person(
            session_id=session_id,
            display_name=display_name,
            cpf_key=cpf_key,
            rg_key=rg_key,
            name_key=name_key,
        )

    def _extract_property_candidate(self, tipo: str, dados: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        imovel = dados.get("imovel")
        if not isinstance(imovel, dict):
            # Verifica se algum campo de imóvel veio na raiz em documentos de imóvel
            if tipo in ("IPTU", "CERTIDAO_IMOVEL", "ESCRITURA", "ESCRITURA_COMPRA_VENDA"):
                imovel = {
                    "endereco_completo": dados.get("endereco_completo"),
                    "inscricao_municipal": dados.get("inscricao_municipal"),
                    "matricula_imovel": dados.get("matricula_imovel") or dados.get("matricula"),
                    "cep": dados.get("cep"),
                }
            else:
                return None

        end = _clean_extracted_value(imovel.get("endereco_completo"))
        insc = _clean_extracted_value(imovel.get("inscricao_municipal"))
        mat = _clean_extracted_value(imovel.get("matricula_imovel"))
        cep = _clean_extracted_value(imovel.get("cep"))

        if not (end or insc or mat or cep):
            return None

        return {
            "endereco_completo": end,
            "inscricao_municipal": insc,
            "matricula_imovel": mat,
            "cep": cep,
        }

    def _match_or_create_property(self, session_id: int, prop_dict: Dict[str, Any]) -> Optional[int]:
        end = prop_dict.get("endereco_completo") or ""
        insc = prop_dict.get("inscricao_municipal") or ""
        mat = prop_dict.get("matricula_imovel") or ""
        cep = prop_dict.get("cep") or ""

        mat_key = normalize_generic_key(mat)
        insc_key = normalize_generic_key(insc)
        addr_key = normalize_generic_key(end)
        cep_key = re.sub(r"\D", "", cep)

        existing_props = self.db.get_session_properties(session_id)
        matched_prop: Optional[Dict[str, Any]] = None

        # 1. Matrícula do imóvel
        if mat_key:
            for pr in existing_props:
                if pr.get("matricula_key") and pr["matricula_key"] == mat_key:
                    matched_prop = pr
                    break

        # 2. Inscrição municipal
        if not matched_prop and insc_key:
            for pr in existing_props:
                if pr.get("inscricao_key") and pr["inscricao_key"] == insc_key:
                    matched_prop = pr
                    break

        # 3. Endereço normalizado ou CEP idêntico
        if not matched_prop and (addr_key or cep_key):
            for pr in existing_props:
                if addr_key and pr.get("address_key") and pr["address_key"] == addr_key:
                    matched_prop = pr
                    break
                if cep_key and pr.get("cep_key") and pr["cep_key"] == cep_key and (not addr_key or not pr.get("address_key")):
                    matched_prop = pr
                    break

        label = end or (f"MATRÍCULA {mat}" if mat else (f"INSCRIÇÃO {insc}" if insc else f"CEP {cep}"))

        if matched_prop:
            pr_id = matched_prop["id"]
            new_label = matched_prop["label"]
            if end and (
                new_label.startswith("MATRÍCULA ")
                or new_label.startswith("INSCRIÇÃO ")
                or new_label.startswith("CEP ")
                or len(end) > len(new_label)
            ):
                try:
                    ov = json.loads(matched_prop.get("overrides_json") or "{}")
                except Exception:
                    ov = {}
                if "endereco_completo" not in ov:
                    new_label = end

            self.db.update_property_keys(
                property_id=pr_id,
                label=new_label,
                matricula_key=matched_prop["matricula_key"] or mat_key,
                inscricao_key=matched_prop["inscricao_key"] or insc_key,
                address_key=matched_prop["address_key"] or addr_key,
                cep_key=matched_prop["cep_key"] or cep_key,
            )
            return pr_id

        return self.db.create_property(
            session_id=session_id,
            label=label,
            matricula_key=mat_key,
            inscricao_key=insc_key,
            address_key=addr_key,
            cep_key=cep_key,
        )

    # ──────────────────────────────────────────────────────────────────
    # Consolidação de Dados com Prioridade de Fonte + Conflitos + Overrides
    # ──────────────────────────────────────────────────────────────────

    def _resolve_person_dict_from_link(self, dados: Dict[str, Any], json_path: str) -> Dict[str, Any]:
        """Recupera o sub-dicionário específico da pessoa dentro do documento (ex: conjuges[1])."""
        if not isinstance(dados, dict):
            return {}
        m = re.match(r"^documento\.(conjuges|compradores|vendedores)\[(\d+)\]$", json_path or "")
        if m:
            list_key = m.group(1)
            idx = int(m.group(2))
            arr = dados.get(list_key)
            if isinstance(arr, list) and 0 <= idx < len(arr) and isinstance(arr[idx], dict):
                return arr[idx]
        pessoa = dados.get("pessoa")
        if isinstance(pessoa, dict):
            return pessoa
        return {}

    def consolidate_person_data(self, person_id: int) -> List[ConsolidatedField]:
        """
        Retorna os 6 campos consolidados da Pessoa selecionada:
        Nome Completo, Data de Nascimento, Data de Óbito, Nome dos Pais, CPF, RG.
        """
        person_row = self.db.get_person(person_id)
        if not person_row:
            return [
                ConsolidatedField(key=k, label=lbl, display_value="", extracted_value="")
                for k, lbl in PERSON_DISPLAY_FIELDS
            ]

        try:
            overrides: Dict[str, str] = json.loads(person_row.get("overrides_json") or "{}")
        except Exception:
            overrides = {}

        linked_docs = self.db.get_entity_extractions("PERSON", person_id)

        # Coleta candidatos por atributo
        candidates_by_field: Dict[str, List[FieldAlternative]] = {k: [] for k, _ in PERSON_DISPLAY_FIELDS}

        for doc_row in linked_docs:
            dados = self.unpack_extraction_payload(doc_row)
            doc_type = str(doc_row.get("document_type") or dados.get("tipo") or "OUTROS").upper()
            doc_name = str(doc_row.get("original_name") or f"DOC #{doc_row['id']}")
            p_dict = self._resolve_person_dict_from_link(dados, doc_row.get("link_json_path") or "documento.pessoa")

            for field_key, _ in PERSON_DISPLAY_FIELDS:
                raw_val = p_dict.get(field_key)
                # Em CIN, caso 'rg' esteja vazio mas 'registro_geral_antigo' exista no documento
                if field_key == "rg" and not raw_val and doc_type == "CIN":
                    raw_val = dados.get("registro_geral_antigo")
                cleaned = _clean_extracted_value(raw_val)
                if field_key == "cpf" and cleaned:
                    cleaned = format_cpf_display(cleaned)
                if cleaned:
                    candidates_by_field[field_key].append(
                        FieldAlternative(
                            value=cleaned,
                            doc_id=doc_row["id"],
                            doc_name=doc_name,
                            doc_type=doc_type,
                        )
                    )

        results: List[ConsolidatedField] = []
        for field_key, label in PERSON_DISPLAY_FIELDS:
            alts = candidates_by_field[field_key]
            prio_list = PERSON_FIELD_PRIORITY.get(field_key, [])

            def _sort_key(alt: FieldAlternative) -> int:
                try:
                    return prio_list.index(alt.doc_type)
                except ValueError:
                    return len(prio_list)

            sorted_alts = sorted(alts, key=_sort_key)
            best_alt = sorted_alts[0] if sorted_alts else None
            extracted_val = best_alt.value if best_alt else ""

            # Verifica se há divergência real entre documentos
            norm_groups: Dict[str, FieldAlternative] = {}
            for alt in sorted_alts:
                if field_key == "cpf":
                    nk = normalize_cpf_key(alt.value) or normalize_generic_key(alt.value)
                elif field_key == "rg":
                    nk = normalize_rg_key(alt.value) or normalize_generic_key(alt.value)
                elif field_key in ("nome_completo", "nome_pais"):
                    nk = normalize_name_key(alt.value)
                else:
                    nk = normalize_generic_key(alt.value)
                if nk and nk not in norm_groups:
                    norm_groups[nk] = alt

            has_conflict = len(norm_groups) > 1
            unique_alts = list(norm_groups.values()) if has_conflict else sorted_alts

            is_overridden = field_key in overrides and bool(str(overrides[field_key]).strip())
            display_val = overrides[field_key].strip().upper() if is_overridden else extracted_val

            results.append(
                ConsolidatedField(
                    key=field_key,
                    label=label,
                    display_value=display_val,
                    extracted_value=extracted_val,
                    source_doc_name=best_alt.doc_name if best_alt else "",
                    source_doc_type=best_alt.doc_type if best_alt else "",
                    is_overridden=is_overridden,
                    has_conflict=has_conflict,
                    alternatives=unique_alts,
                )
            )

        return results

    def consolidate_property_data(self, property_id: int) -> List[ConsolidatedField]:
        """
        Retorna os 4 campos consolidados do Imóvel selecionado:
        Endereço + Complementos, Inscrição Municipal, Matrícula do Imóvel, CEP.
        """
        prop_row = self.db.get_property(property_id)
        if not prop_row:
            return [
                ConsolidatedField(key=k, label=lbl, display_value="", extracted_value="")
                for k, lbl in PROPERTY_DISPLAY_FIELDS
            ]

        try:
            overrides: Dict[str, str] = json.loads(prop_row.get("overrides_json") or "{}")
        except Exception:
            overrides = {}

        linked_docs = self.db.get_entity_extractions("PROPERTY", property_id)
        candidates_by_field: Dict[str, List[FieldAlternative]] = {k: [] for k, _ in PROPERTY_DISPLAY_FIELDS}

        for doc_row in linked_docs:
            dados = self.unpack_extraction_payload(doc_row)
            doc_type = str(doc_row.get("document_type") or dados.get("tipo") or "OUTROS").upper()
            doc_name = str(doc_row.get("original_name") or f"DOC #{doc_row['id']}")
            prop_cand = self._extract_property_candidate(doc_type, dados) or {}

            for field_key, _ in PROPERTY_DISPLAY_FIELDS:
                cleaned = _clean_extracted_value(prop_cand.get(field_key))
                if cleaned:
                    candidates_by_field[field_key].append(
                        FieldAlternative(
                            value=cleaned,
                            doc_id=doc_row["id"],
                            doc_name=doc_name,
                            doc_type=doc_type,
                        )
                    )

        results: List[ConsolidatedField] = []
        for field_key, label in PROPERTY_DISPLAY_FIELDS:
            alts = candidates_by_field[field_key]
            prio_list = PROPERTY_FIELD_PRIORITY.get(field_key, [])

            def _sort_key(alt: FieldAlternative) -> int:
                try:
                    return prio_list.index(alt.doc_type)
                except ValueError:
                    return len(prio_list)

            sorted_alts = sorted(alts, key=_sort_key)
            best_alt = sorted_alts[0] if sorted_alts else None
            extracted_val = best_alt.value if best_alt else ""

            norm_groups: Dict[str, FieldAlternative] = {}
            for alt in sorted_alts:
                nk = normalize_generic_key(alt.value)
                if nk and nk not in norm_groups:
                    norm_groups[nk] = alt

            has_conflict = len(norm_groups) > 1
            unique_alts = list(norm_groups.values()) if has_conflict else sorted_alts

            is_overridden = field_key in overrides and bool(str(overrides[field_key]).strip())
            display_val = overrides[field_key].strip().upper() if is_overridden else extracted_val

            results.append(
                ConsolidatedField(
                    key=field_key,
                    label=label,
                    display_value=display_val,
                    extracted_value=extracted_val,
                    source_doc_name=best_alt.doc_name if best_alt else "",
                    source_doc_type=best_alt.doc_type if best_alt else "",
                    is_overridden=is_overridden,
                    has_conflict=has_conflict,
                    alternatives=unique_alts,
                )
            )

        return results
