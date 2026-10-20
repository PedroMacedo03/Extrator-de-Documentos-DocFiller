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
    # [Opus - Security Audit (Item 1)]: Novas categorias para cobrir os 20 tipos de documentos e MRZ
    MRZ = "MRZ"
    PASSPORT = "PASSAPORTE"
    CNS = "CNS"
    TITULO_ELEITOR = "TITULO"
    RA_MILITAR = "RA"
    MATRICULA_CERTIDAO = "MATRICULA"
    REGISTRO_PROFISSIONAL = "REGISTRO"

# Categorias que devem ser apagadas definitivamente (LGPD)
SCRUB_CATEGORIES = {
    SensitiveCategory.PHONE,
    SensitiveCategory.EMAIL,
    SensitiveCategory.MONEY,
    SensitiveCategory.BANK_ACCOUNT,
    SensitiveCategory.PIX_KEY,
}

# [Opus - Security Audit (Item 4)]: Categorias cuja chave de deduplicação ignora pontuação/espaços
NUMERIC_CATEGORIES = {
    SensitiveCategory.CPF,
    SensitiveCategory.RG,
    SensitiveCategory.CNH,
    SensitiveCategory.CEP,
    SensitiveCategory.CNS,
    SensitiveCategory.TITULO_ELEITOR,
    SensitiveCategory.RA_MILITAR,
    SensitiveCategory.MATRICULA_CERTIDAO,
}

SCRUB_TOKEN = "[REMOVIDO_LGPD]"

