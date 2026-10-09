"""
DocFiller — Organizador e Validador (Cross-Validation)
======================================================

Responsável por:
1. Receber os múltiplos JSONs estruturados extraídos pela API.
2. Fazer o cross-validation (dupla autenticação) comparando dados entre os documentos.
3. Consolidar as informações únicas em um único "Payload" final.
4. Chamar o DataMasker para realizar o DEMASK (descriptografar) os tokens 
   para os dados originais do usuário antes de preencher a web.
"""

from typing import Any, Dict, List, Tuple
from dataclasses import dataclass

# Importa de forma relativa ou por nome do projeto dependendo do setup. 
# Assumindo execução no contexto do projeto.
try:
    from .models_gemini import ExtractedDocument
    from .masker_gemini import DataMasker
except ImportError:
    pass

@dataclass
class ValidationIssue:
    level: str  # "WARNING" ou "ERROR"
    message: str

@dataclass
class ConsolidatedPayload:
    data: Dict[str, Any]
    issues: List[ValidationIssue]
    is_valid: bool

class DocumentOrganizer:
    """
    Consolida e cruza dados de múltiplos documentos.
    """
    
    def __init__(self, masker: 'DataMasker'):
        self.masker = masker

    def _extract_all_persons(self, doc_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
        """[GEMINI - CORREÇÃO H1]: Extrai todas as entidades de pessoa de qualquer tipo de documento."""
        persons = []
        if "pessoa" in doc_dict and isinstance(doc_dict["pessoa"], dict):
            persons.append(doc_dict["pessoa"])
        if "contribuinte" in doc_dict and isinstance(doc_dict["contribuinte"], dict):
            persons.append(doc_dict["contribuinte"])
        for key in ["conjuges", "compradores", "vendedores", "proprietarios", "pessoas_citadas"]:
            if key in doc_dict and isinstance(doc_dict[key], list):
                for p in doc_dict[key]:
                    if isinstance(p, dict):
                        persons.append(p)
        return persons

    def _extract_all_properties(self, doc_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
        """[GEMINI - CORREÇÃO H1]: Extrai todas as informações de imóveis de qualquer documento."""
        props = []
        if "imovel" in doc_dict and isinstance(doc_dict["imovel"], dict):
            props.append(doc_dict["imovel"])
        if "imoveis_citados" in doc_dict and isinstance(doc_dict["imoveis_citados"], list):
            for pr in doc_dict["imoveis_citados"]:
                if isinstance(pr, dict):
                    props.append(pr)
        return props

    def process_and_validate(self, docs_with_tokens: List[Tuple['ExtractedDocument', Dict[str, str]]]) -> ConsolidatedPayload:
        """
        Recebe uma lista de tuplas (Documento Tipado, Token Map daquele documento).
        Retorna o payload final limpo (com dados reais desmascarados) e lista de alertas.
        """
        issues: List[ValidationIssue] = []
        flat_data = {}
        
        all_cpfs = set()
        all_enderecos = set()
        first_names_parents = set()

        for doc, token_map in docs_with_tokens:
            doc_type = doc.documento.tipo
            doc_dict = doc.documento.model_dump(exclude_none=True)

            # [LEGACY]: Unia todos os token_maps em um dicionário único global antes do desmascaramento,
            # o que causava sobrescrita e colisão quando múltiplos documentos continham [NOME_001], [CPF_001].
            # [GEMINI - CORREÇÃO C5]: Desmascara cada documento individualmente com seu respectivo token_map!
            if token_map:
                doc_dict = self.masker.demask_dict(doc_dict, token_map)

            # Consolidação: achata campos já desmascarados
            self._flatten_dict(doc_dict, flat_data)

            # [LEGACY]: Verificava apenas a chave "pessoa", ignorando cônjuges, compradores, vendedores e proprietários
            # [GEMINI - CORREÇÃO H1]: Cross-validation em todas as pessoas e imóveis de todos os tipos de documento
            persons = self._extract_all_persons(doc_dict)
            for p in persons:
                cpf = p.get("cpf")
                if cpf and cpf != "-" and len(cpf.strip()) >= 11:
                    all_cpfs.add(cpf.strip())
                pais = p.get("nome_pais")
                if pais and isinstance(pais, list):
                    for np in pais:
                        primeiro = np.strip().split(" ")[0].upper()
                        if len(primeiro) > 1:
                            first_names_parents.add(primeiro)

            properties = self._extract_all_properties(doc_dict)
            for pr in properties:
                end = pr.get("endereco_completo")
                if end and end != "-":
                    all_enderecos.add(end.strip())

        # 3. Cross-Validation (Regras de Negócio do Usuário)
        if len(all_cpfs) > 1:
            issues.append(ValidationIssue(
                level="ERROR", 
                message=f"Divergência de CPFs encontrada entre os documentos: {list(all_cpfs)}"
            ))

        if len(all_enderecos) > 1:
            issues.append(ValidationIssue(
                level="WARNING", 
                message=f"Endereços de imóveis divergem entre os documentos apresentados: {list(all_enderecos)}"
            ))

        if len(first_names_parents) > 2:
            issues.append(ValidationIssue(
                level="WARNING",
                message=f"Divergência no primeiro nome dos pais identificada. Nomes encontrados: {list(first_names_parents)}"
            ))

        is_valid = not any(issue.level == "ERROR" for issue in issues)
        
        return ConsolidatedPayload(
            data=flat_data,
            issues=issues,
            is_valid=is_valid
        )

    def _flatten_dict(self, nested_dict: Dict[str, Any], flat_dict: Dict[str, Any], prefix: str = "") -> None:
        """Achata um dicionário aninhado (ex: pessoa.nome_completo -> pessoa_nome_completo)."""
        for k, v in nested_dict.items():
            # Pula o campo 'tipo' para não sujar os dados
            if k == "tipo": continue
            
            key = f"{prefix}{k}" if prefix else k
            if isinstance(v, dict):
                self._flatten_dict(v, flat_dict, f"{key}_")
            elif isinstance(v, list):
                # Para listas de pessoas (ex: conjuges, vendedores) vamos criar chaves indexadas
                for i, item in enumerate(v):
                    if isinstance(item, dict):
                        self._flatten_dict(item, flat_dict, f"{key}_{i}_")
                    else:
                        flat_dict[f"{key}_{i}"] = item
            else:
                # Mantém o valor que já existir se for igual, ou cria se não existir.
                # Conflitos (valores diferentes pra mesma chave) são tratados no cross-validation
                if key not in flat_dict:
                    flat_dict[key] = v

# ──────────────────────────────────────────────────────────────────
# Teste Rápido
# ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Módulo Organizer carregado com sucesso.")
