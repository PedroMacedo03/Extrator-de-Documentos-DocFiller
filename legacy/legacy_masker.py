"""
DocFiller — Módulo de Mascaramento Local de Dados Sensíveis
===========================================================

Este módulo garante que NENHUM dado pessoal identificável (PII) seja enviado
para APIs externas (Gemini, etc.) em texto claro.

Fluxo de Segurança:
    1. OCR local (Tesseract) extrai texto bruto da imagem/PDF
    2. DataMasker.mask() substitui dados sensíveis por tokens ([CPF_001], [NOME_001], etc.)
    3. Apenas o texto mascarado é enviado para a API Gemini para interpretação
    4. DataMasker.demask() restaura os valores originais na resposta estruturada

O mapeamento token → valor original NUNCA sai da máquina local.
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
    PHONE = "TELEFONE"
    EMAIL = "EMAIL"
    DATE = "DATA"
    MONEY = "VALOR"
    NAME = "NOME"
    ADDRESS = "ENDERECO"
    BANK_ACCOUNT = "CONTA_BANCARIA"
    PIX_KEY = "CHAVE_PIX"
    CEP = "CEP"


@dataclass
class MaskedToken:
    """Representa um dado mascarado com seu valor original."""
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
        return len(self.tokens) > 0


class DataMasker:
    """
    Motor de mascaramento local de dados sensíveis brasileiros.

    Detecta e substitui dados pessoais por tokens reversíveis,
    mantendo o mapeamento original exclusivamente em memória local.

    Uso:
        masker = DataMasker()
        result = masker.mask("CPF: 123.456.789-00, Nome: João da Silva")
        # result.masked_text => "CPF: [CPF_001], Nome: [NOME_001]"
        # result.token_map   => {"[CPF_001]": "123.456.789-00", "[NOME_001]": "João da Silva"}

        # Depois de receber resposta da API com tokens:
        restored = masker.demask(api_response_text, result.token_map)
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
        """
        Inicializa o masker com categorias configuráveis.

        Args:
            mask_*: Habilita/desabilita mascaramento por categoria.
            custom_patterns: Padrões regex adicionais [(regex_str, categoria), ...].
            name_labels: Labels que precedem nomes nos documentos.
                         Default: ["nome", "name", "proprietário", "comprador", etc.]
            address_labels: Labels que precedem endereços.
                           Default: ["endereço", "address", "logradouro", etc.]
        """
        self._counters: dict[str, int] = {}
        self._all_tokens: list[MaskedToken] = []

        # Configuração de quais categorias mascarar
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
        self._name_labels = name_labels or [
            "nome", "name", "proprietário", "proprietario",
            "comprador", "vendedor", "outorgante", "outorgado",
            "locador", "locatário", "locatario", "beneficiário",
            "beneficiario", "pagador", "titular", "responsável",
            "responsavel", "cônjuge", "conjuge", "filho", "filha",
            "pai", "mãe", "mae", "filiação", "filiacao",
            "representante", "procurador", "testemunha",
            "contratante", "contratado", "requerente",
        ]

        # Labels para detecção contextual de endereços
        self._address_labels = address_labels or [
            "endereço", "endereco", "address", "logradouro",
            "rua", "avenida", "av", "travessa", "alameda",
            "praça", "praca", "rodovia", "estrada",
            "residência", "residencia", "domicílio", "domicilio",
            "localizado", "situado", "sito",
        ]

        # Padrões customizados adicionais
        self._custom_patterns = custom_patterns or []

    def _next_token(self, category: SensitiveCategory) -> str:
        """Gera próximo token sequencial para uma categoria."""
        key = category.value
        self._counters[key] = self._counters.get(key, 0) + 1
        return f"[{key}_{self._counters[key]:03d}]"

    def _reset(self) -> None:
        """Reseta contadores para nova operação de mascaramento."""
        self._counters.clear()
        self._all_tokens.clear()

    # ──────────────────────────────────────────────────────────────
    # Padrões regex para dados sensíveis brasileiros
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _cpf_pattern() -> re.Pattern:
        """CPF: 000.000.000-00 (somente formatado, para evitar colisão com CNH/outros de 11 dígitos)"""
        return re.compile(
            r"\b(\d{3}\.\d{3}\.\d{3}-\d{2})\b"
        )

    @staticmethod
    def _cpf_contextual_pattern() -> re.Pattern:
        """CPF sem formatação: 11 dígitos precedidos de label 'CPF'"""
        return re.compile(
            r"(?:CPF|cpf)\s*[:.]?\s*(\d{11})\b"
        )

    @staticmethod
    def _rg_pattern() -> re.Pattern:
        """RG: formatos variados (XX.XXX.XXX-X, XX XXX XXX X, etc.)"""
        return re.compile(
            r"\b(\d{1,2}[.\s]?\d{3}[.\s]?\d{3}[-.\s]?[\dxX])\b"
        )

    @staticmethod
    def _cnh_pattern() -> re.Pattern:
        """CNH: 11 dígitos"""
        return re.compile(
            r"(?:CNH|habilitação|habilitacao|registro\s*nacional)\s*[:.]?\s*(\d{11})",
            re.IGNORECASE
        )

    @staticmethod
    def _phone_pattern() -> re.Pattern:
        """Telefone BR: (XX) XXXXX-XXXX, (XX) XXXX-XXXX, +55..., etc."""
        return re.compile(
            r"(?:\+55\s?)?"              # Código país opcional
            r"\(?\d{2}\)?\s?"            # DDD
            r"(?:9\s?)?"                 # Nono dígito
            r"\d{4}[-.\s]?\d{4}\b"       # Número
        )

    @staticmethod
    def _email_pattern() -> re.Pattern:
        """Email padrão."""
        return re.compile(
            r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"
        )

    @staticmethod
    def _date_pattern() -> re.Pattern:
        """Datas: DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY, YYYY-MM-DD"""
        return re.compile(
            r"\b(\d{2}[/.-]\d{2}[/.-]\d{4}|\d{4}[/.-]\d{2}[/.-]\d{2})\b"
        )

    @staticmethod
    def _money_pattern() -> re.Pattern:
        """Valores monetários: R$ 1.234,56 / R$1234.56 / etc."""
        return re.compile(
            r"R\$\s*\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})?"  # R$ 1.234,56
            r"|\b\d{1,3}(?:\.\d{3})*,\d{2}\b"            # 1.234,56 (sem R$)
        )

    @staticmethod
    def _cep_pattern() -> re.Pattern:
        """CEP: XXXXX-XXX ou XXXXXXXX"""
        return re.compile(
            r"\b(\d{5}-?\d{3})\b"
        )

    @staticmethod
    def _bank_account_pattern() -> re.Pattern:
        """Conta bancária: agência XXXX-X conta XXXXX-X, etc."""
        return re.compile(
            r"(?:ag(?:ência|encia)?|agência)\s*[:.]?\s*(\d{4}[-.]?\d?)"
            r"|(?:conta|c/?c)\s*[:.]?\s*(\d{5,12}[-.]?\d?)",
            re.IGNORECASE
        )

    @staticmethod
    def _pix_pattern() -> re.Pattern:
        """Chaves PIX: CPF, email, telefone, ou UUID."""
        return re.compile(
            r"(?:pix|chave)\s*[:.]?\s*("
            r"[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}"  # UUID
            r"|[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"  # Email
            r"|\+?\d{10,13}"  # Telefone
            r"|\d{11}"  # CPF
            r")",
            re.IGNORECASE
        )

    def _name_pattern(self) -> re.Pattern:
        """
        Detecta nomes apos labels contextuais.
        Ex: "Nome: Maria Fernanda dos Santos Silva" -> captura nome completo
        Importante: usa [ \\t] ao inves de \\s para nao cruzar linhas.
        """
        labels = "|".join(re.escape(l) for l in self._name_labels)
        return re.compile(
            rf"(?:{labels})[ \t]*[:\.\-]+[ \t]*"
            rf"([A-Z\u00C0-\u00FF][a-z\u00E0-\u00FF]+"
            rf"(?:[ \t]+(?:de|da|do|dos|das|e|Di|Del|Van|Von|La|Le))*"
            rf"(?:[ \t]+[A-Z\u00C0-\u00FF][a-z\u00E0-\u00FF]+)+)",
            re.IGNORECASE | re.UNICODE
        )

    def _standalone_name_pattern(self) -> re.Pattern:
        """
        Detecta nomes próprios completos (2+ palavras capitalizadas).
        Mais agressivo — usar apenas se mask_name=True.
        Exclui palavras comuns em documentos brasileiros.
        """
        return re.compile(
            r"\b([A-ZÀ-ÿ][a-zà-ÿ]+"
            r"(?:\s+(?:de|da|do|dos|das|e))?"
            r"(?:\s+[A-ZÀ-ÿ][a-zà-ÿ]+){1,6})\b",
            re.UNICODE
        )

    def _address_pattern(self) -> re.Pattern:
        """
        Detecta endereços após labels contextuais.
        Ex: "Endereço: Rua das Flores, 123, Apt 45 - Centro"
        """
        labels = "|".join(re.escape(l) for l in self._address_labels)
        return re.compile(
            rf"(?:{labels})\s*[:.\-–—]\s*"
            rf"(.+?)(?:\n|$)",  # Captura até fim da linha
            re.IGNORECASE | re.UNICODE
        )

    # ──────────────────────────────────────────────────────────────
    # Motor principal de mascaramento
    # ──────────────────────────────────────────────────────────────

    def mask(self, text: str) -> MaskingResult:
        """
        Mascara todos os dados sensíveis detectados no texto.

        Ordem de processamento (do mais específico ao mais genérico):
        1. CPF (11 dígitos formatados)
        2. Email
        3. Chave PIX
        4. Conta bancária
        5. CEP
        6. CNH
        7. Telefone
        8. RG
        9. Datas
        10. Valores monetários
        11. Nomes (contextual — após labels)
        12. Endereços (contextual — após labels)
        13. Padrões customizados

        Args:
            text: Texto bruto extraído por OCR local.

        Returns:
            MaskingResult com texto mascarado, tokens e estatísticas.
        """
        self._reset()
        masked = text
        stats: dict[str, int] = {}

        # Lista de (pattern, category, group_index) na ordem de processamento
        patterns: list[tuple[re.Pattern, SensitiveCategory, int | None]] = []

        # 1. CPF formatado (XXX.XXX.XXX-XX) — inequívoco
        if self._enabled.get(SensitiveCategory.CPF):
            patterns.append((self._cpf_pattern(), SensitiveCategory.CPF, None))
        # 2. Email
        if self._enabled.get(SensitiveCategory.EMAIL):
            patterns.append((self._email_pattern(), SensitiveCategory.EMAIL, None))
        # 3. PIX
        if self._enabled.get(SensitiveCategory.PIX_KEY):
            patterns.append((self._pix_pattern(), SensitiveCategory.PIX_KEY, 1))
        # 4. Conta bancária
        if self._enabled.get(SensitiveCategory.BANK_ACCOUNT):
            patterns.append((self._bank_account_pattern(), SensitiveCategory.BANK_ACCOUNT, None))
        # 5. CEP
        if self._enabled.get(SensitiveCategory.CEP):
            patterns.append((self._cep_pattern(), SensitiveCategory.CEP, None))
        # 6. CNH (contextual, 11 dígitos com label) — ANTES do CPF contextual
        if self._enabled.get(SensitiveCategory.CNH):
            patterns.append((self._cnh_pattern(), SensitiveCategory.CNH, 1))
        # 7. CPF contextual (11 dígitos com label "CPF") — DEPOIS da CNH
        if self._enabled.get(SensitiveCategory.CPF):
            patterns.append((self._cpf_contextual_pattern(), SensitiveCategory.CPF, 1))
        # 8. Telefone
        if self._enabled.get(SensitiveCategory.PHONE):
            patterns.append((self._phone_pattern(), SensitiveCategory.PHONE, None))
        # 9. RG
        if self._enabled.get(SensitiveCategory.RG):
            patterns.append((self._rg_pattern(), SensitiveCategory.RG, None))
        # 10. Datas
        if self._enabled.get(SensitiveCategory.DATE):
            patterns.append((self._date_pattern(), SensitiveCategory.DATE, None))
        # 11. Valores monetários
        if self._enabled.get(SensitiveCategory.MONEY):
            patterns.append((self._money_pattern(), SensitiveCategory.MONEY, None))
        # 12. Nomes (contextual)
        if self._enabled.get(SensitiveCategory.NAME):
            patterns.append((self._name_pattern(), SensitiveCategory.NAME, 1))
        # 13. Endereços (contextual)
        if self._enabled.get(SensitiveCategory.ADDRESS):
            patterns.append((self._address_pattern(), SensitiveCategory.ADDRESS, 1))

        # Padrões customizados
        for pattern_str, category in self._custom_patterns:
            patterns.append((re.compile(pattern_str), category, None))

        # Aplicar cada padrão sequencialmente
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
        """Aplica um padrão regex e substitui matches por tokens."""
        count = 0
        # Coletar matches de trás para frente para não invalidar posições
        matches = list(pattern.finditer(text))

        for match in reversed(matches):
            if group_idx is not None:
                # Capturar grupo específico
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

            # Verificar se já não foi mascarado (contém token)
            if re.search(r"\[[A-Z_]+_\d{3}\]", original):
                continue

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
        """
        Restaura dados originais substituindo tokens pelos valores reais.

        Args:
            text: Texto (ou JSON string) contendo tokens mascarados.
            token_map: Mapeamento token → valor original (de MaskingResult.token_map).

        Returns:
            Texto com dados originais restaurados.
        """
        result = text
        # Ordenar por comprimento do token (maior primeiro) para evitar
        # substituições parciais
        for token in sorted(token_map.keys(), key=len, reverse=True):
            result = result.replace(token, token_map[token])
        return result

    def demask_dict(self, data: dict[str, Any], token_map: dict[str, str]) -> dict[str, Any]:
        """
        Restaura dados originais recursivamente em um dicionário.
        Útil para desmascarar structured output JSON da API.

        Args:
            data: Dicionário com valores que podem conter tokens.
            token_map: Mapeamento token → valor original.

        Returns:
            Dicionário com dados originais restaurados.
        """
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
        """Restaura dados originais recursivamente em uma lista."""
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
    # Persistência segura do mapeamento (opcional)
    # ──────────────────────────────────────────────────────────────

    def save_token_map(
        self,
        result: MaskingResult,
        filepath: str | Path,
        *,
        encrypt: bool = False,
    ) -> None:
        """
        Salva mapeamento de tokens em arquivo local (JSON).

        O arquivo é salvo EXCLUSIVAMENTE no disco local,
        NUNCA sendo transmitido para APIs externas.

        Args:
            result: Resultado do mascaramento.
            filepath: Caminho local para salvar o mapeamento.
            encrypt: Se True, aplica ofuscação básica (XOR). Para
                     criptografia real, use bibliotecas como `cryptography`.
        """
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": "1.0",
            "tokens": [
                {
                    "token": t.token,
                    "category": t.category.value,
                    "original_value": t.original_value,
                }
                for t in result.tokens
            ],
            "stats": result.stats,
        }

        content = json.dumps(data, ensure_ascii=False, indent=2)

        if encrypt:
            # Ofuscação simples — NÃO é criptografia real.
            # Para produção, usar `cryptography.fernet`.
            key = hashlib.sha256(b"docfiller_local_key").digest()
            encrypted_bytes = bytes(
                b ^ key[i % len(key)]
                for i, b in enumerate(content.encode("utf-8"))
            )
            filepath.write_bytes(encrypted_bytes)
        else:
            filepath.write_text(content, encoding="utf-8")

    def load_token_map(
        self,
        filepath: str | Path,
        *,
        encrypted: bool = False,
    ) -> dict[str, str]:
        """
        Carrega mapeamento de tokens de arquivo local.

        Returns:
            Dicionário token → valor original.
        """
        filepath = Path(filepath)

        if encrypted:
            key = hashlib.sha256(b"docfiller_local_key").digest()
            encrypted_bytes = filepath.read_bytes()
            decrypted = bytes(
                b ^ key[i % len(key)]
                for i, b in enumerate(encrypted_bytes)
            )
            content = decrypted.decode("utf-8")
        else:
            content = filepath.read_text(encoding="utf-8")

        data = json.loads(content)
        return {
            t["token"]: t["original_value"]
            for t in data["tokens"]
        }

    # ──────────────────────────────────────────────────────────────
    # Relatório de auditoria
    # ──────────────────────────────────────────────────────────────

    def generate_audit_report(self, result: MaskingResult) -> str:
        """
        Gera relatório de auditoria mostrando o que foi mascarado.
        NÃO exibe valores originais — seguro para logs.
        """
        lines = [
            "=" * 60,
            "  RELATÓRIO DE MASCARAMENTO — DocFiller",
            "=" * 60,
            f"  Total de dados mascarados: {len(result.tokens)}",
            "",
        ]

        if result.stats:
            lines.append("  Dados por categoria:")
            for category, count in sorted(result.stats.items()):
                lines.append(f"    • {category}: {count} ocorrência(s)")
            lines.append("")

        lines.append("  Tokens gerados:")
        for token in result.tokens:
            # Mostra apenas os 3 primeiros e 2 últimos caracteres do valor original
            val = token.original_value
            if len(val) > 8:
                preview = f"{val[:3]}***{val[-2:]}"
            else:
                preview = "***"
            lines.append(f"    {token.token} <- {token.category.value} ({preview})")

        lines.extend(["", "=" * 60])
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────
# Validação de CPF (utilidade para distinguir CPFs reais de 11 dígitos aleatórios)
# ──────────────────────────────────────────────────────────────────

