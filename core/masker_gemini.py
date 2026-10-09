"""
DocFiller — Módulo de Mascaramento Local de Dados Sensíveis
===========================================================

Este módulo garante que NENHUM dado pessoal identificável (PII) seja enviado
para APIs externas (Gemini, etc.) em texto claro.

Possui dois modos de operação (LGPD Compliance):
    1. MODO SCRUB (Remoção Irreversível):
       Aplicado a dados proibidos (Telefone, Email, Valores, Conta, PIX).
       O dado é apagado (substituído por [REMOVIDO_LGPD]) e NUNCA é armazenado,
       sendo impossível de ser recuperado.

    2. MODO MASK (Tokenização Reversível):
       Aplicado a dados que precisamos extrair estruturadamente (CPF, RG, Nome, etc.).
       Substituído por tokens ([CPF_001]) e o mapeamento é guardado EXCLUSIVAMENTE
       na memória local da sua máquina. O Gemini interpreta apenas os tokens, e
       o demask() restaura os dados reais localmente ao final.
"""

from __future__ import annotations

import re
import json
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from pathlib import Path


class SensitiveCategory(str, Enum):
    """Categorias de dados sensíveis detectáveis."""
    CPF = "CPF"
    RG = "RG"
    CNH = "CNH"
    PHONE = "TELEFONE"       # SCRUB
    EMAIL = "EMAIL"          # SCRUB
    DATE = "DATA"
    MONEY = "VALOR"          # SCRUB
    NAME = "NOME"
    ADDRESS = "ENDERECO"
    BANK_ACCOUNT = "CONTA"   # SCRUB
    PIX_KEY = "CHAVE_PIX"    # SCRUB
    CEP = "CEP"

# Categorias que devem ser apagadas definitivamente (LGPD)
SCRUB_CATEGORIES = {
    SensitiveCategory.PHONE,
    SensitiveCategory.EMAIL,
    SensitiveCategory.MONEY,
    SensitiveCategory.BANK_ACCOUNT,
    SensitiveCategory.PIX_KEY,
}

SCRUB_TOKEN = "[REMOVIDO_LGPD]"


@dataclass
class MaskedToken:
    """Representa um dado mascarado com seu valor original (apenas para modo MASK)."""
    token: str              # Ex: "[CPF_001]"
    category: SensitiveCategory
    original_value: str     # Valor real (armazenado apenas localmente)
    start_pos: int          # Posição inicial no texto original
    end_pos: int            # Posição final no texto original


@dataclass
class MaskingResult:
    """Resultado da operação de mascaramento."""
    masked_text: str
    tokens: list[MaskedToken] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def token_map(self) -> dict[str, str]:
        """Retorna mapeamento token → valor original."""
        return {t.token: t.original_value for t in self.tokens}

    @property
    def has_sensitive_data(self) -> bool:
        return len(self.tokens) > 0 or len(self.stats) > 0