# [Opus - Security Audit (Item 2)]: Palavras de cabeçalhos oficiais que NUNCA devem ser mascaradas como nome de pessoa
_HEADER_STOPWORDS = {
    "REPUBLICA FEDERATIVA", "REPÚBLICA FEDERATIVA", "CARTEIRA NACIONAL",
    "CARTEIRA DE IDENTIDADE", "SECRETARIA DE", "MINISTERIO DA", "MINISTÉRIO DA",
    "REGISTRO GERAL", "REGISTRO CIVIL", "VALIDO EM TODO", "VÁLIDO EM TODO",
    "TERRITORIO NACIONAL", "TERRITÓRIO NACIONAL", "DEPARTAMENTO ESTADUAL",
    "DEPARTAMENTO NACIONAL", "POLICIA CIVIL", "POLÍCIA CIVIL", "POLICIA FEDERAL",
    "POLÍCIA FEDERAL", "INSTITUTO DE", "DIRETORIA DE", "SERVICO PUBLICO",
    "SERVIÇO PÚBLICO", "JUSTICA ELEITORAL", "JUSTIÇA ELEITORAL", "TRIBUNAL REGIONAL",
    "TRIBUNAL SUPERIOR", "CERTIDAO DE", "CERTIDÃO DE", "DOCUMENTO NACIONAL",
    "CONSELHO REGIONAL", "ORDEM DOS ADVOGADOS", "EXERCITO BRASILEIRO",
    "EXÉRCITO BRASILEIRO", "MARINHA DO BRASIL", "FORCA AEREA", "FORÇA AÉREA",
    "ENSINO MEDIO", "ENSINO MÉDIO", "ENSINO SUPERIOR", "EDUCACAO BASICA",
    "EDUCAÇÃO BÁSICA", "NAO INFORMADO", "NÃO INFORMADO", "NADA CONSTA",
    "SEGMENTACAO EM BLOCO", "SEGMENTAÇÃO EM BLOCO", "DATA DE NASCIMENTO",
    "DATA DE EMISSAO", "DATA DE EMISSÃO", "DATA DE EXPEDICAO", "DATA DE EXPEDIÇÃO",
    "LOCAL DE NASCIMENTO", "NATURALIDADE", "NACIONALIDADE", "ASSINATURA DO TITULAR",
    "ASSINATURA DO PORTADOR", "PERMISSAO", "PERMISSÃO", "OBSERVACOES", "OBSERVAÇÕES",
}


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
        # [Opus - Security Audit (Item 4)]: Deduplicação para que o mesmo dado receba sempre o mesmo token
        self._value_to_token: dict[tuple[str, str], str] = {}

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
            # [Opus - Security Audit (Item 1)]: Habilita proteção para os novos documentos e MRZ
            SensitiveCategory.MRZ: True,
            SensitiveCategory.PASSPORT: True,
            SensitiveCategory.CNS: True,
            SensitiveCategory.TITULO_ELEITOR: True,
            SensitiveCategory.RA_MILITAR: True,
            SensitiveCategory.MATRICULA_CERTIDAO: True,
            SensitiveCategory.REGISTRO_PROFISSIONAL: True,
        }

        # Labels para detecção contextual de nomes
        # [LEGACY]: Lista restrita que não contemplava termos específicos de certidões civis
        # [GEMINI - CORREÇÃO C3]: Rótulos expandidos para certidões de nascimento, casamento, óbito e escrituras
        # [Opus - Security Audit (Item 2)]: Removidos substantivos ambíguos ('pais', 'posto', 'graduação',
        # 'matrícula', 'funcional', 'sus', 'cns', 'passaporte', 'dne') que causavam over-masking em frases comuns.
        self._name_labels = name_labels or [
            "nome completo", "nome social", "nome civil", "nome do titular", "nome do eleitor",
            "nome do aluno", "nome do paciente", "nome", "name", "rm", "nm",
            "proprietário", "proprietario",
            "comprador", "compradores", "vendedor", "vendedores",
            "outorgante", "outorgado", "locador", "locatário", "locatario",
            "beneficiário", "beneficiario", "pagador", "titular", "responsável",
            "responsavel", "cônjuge", "conjuge", "cônjuges", "conjuges",
            "filho de", "filha de", "filiação", "filiacao",
            "sendo pai", "sendo mãe", "sendo mae", "pai", "mãe", "mae",
            "nascido", "nascida", "registrado", "registrada",
            "falecido", "falecida", "de cujus", "declarante",
            "nubente", "nubentes", "contraente", "contraentes",
            "avós paternos", "avos paternos", "avós maternos", "avos maternos",
            "avô", "avó", "avo",
            "representante", "procurador", "testemunha",
            "contratante", "contratado", "requerente", "contribuinte",
            "eleitor", "eleitora", "aluno", "aluna", "estudante",
            "formando", "formanda", "diplomado", "diplomada", "concluinte", "egresso", "egressa",
            "viajante", "paciente", "reservista", "alistado", "conscrito", "profissional",
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

    # [Opus - Security Audit (Item 4 & Item 8)]: Deduplicação de tokens e normalização em MAIÚSCULAS
    def _normalize_key(self, category: SensitiveCategory, value: str) -> str:
        """Gera chave canônica para que o mesmo dado (mesmo com ruído de pontuação) receba o mesmo token."""
        if category in NUMERIC_CATEGORIES:
            return re.sub(r"[^0-9A-Z]", "", value.upper())
        return " ".join(value.upper().split())

    def _get_or_create_token(self, category: SensitiveCategory, original: str, start: int, end: int) -> str:
        """Retorna um token existente se o valor já foi visto no documento, ou cria um novo."""
        upper_val = " ".join(original.upper().split()) if category != SensitiveCategory.MRZ else original.upper().strip()
        # [Opus - RG/CNH Multi-Layout CPF]: Padroniza qualquer CPF de 11 dígitos (mesmo lido com '/', ':' ou sem pontos)
        # para o formato canônico XXX.XXX.XXX-XX ao salvar no token_map.
        if category == SensitiveCategory.CPF:
            cpf_digits = re.sub(r"\D", "", upper_val)
            if len(cpf_digits) == 11:
                upper_val = f"{cpf_digits[:3]}.{cpf_digits[3:6]}.{cpf_digits[6:9]}-{cpf_digits[9:]}"
        norm_key = self._normalize_key(category, upper_val)
        cache_key = (category.value, norm_key)

        if cache_key in self._value_to_token:
            token = self._value_to_token[cache_key]
            # Se a nova ocorrência for mais detalhada (ex: CPF com pontuação vs sem pontuação), atualiza o valor salvo
            for existing in self._all_tokens:
                if existing.token == token and len(upper_val) > len(existing.original_value):
                    existing.original_value = upper_val
            return token

        token = self._next_token(category)
        self._value_to_token[cache_key] = token
        self._all_tokens.append(MaskedToken(
            token=token,
            category=category,
            original_value=upper_val,
            start_pos=start,
            end_pos=end,
        ))
        return token

    def _reset(self) -> None:
        self._counters.clear()
        self._all_tokens.clear()
        self._value_to_token.clear()

    # ──────────────────────────────────────────────────────────────
    # Padrões regex para dados sensíveis brasileiros
    # ──────────────────────────────────────────────────────────────

    # [Opus - Security Audit (Item 1)]: Código MRZ (Passaporte e verso da CIN)
    @staticmethod
    def _mrz_pattern() -> re.Pattern:
        return re.compile(r"(?<![A-Z0-9<])([A-Z0-9<]{5,}<<[A-Z0-9<]{4,})(?![A-Z0-9<])")

    # [Opus - Security Audit (Item 1)]: Matrícula de Certidão Civil (32 dígitos com ou sem hífens/espaços)
    @staticmethod
    def _matricula_certidao_pattern() -> re.Pattern:
        return re.compile(
            r"(?<![\d\-])\b("
            r"\d{6}[\s.\-]\d{2}[\s.\-]\d{2}[\s.\-]\d{4}[\s.\-]\d[\s.\-]\d{5}[\s.\-]\d{3}[\s.\-]\d{7}[\s.\-]\d{2}"
            r"|\d{2}-\d{2}-\d{2}-\d{4}-\d-\d{5}-\d{3}-\d{7}-\d{2}"
            r"|\d{32}"
            r")\b(?![\d\-])"
        )

    # [Opus - Security Audit (Item 1)]: Cartão Nacional de Saúde (CNS / SUS - 15 dígitos)
    @staticmethod
    def _cns_pattern() -> re.Pattern:
        return re.compile(
            r"(?:(?:CNS|SUS|cart[ãa]o\s*nacional\s*de\s*sa[úu]de)\s*[:.\-–—]?\s*(?:\r?\n\s*)?([12789]\d{2}[.\s]?\d{4}[.\s]?\d{4}[.\s]?\d{4})"
            r"|(?<![\d.\-])\b([12789]\d{2}\s\d{4}\s\d{4}\s\d{4})\b(?![\d.\-]))",
            re.IGNORECASE
        )

    # [Opus - Security Audit (Item 1)]: Título de Eleitor (12 dígitos)
    @staticmethod
    def _titulo_eleitor_pattern() -> re.Pattern:
        return re.compile(
            r"(?:inscri[çc][ãa]o(?:\s*eleitoral)?|t[íi]tulo(?:\s*de\s*eleitor)?|n[ºo°]\s*do\s*t[íi]tulo)\s*[:.\-–—]?\s*(?:\r?\n\s*)?(\d{4}[.\s]?\d{4}[.\s]?\d{4})\b",
            re.IGNORECASE
        )

    # [Opus - Security Audit (Item 1)]: Registro de Alistamento Militar / Reservista (12 dígitos)
    @staticmethod
    def _ra_militar_pattern() -> re.Pattern:
        return re.compile(
            r"(?:\bRA\b|registro\s*de\s*alistamento)\s*[:.\-–—]?\s*(?:\r?\n\s*)?(\d{12}|\d{2}[.\s\-]\d{3}[.\s\-]\d{6}[.\s\-]\d)\b",
            re.IGNORECASE
        )

    # [Opus - Security Audit (Item 1)]: Passaporte Brasileiro (2 letras + 6 dígitos)
    @staticmethod
    def _passport_pattern() -> re.Pattern:
        return re.compile(
            r"(?:passaporte|passport(?:\s*no\.?)?|n[ºo°]\s*do\s*passaporte)\s*[:.\-–—/\s]*?(?:\r?\n\s*)?\b([A-Z]{2}\s?\d{6})\b",
            re.IGNORECASE
        )

    # [Opus - Security Audit (Item 1)]: Registro em Ordens e Conselhos Profissionais (OAB, CRM, CREA, etc.)
    @staticmethod
    def _registro_profissional_pattern() -> re.Pattern:
        return re.compile(
            r"\b(?:OAB|CRM|CREA|CRC|CRO|CRP|CAU|COFEN)(?:\s*[-/]\s*[A-Z]{2})?\s*[:.\-–—]?\s*((?:\d{1,3}(?:\.\d{3})+|\d{3,10})(?:-[A-Za-z0-9])?(?:\s*/\s*[A-Z]{2})?)\b",
            re.IGNORECASE
        )

    # [LEGACY]: return re.compile(r"\b(\d{3}\.\d{3}\.\d{3}-\d{2})\b")
    # [Opus - Security Audit (Item 3.2)]: Suporte a espaços de OCR e proteção com lookaround
    # [Opus - RG/CNH Multi-Layout CPF]: Suporte aos formatos históricos de RG dos últimos 20 anos:
    # - Separador '/' antes do dígito verificador (ex: 123.456.789/00, muito comum em RGs estaduais antigos)
    # - Ruído de OCR nos pontos (':' ou ',' no lugar de '.', ex: 123. 456: 789-09)
    # - Formato semi-formatado sem pontos (9 dígitos + '-' ou '/' + 2 dígitos, ex: 123456789-00 ou 123456789/00)
    @staticmethod
    def _cpf_pattern() -> re.Pattern:
        return re.compile(
            r"(?<![\d.\-/])\b("
            r"\d{3}\s*[.,:\s]\s*\d{3}\s*[.,:\s]\s*\d{3}\s*[-./]\s*\d{2}"
            r"|\d{9}\s*[-/]\s*\d{2}"
            r")\b(?![\d.\-/])"
        )

    # [LEGACY]: return re.compile(r"(?:CPF|cpf)\s*[:.]?\s*(\d{11})\b")
    # [Opus - Security Audit (Item 3.2)]: Suporte a quebra de linha entre rótulo CPF e os 11 dígitos (CNH/CIN) e espaços do OCR
    # [Opus - RG/CNH Multi-Layout CPF]: Inclui leituras corrompidas do rótulo 'CPF' pelo Tesseract em caixas pequenas
    # de RG/CNH ('CRE', 'CPR', 'CPE', 'CPP', '4D CPF', 'C.P.F')
    @staticmethod
    def _cpf_contextual_pattern() -> re.Pattern:
        return re.compile(
            r"\b(?:C\.?\s*P\.?\s*F\.?(?:\s*/\s*MF)?|4[dD]\s*CPF|CRE|CPR|CPE|CPP)\s*[:.\-–—|]?\s*(?:\r?\n\s*)?(?<![\d.\-/])("
            r"\d{3}\s*[.,:\s]\s*\d{3}\s*[.,:\s]\s*\d{3}\s*[-./]?\s*\d{2}"
            r"|\d{9}\s*[-/]?\s*\d{2}"
            r"|\d{11}"
            r")\b(?![\d.\-/])",
            re.IGNORECASE
        )

    # [Opus - RG/CNH Multi-Layout CPF]: Captura CPFs de 11 dígitos corridos sem pontuação quando o rótulo 'CPF'
    # está em outra coluna/caixa ou foi destruído pelo fundo do documento. Exige validação matemática Módulo 11.
    @staticmethod
    def _cpf_bare_valid_pattern() -> re.Pattern:
        return re.compile(r"(?<![\d.\-/])\b(\d{11})\b(?![\d.\-/])")

    @staticmethod
    def _is_valid_cpf(val: str) -> bool:
        """
        # [Opus - RG/CNH Multi-Layout CPF]: Valida matematicamente os 2 dígitos verificadores (Módulo 11)
        # do CPF brasileiro, descartando sequências repetidas (ex: 00000000000) ou números de CNH/protocolo.
        """
        digits = re.sub(r"\D", "", val)
        if len(digits) != 11 or len(set(digits)) == 1:
            return False
        for i in range(9, 11):
            total = sum(int(digits[num]) * ((i + 1) - num) for num in range(i))
            digit = ((total * 10) % 11) % 10
            if digit != int(digits[i]):
                return False
        return True

    # [LEGACY]: return re.compile(r"\b(\d{1,2}[.\s]?\d{3}[.\s]?\d{3}[-.\s]?[\dxX])\b")
    # [Opus - Security Audit (Item 3.2)]: Lookarounds impedem que o RG fatie CPFs sem pontuação, CNS ou matrículas longas
    @staticmethod
    def _rg_pattern() -> re.Pattern:
        return re.compile(r"(?<![\d.\-/])\b(\d{1,2}[.\s]?\d{3}[.\s]?\d{3}[-.\s]?[\dxX])\b(?![\d.\-/])")

    @staticmethod
    def _cnh_pattern() -> re.Pattern:
        return re.compile(
            r"(?:CNH|habilitação|habilitacao|registro\s*nacional|n[ºo°]\s*registro)\s*[:.\-–—]?\s*(?:\r?\n\s*)?(?<![\d.\-])(\d{11})\b(?![\d.\-])",
            re.IGNORECASE
        )

    # [LEGACY]: r"(?:\+55\s*)?(?:\(?\d{2}\)?\s*)?(?:9\s*\d{4}[-\s]?\d{4}|\d{4}[-\s]?\d{4})\b"
    # [Opus - Security Audit (Item 3.2)]: Lookarounds impedem que o SCRUB de telefone apague CPFs de 11 dígitos ou CNS
    @staticmethod
    def _phone_pattern() -> re.Pattern:
        return re.compile(
            r"(?<![\d.\-/])(?:\+55\s*)?(?:\(\d{2}\)\s*|\b\d{2}\s+)(?:9\s*\d{4}[-\s]\d{4}|\d{4}[-\s]\d{4})\b(?![\d.\-/])"
            r"|(?<![\d.\-/])\b(?:9\d{4}-\d{4}|\d{4}-\d{4})\b(?![\d.\-/])"
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
        # [Opus - Security Audit (Item 2)]: Suporte a sobrenomes com apóstrofo/hífen (D'AVILA, SANT'ANNA, ESPIRITO-SANTO)
        # e exigência de limite de palavra (\b) no rótulo para evitar casamento parcial.
        labels = "|".join(re.escape(l) for l in sorted(self._name_labels, key=len, reverse=True))
        word_pat = r"[A-Za-z\u00C0-\u00FF]+(?:['’\-][A-Za-z\u00C0-\u00FF]+)*"
        return re.compile(
            rf"(?:^|[|\n\r;])[ \t]*(?:{labels})\b[ \t|]*(?:[:.\-–—][ \t]*\r?\n?[ \t]*|[ \t]+\r?\n[ \t]*|[ \t]+)({word_pat}(?:[ \t]+{word_pat})+)",
            re.IGNORECASE | re.UNICODE
        )

    # [Opus - Security Audit (Item 2)]: Padrão para conectivos no meio da linha em certidões (ex: "... filho de JOAO DA SILVA e de MARIA DA SILVA ...")
    @staticmethod
    def _inline_certidao_name_pattern() -> re.Pattern:
        word_pat = r"[A-Z\u00C0-\u00DD]+(?:['’\-][A-Z\u00C0-\u00DD]+)*"
        connectors = r"(?:filh[oa]\s+de|sendo\s+pai|sendo\s+m[ãa]e|casad[oa]\s+com|nascid[oa]\s+em\s+[^,\n]+,\s*filh[oa]\s+de|e\s+de|neto\s+paterno\s+de|neto\s+materno\s+de|av[óo]s\s+paternos|av[óo]s\s+maternos)"
        return re.compile(
            rf"\b{connectors}\s*[:.\-–—]?\s*({word_pat}(?:[ \t]+(?:de|da|do|dos|das|e|{word_pat}))+)",
            re.IGNORECASE | re.UNICODE
        )

    @staticmethod
    def _is_valid_person_name(candidate: str) -> bool:
        """[Opus - Security Audit (Item 2)]: Filtra cabeçalhos institucionais e frases comuns para evitar over-masking."""
        cleaned = " ".join(candidate.upper().split())
        if len(cleaned) < 5:
            return False
        for stop in _HEADER_STOPWORDS:
            if stop in cleaned:
                return False
        words = [w for w in cleaned.split(" ") if w not in ("DE", "DA", "DO", "DOS", "DAS", "E")]
        if len(words) < 2:
            return False
        if any(len(w) < 2 and w not in ("D'",) for w in words[:2]):
            return False
        return True

    def _apply_multiline_filiacao(self, text: str) -> tuple[str, int]:
        """
        [Opus - Security Audit (Item 2)]: Mascara blocos de FILIAÇÃO onde Pai e Mãe estão em linhas consecutivas
        (padrão de RG, CNH e CIN: 'FILIAÇÃO\\nJOAO DA SILVA\\nMARIA DA SILVA').
        """
        count = 0
        word_pat = r"[A-Za-z\u00C0-\u00FF]+(?:['’\-][A-Za-z\u00C0-\u00FF]+)*"
        line_name_re = re.compile(rf"^[ \t|]*({word_pat}(?:[ \t]+{word_pat})+)[ \t|]*$")
        header_re = re.compile(
            r"(?:^|[\n\r|])[ \t]*(?:FILIA[ÇC][ÃA]O|NOME\s+DOS\s+PAIS|PAIS)[ \t|]*[:.\-–—]?[ \t]*\r?\n",
            re.IGNORECASE
        )

        matches = list(header_re.finditer(text))
        for m in reversed(matches):
            pos = m.end()
            # Inspeciona até 3 linhas subsequentes ao cabeçalho FILIAÇÃO
            remaining = text[pos:]
            lines = remaining.splitlines(keepends=True)
            offset = pos
            replacements: list[tuple[int, int, str]] = []

            for line in lines[:3]:
                stripped = line.strip()
                if not stripped or stripped.upper() in ("E", "E DE", "-"):
                    offset += len(line)
                    continue
                if re.search(r"\[[A-Z_]+_\d{3}\]|\[REMOVIDO_LGPD\]", stripped):
                    offset += len(line)
                    continue
                # Se a linha contém outro rótulo com ':', para de capturar como filiação
                if ":" in stripped:
                    break
                nm = line_name_re.match(line.rstrip("\r\n"))
                if nm:
                    cand = nm.group(1).strip()
                    if self._is_valid_person_name(cand):
                        s_idx = offset + nm.start(1)
                        e_idx = offset + nm.end(1)
                        replacements.append((s_idx, e_idx, cand))
                        offset += len(line)
                        continue
                break

            for s_idx, e_idx, cand in reversed(replacements):
                token = self._get_or_create_token(SensitiveCategory.NAME, cand, s_idx, e_idx)
                text = text[:s_idx] + token + text[e_idx:]
                count += 1

        return text, count

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

        # [Opus - Security Audit (Itens 1 e 3.2)]: Ordem hierárquica do maior/mais específico para o menor,
        # impedindo que telefone/RG corrompam MRZ, matrículas de 32 dígitos, CNS de 15 dígitos ou CPFs de 11 dígitos.
        if self._enabled.get(SensitiveCategory.MRZ):
            patterns.append((self._mrz_pattern(), SensitiveCategory.MRZ, 1))
        if self._enabled.get(SensitiveCategory.MATRICULA_CERTIDAO):
            patterns.append((self._matricula_certidao_pattern(), SensitiveCategory.MATRICULA_CERTIDAO, 1))
        if self._enabled.get(SensitiveCategory.CNS):
            patterns.append((self._cns_pattern(), SensitiveCategory.CNS, None))
        if self._enabled.get(SensitiveCategory.TITULO_ELEITOR):
            patterns.append((self._titulo_eleitor_pattern(), SensitiveCategory.TITULO_ELEITOR, 1))
        if self._enabled.get(SensitiveCategory.RA_MILITAR):
            patterns.append((self._ra_militar_pattern(), SensitiveCategory.RA_MILITAR, 1))
        if self._enabled.get(SensitiveCategory.PASSPORT):
            patterns.append((self._passport_pattern(), SensitiveCategory.PASSPORT, 1))
        if self._enabled.get(SensitiveCategory.REGISTRO_PROFISSIONAL):
            patterns.append((self._registro_profissional_pattern(), SensitiveCategory.REGISTRO_PROFISSIONAL, 1))
        if self._enabled.get(SensitiveCategory.CPF):
            patterns.append((self._cpf_pattern(), SensitiveCategory.CPF, 1))
            patterns.append((self._cpf_contextual_pattern(), SensitiveCategory.CPF, 1))
        if self._enabled.get(SensitiveCategory.CNH):
            patterns.append((self._cnh_pattern(), SensitiveCategory.CNH, 1))
        if self._enabled.get(SensitiveCategory.EMAIL):
            patterns.append((self._email_pattern(), SensitiveCategory.EMAIL, None))
        if self._enabled.get(SensitiveCategory.PIX_KEY):
            patterns.append((self._pix_pattern(), SensitiveCategory.PIX_KEY, 1))
        if self._enabled.get(SensitiveCategory.BANK_ACCOUNT):
            patterns.append((self._bank_account_pattern(), SensitiveCategory.BANK_ACCOUNT, None))
        if self._enabled.get(SensitiveCategory.CEP):
            patterns.append((self._cep_pattern(), SensitiveCategory.CEP, 1))
        if self._enabled.get(SensitiveCategory.PHONE):
            patterns.append((self._phone_pattern(), SensitiveCategory.PHONE, None))
        # [Opus - RG/CNH Multi-Layout CPF]: Após CNH e TELEFONE já terem sido extraídos, captura CPFs
        # de 11 dígitos corridos sem rótulo que passem na validação matemática Módulo 11
        if self._enabled.get(SensitiveCategory.CPF):
            patterns.append((self._cpf_bare_valid_pattern(), SensitiveCategory.CPF, 1))
        if self._enabled.get(SensitiveCategory.RG):
            patterns.append((self._rg_pattern(), SensitiveCategory.RG, 1))
        if self._enabled.get(SensitiveCategory.DATE):
            patterns.append((self._date_pattern(), SensitiveCategory.DATE, 1))
        if self._enabled.get(SensitiveCategory.MONEY):
            patterns.append((self._money_pattern(), SensitiveCategory.MONEY, None))

        # [Opus - Security Audit (Item 2)]: Aplica filiação multilinhas antes do padrão geral de nomes
        if self._enabled.get(SensitiveCategory.NAME):
            masked, fil_count = self._apply_multiline_filiacao(masked)
            if fil_count > 0:
                stats[SensitiveCategory.NAME.value] = stats.get(SensitiveCategory.NAME.value, 0) + fil_count
            patterns.append((self._name_pattern(), SensitiveCategory.NAME, 1))
            patterns.append((self._inline_certidao_name_pattern(), SensitiveCategory.NAME, 1))

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
                # Para padrões com grupos alternativos (como CNS), usa o primeiro grupo não-nulo se houver
                if match.lastindex:
                    original = match.group(match.lastindex)
                    start = match.start(match.lastindex)
                    end = match.end(match.lastindex)
                else:
                    original = match.group(0)
                    start = match.start()
                    end = match.end()

            original = original.strip()
            if not original or len(original) < 2:
                continue

            # Evita mascarar tokens já gerados ou marcadores de página
            if re.search(r"\[[A-Z_]+_\d{3}\]|\[REMOVIDO_LGPD\]|<<<PAGINA_\d+>>>", original):
                continue

            # [Opus - Security Audit (Item 2)]: Valida se o candidato a nome não é cabeçalho de órgão/documento
            if category == SensitiveCategory.NAME and not self._is_valid_person_name(original):
                continue

            # [Opus - RG/CNH Multi-Layout CPF]: Para CPFs sem os 2 pontos separadores (11 dígitos corridos ou 9+2)
            # que não vieram precedidos de rótulo explícito, exige validação matemática dos dígitos (Módulo 11)
            # para evitar confundir número de registro CNH ou protocolo com CPF.
            if category == SensitiveCategory.CPF:
                has_full_formatting = bool(re.match(r"^\d{3}\D+\d{3}\D+\d{3}\D+\d{2}$", original))
                has_cpf_label = bool(re.match(r"^(?:C\.?\s*P\.?\s*F|4[dD]|CRE|CPR|CPE|CPP)", match.group(0).strip(), re.IGNORECASE))
                if not has_full_formatting and not has_cpf_label:
                    if not self._is_valid_cpf(original):
                        continue

            # LÓGICA LGPD: SCRUB vs MASK
            if category in SCRUB_CATEGORIES:
                # SCRUB: Apaga irreversivelmente
                token = SCRUB_TOKEN
                # NÃO armazenamos o valor em self._all_tokens
            else:
                # [LEGACY]: token = self._next_token(category) (criava tokens duplicados para o mesmo valor)
                # [Opus - Security Audit (Item 4)]: Reutiliza o mesmo token para valores idênticos
                token = self._get_or_create_token(category, original, start, end)

            text = text[:start] + token + text[end:]
            count += 1

        return text, count

    # ──────────────────────────────────────────────────────────────
    # Desmascaramento (restauração dos dados originais)
    # ──────────────────────────────────────────────────────────────

    # [LEGACY]:
    # def demask(self, text: str, token_map: dict[str, str]) -> str:
    #     result = text
    #     for token in sorted(token_map.keys(), key=len, reverse=True):
    #         result = result.replace(token, token_map[token])
    #     return result
    # [Opus - Security Audit (Item 8)]: Desmascaramento case-insensitive, tolerante a espaços nos colchetes
    # e conversão automática de todo texto extraído/convertido para LETRAS MAIÚSCULAS.
    def demask(self, text: str, token_map: dict[str, str], force_uppercase: bool = True) -> str:
        result = text
        if token_map:
            for token in sorted(token_map.keys(), key=len, reverse=True):
                val = token_map[token]
                inner = token.strip("[]")
                # Casa [NOME_001], [nome_001], [ NOME_001 ]
                flex_pat = re.compile(rf"\[\s*{re.escape(inner)}\s*\]", re.IGNORECASE)
                result = flex_pat.sub(lambda _, v=val: v, result)
        return result.upper() if force_uppercase else result

    def demask_dict(self, data: dict[str, Any], token_map: dict[str, str]) -> dict[str, Any]:
        result = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = self.demask(value, token_map, force_uppercase=True)
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
                result.append(self.demask(item, token_map, force_uppercase=True))
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