def validate_cpf(cpf: str) -> bool:
    """
    Valida um CPF brasileiro usando o algoritmo de dígitos verificadores.

    Args:
        cpf: String do CPF (com ou sem formatação).

    Returns:
        True se o CPF é válido.
    """
    cpf = re.sub(r"[^\d]", "", cpf)

    if len(cpf) != 11:
        return False

    # Rejeitar CPFs com todos os dígitos iguais (ex: 111.111.111-11)
    if len(set(cpf)) == 1:
        return False

    # Cálculo do primeiro dígito verificador
    total = sum(int(cpf[i]) * (10 - i) for i in range(9))
    rest = total % 11
    digit1 = 0 if rest < 2 else 11 - rest

    if int(cpf[9]) != digit1:
        return False

    # Cálculo do segundo dígito verificador
    total = sum(int(cpf[i]) * (11 - i) for i in range(10))
    rest = total % 11
    digit2 = 0 if rest < 2 else 11 - rest

    return int(cpf[10]) == digit2


# ──────────────────────────────────────────────────────────────────
# Exemplo de uso / teste rápido
# ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import io
    # Forcar UTF-8 no console Windows
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    # Texto simulando output de OCR de um documento
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

    print("TEXTO MASCARADO:")
    print("-" * 60)
    print(result.masked_text)
    print()
    print(masker.generate_audit_report(result))
    print()
    print("TEXTO RESTAURADO:")
    print("-" * 60)
    restored = masker.demask(result.masked_text, result.token_map)
    print(restored)
    print()

    # Verificacao de integridade: texto restaurado deve ser igual ao original
    if restored.strip() == sample_text.strip():
        print("[OK] Texto restaurado identico ao original.")
    else:
        print("[AVISO] Texto restaurado difere do original.")
        # Mostrar diferencas
        for i, (a, b) in enumerate(zip(sample_text, restored)):
            if a != b:
                print(f"  Diferenca na posicao {i}: original='{a}' restaurado='{b}'")