class DataMasker:
    """
    Motor de mascaramento local de dados sensíveis brasileiros (LGPD Compliant).
    """

    def __init__(
        self,
        mask_cpf: bool = True,
        mask_rg: bool = True,
        mask_cnh: bool = True,
        mask_phone: bool = True,
        mask_email: bool = True,
        mask_date: bool = True,
        mask_money: bool = True,
        mask_name: bool = True,
        mask_address: bool = True,
        mask_bank: bool = True,
        mask_pix: bool = True,
        mask_cep: bool = True,
        custom_patterns: list[tuple[str, SensitiveCategory]] | None = None,
        name_labels: list[str] | None = None,
        address_labels: list[str] | None = None,
    ):
        self._counters: dict[str, int] = {}
        self._all_tokens: list[MaskedToken] = []

        # Configuração de quais categorias processar
        self._enabled: dict[SensitiveCategory, bool] = {
            SensitiveCategory.CPF: mask_cpf,
            SensitiveCategory.RG: mask_rg,
            SensitiveCategory.CNH: mask_cnh,
            SensitiveCategory.PHONE: mask_phone,
            SensitiveCategory.EMAIL: mask_email,
            SensitiveCategory.DATE: mask_date,
            SensitiveCategory.MONEY: mask_money,
            SensitiveCategory.NAME: mask_name,
            SensitiveCategory.ADDRESS: mask_address,
            SensitiveCategory.BANK_ACCOUNT: mask_bank,
            SensitiveCategory.PIX_KEY: mask_pix,
            SensitiveCategory.CEP: mask_cep,
        }

        # Labels para detecção contextual de nomes
        # [LEGACY]: Lista restrita que não contemplava termos específicos de certidões civis
        # [GEMINI - CORREÇÃO C3]: Rótulos expandidos para certidões de nascimento, casamento, óbito e escrituras
        self._name_labels = name_labels or [
            "nome", "name", "nome completo", "rm", "nm",
            "proprietário", "proprietario",
            "comprador", "compradores", "vendedor", "vendedores", 
            "outorgante", "outorgado", "locador", "locatário", "locatario", 
            "beneficiário", "beneficiario", "pagador", "titular", "responsável",
            "responsavel", "cônjuge", "conjuge", "cônjuges", "conjuges",
            "filho", "filha", "filhos", "filhas", "filiação", "filiacao",
            "pai", "mãe", "mae", "pais", "nascido", "nascida",
            "registrado", "registrada", "criança", "crianca",
            "falecido", "falecida", "de cujus", "declarante",
            "nubente", "nubentes", "contraente", "contraentes",
            "avô", "avó", "avo", "avós", "avos", "paternos", "maternos",
            "representante", "procurador", "testemunha",
            "contratante", "contratado", "requerente",
            # Documentos Eleitorais, Militares, Funcionais e Acadêmicos
            "eleitor", "eleitora", "militar", "policial", "posto", "graduação", "graduacao",
            "patente", "matrícula", "matricula", "funcional", "aluno", "aluna", "estudante",
            "formando", "formanda", "diplomado", "diplomada", "concluinte", "egresso", "egressa",
            "bacharel", "licenciado", "diretor", "diretora", "reitor", "reitora",
            # CIN, Passaporte, Reservista, SUS e DNE
            "nome social", "passaporte", "passport", "viajante", "paciente", "cns", "sus",
            "reservista", "alistado", "conscrito", "dne", "estudantil",
        ]

        # Labels para detecção contextual de endereços
        self._address_labels = address_labels or [
            "endereço", "endereco", "address", "logradouro",
            "rua", "avenida", "av", "travessa", "alameda",
            "praça", "praca", "rodovia", "estrada",
            "residência", "residencia", "domicílio", "domicilio",
            "localizado", "situado", "sito",
        ]

        self._custom_patterns = custom_patterns or []

    def _next_token(self, category: SensitiveCategory) -> str:
        """Gera próximo token sequencial para uma categoria MASK."""
        key = category.value
        self._counters[key] = self._counters.get(key, 0) + 1
        return f"[{key}_{self._counters[key]:03d}]"

    def _reset(self) -> None:
        self._counters.clear()
        self._all_tokens.clear()

    # ──────────────────────────────────────────────────────────────
    # Padrões regex para dados sensíveis brasileiros
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _cpf_pattern() -> re.Pattern:
        return re.compile(r"\b(\d{3}\.\d{3}\.\d{3}-\d{2})\b")

    @staticmethod
    def _cpf_contextual_pattern() -> re.Pattern:
        return re.compile(r"(?:CPF|cpf)\s*[:.]?\s*(\d{11})\b")

    @staticmethod
    def _rg_pattern() -> re.Pattern:
        return re.compile(r"\b(\d{1,2}[.\s]?\d{3}[.\s]?\d{3}[-.\s]?[\dxX])\b")

    @staticmethod
    def _cnh_pattern() -> re.Pattern:
        return re.compile(
            r"(?:CNH|habilitação|habilitacao|registro\s*nacional)\s*[:.]?\s*(\d{11})",
            re.IGNORECASE
        )

    @staticmethod
    def _phone_pattern() -> re.Pattern:
        return re.compile(
            r"(?:\+55\s*)?(?:\(?\d{2}\)?\s*)?(?:9\s*\d{4}[-\s]?\d{4}|\d{4}[-\s]?\d{4})\b"
        )

    @staticmethod
    def _email_pattern() -> re.Pattern:
        return re.compile(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
        )

    @staticmethod
    def _date_pattern() -> re.Pattern:
        return re.compile(
            r"\b(\d{2}/\d{2}/\d{4})\b"
        )

    @staticmethod
    def _money_pattern() -> re.Pattern:
        return re.compile(
            r"(?:R\$\s*|BRL\s*)?\b\d{1,3}(?:\.\d{3})*,\d{2}\b"
        )

    @staticmethod
    def _cep_pattern() -> re.Pattern:
        # [LEGACY]: r"\b(\d{5}-?\d{3})\b" casava falsamente com fatias de matrículas longas (ex: 08-01-95-2003-1-00229-049-01)
        # [GEMINI - CORREÇÃO FALSO POSITIVO CEP]: Lookaround negativo garante que o CEP não faz parte de número longo/matrícula
        return re.compile(r"(?<![\d\-])\b(\d{5}-?\d{3})\b(?![\d\-])")

    @staticmethod
    def _bank_account_pattern() -> re.Pattern:
        return re.compile(
            r"(?:ag[eê]ncia|ag\.?)\s*[:.]?\s*(\d{3,5}(?:-\d)?)\s*"
            r"(?:conta|c/c|cc)\s*[:.]?\s*(\d{4,12}(?:-\d)?)|"
            r"(?:banco)\s*[:.]?\s*(\d{3})\b",
            re.IGNORECASE
        )

    @staticmethod
    def _pix_pattern() -> re.Pattern:
        return re.compile(
            r"(?:pix|chave)\s*[:.]?\s*("
            r"[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}" 
            r"|[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
            r"|\+?\d{10,13}"
            r"|\d{11}"
            r")",
            re.IGNORECASE
        )

    def _name_pattern(self) -> re.Pattern:
        # [LEGACY]: Exigia pontuação fixa antes do nome e não aceitava pipes | comuns em tabelas de RG
        # [GEMINI - CORREÇÃO C3/RG]: Suporte a pipes de tabelas (| rm PEDRO...), rótulos de OCR e quebras de linha
        labels = "|".join(re.escape(l) for l in self._name_labels)
        return re.compile(
            rf"(?:^|[|\n\r;])?[ \t]*(?:{labels})[ \t|]*[:\.\-–—\s]+([A-Za-z\u00C0-\u00FF]{{2,}}(?:[ \t]+[A-Za-z\u00C0-\u00FF]+)+)",
            re.IGNORECASE | re.UNICODE
        )

    def _address_pattern(self) -> re.Pattern:
        labels = "|".join(re.escape(l) for l in self._address_labels)
        return re.compile(
            rf"(?:{labels})\s*[:.\-–—]\s*"
            rf"(.+?)(?:\n|$)",
            re.IGNORECASE | re.UNICODE
        )

    # ──────────────────────────────────────────────────────────────
    # Motor principal de mascaramento
    # ──────────────────────────────────────────────────────────────

    def mask(self, text: str) -> MaskingResult:
        self._reset()
        masked = text
        stats: dict[str, int] = {}

        patterns: list[tuple[re.Pattern, SensitiveCategory, int | None]] = []

        if self._enabled.get(SensitiveCategory.CPF):
            patterns.append((self._cpf_pattern(), SensitiveCategory.CPF, None))
        if self._enabled.get(SensitiveCategory.EMAIL):
            patterns.append((self._email_pattern(), SensitiveCategory.EMAIL, None))
        if self._enabled.get(SensitiveCategory.PIX_KEY):
            patterns.append((self._pix_pattern(), SensitiveCategory.PIX_KEY, 1))
        if self._enabled.get(SensitiveCategory.BANK_ACCOUNT):
            patterns.append((self._bank_account_pattern(), SensitiveCategory.BANK_ACCOUNT, None))
        if self._enabled.get(SensitiveCategory.CEP):
            patterns.append((self._cep_pattern(), SensitiveCategory.CEP, None))
        if self._enabled.get(SensitiveCategory.CNH):
            patterns.append((self._cnh_pattern(), SensitiveCategory.CNH, 1))
        if self._enabled.get(SensitiveCategory.CPF):
            patterns.append((self._cpf_contextual_pattern(), SensitiveCategory.CPF, 1))
        if self._enabled.get(SensitiveCategory.PHONE):
            patterns.append((self._phone_pattern(), SensitiveCategory.PHONE, None))
        if self._enabled.get(SensitiveCategory.RG):
            patterns.append((self._rg_pattern(), SensitiveCategory.RG, None))
        if self._enabled.get(SensitiveCategory.DATE):
            patterns.append((self._date_pattern(), SensitiveCategory.DATE, None))
        if self._enabled.get(SensitiveCategory.MONEY):
            patterns.append((self._money_pattern(), SensitiveCategory.MONEY, None))
        if self._enabled.get(SensitiveCategory.NAME):
            patterns.append((self._name_pattern(), SensitiveCategory.NAME, 1))
        if self._enabled.get(SensitiveCategory.ADDRESS):
            patterns.append((self._address_pattern(), SensitiveCategory.ADDRESS, 1))

        for pattern_str, category in self._custom_patterns:
            patterns.append((re.compile(pattern_str), category, None))

        for pattern, category, group_idx in patterns:
            masked, count = self._apply_pattern(masked, pattern, category, group_idx)
            if count > 0:
                stats[category.value] = stats.get(category.value, 0) + count

        return MaskingResult(
            masked_text=masked,
            tokens=list(self._all_tokens),
            stats=stats,
        )

    def _apply_pattern(
        self,
        text: str,
        pattern: re.Pattern,
        category: SensitiveCategory,
        group_idx: int | None = None,
    ) -> tuple[str, int]:
        count = 0
        matches = list(pattern.finditer(text))

        for match in reversed(matches):
            if group_idx is not None:
                try:
                    original = match.group(group_idx)
                    if original is None:
                        continue
                    start = match.start(group_idx)
                    end = match.end(group_idx)
                except IndexError:
                    continue
            else:
                original = match.group(0)
                start = match.start()
                end = match.end()

            original = original.strip()
            if not original or len(original) < 2:
                continue

            # Evita mascarar tokens já gerados
            if re.search(r"\[[A-Z_]+_\d{3}\]|\[REMOVIDO_LGPD\]", original):
                continue

            # LÓGICA LGPD: SCRUB vs MASK
            if category in SCRUB_CATEGORIES:
                # SCRUB: Apaga irreversivelmente
                token = SCRUB_TOKEN
                # NÃO armazenamos o valor em self._all_tokens
            else:
                # MASK: Tokeniza de forma reversível
                token = self._next_token(category)
                self._all_tokens.append(MaskedToken(
                    token=token,
                    category=category,
                    original_value=original,
                    start_pos=start,
                    end_pos=end,
                ))

            text = text[:start] + token + text[end:]
            count += 1

        return text, count

    # ──────────────────────────────────────────────────────────────
    # Desmascaramento (restauração dos dados originais)
    # ──────────────────────────────────────────────────────────────

    def demask(self, text: str, token_map: dict[str, str]) -> str:
        result = text
        for token in sorted(token_map.keys(), key=len, reverse=True):
            result = result.replace(token, token_map[token])
        return result

    def demask_dict(self, data: dict[str, Any], token_map: dict[str, str]) -> dict[str, Any]:
        result = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = self.demask(value, token_map)
            elif isinstance(value, dict):
                result[key] = self.demask_dict(value, token_map)
            elif isinstance(value, list):
                result[key] = self._demask_list(value, token_map)
            else:
                result[key] = value
        return result

    def _demask_list(self, items: list, token_map: dict[str, str]) -> list:
        result = []
        for item in items:
            if isinstance(item, str):
                result.append(self.demask(item, token_map))
            elif isinstance(item, dict):
                result.append(self.demask_dict(item, token_map))
            elif isinstance(item, list):
                result.append(self._demask_list(item, token_map))
            else:
                result.append(item)
        return result

    # ──────────────────────────────────────────────────────────────
    # Relatório de auditoria
    # ──────────────────────────────────────────────────────────────

    def generate_audit_report(self, result: MaskingResult) -> str:
        lines = [
            "=" * 60,
            "  RELATÓRIO DE MASCARAMENTO / SCRUB (LGPD) — DocFiller",
            "=" * 60,
            f"  Total de intervenções: {sum(result.stats.values())}",
            "",
        ]

        if result.stats:
            lines.append("  Dados por categoria:")
            for category, count in sorted(result.stats.items()):
                # Identifica se a categoria sofreu SCRUB ou MASK
                try:
                    cat_enum = SensitiveCategory(category)
                    is_scrub = cat_enum in SCRUB_CATEGORIES
                    action = "APAGADO (SCRUB)" if is_scrub else "TOKENIZADO (MASK)"
                except ValueError:
                    action = "TOKENIZADO"
                lines.append(f"    • {category}: {count} ocorrência(s) -> {action}")
            lines.append("")

        if result.tokens:
            lines.append("  Tokens gerados (Modo MASK):")
            for token in result.tokens:
                val = token.original_value
                if len(val) > 8:
                    preview = f"***{val[-2:]}" if len(val) > 3 else "***"
                else:
                    preview = "***"
                lines.append(f"    {token.token} <- {token.category.value} ({preview})")

        lines.extend(["", "=" * 60])
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────
# Exemplo de uso / teste rápido
# ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    sample_text = (
        "CARTEIRA NACIONAL DE HABILITACAO\n"
        "\n"
        "Nome: Maria Fernanda dos Santos Silva\n"
        "CPF: 123.456.789-09\n"
        "RG: 12.345.678-9\n"
        "Data de Nascimento: 15/03/1985\n"
        "CNH: 04567890123\n"
        "\n"
        "Endereco: Rua das Palmeiras, 456, Apt 12 - Jardim America\n"
        "CEP: 01234-567\n"
        "Telefone: (11) 98765-4321\n"
        "Email: maria.santos@email.com.br\n"
        "\n"
        "Valor do servico: R$ 1.250,00\n"
        "\n"
        "Proprietario: Joao Carlos Mendes\n"
        "Comprador: Ana Paula Ferreira Lima\n"
    )

    masker = DataMasker()
    result = masker.mask(sample_text)

    print("TEXTO PROCESSADO (O QUE VAI PARA O GEMINI API):")
    print("-" * 60)
    print(result.masked_text)
    print()
    print(masker.generate_audit_report(result))
    print()
    
    print("TEXTO RESTAURADO LOCALMENTE (POST-API):")
    print("-" * 60)
    restored = masker.demask(result.masked_text, result.token_map)
    print(restored)
    print()

    # Como usamos o SCRUB, o texto restaurado deve ser diferente do original
    # na parte dos dados apagados
    if restored.strip() != sample_text.strip() and "[REMOVIDO_LGPD]" in restored:
        print("[OK] Dados sensíveis LGPD foram apagados irreversivelmente!")
    else:
        print("[ERRO] SCRUB falhou ou texto está idêntico.")
