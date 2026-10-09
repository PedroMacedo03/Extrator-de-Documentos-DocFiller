from __future__ import annotations
from typing import List, Optional, Union, Dict, Literal
from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────
# Sub-Modelos Compartilhados
# ─────────────────────────────────────────────────────────

class Person(BaseModel):
    """Representa uma pessoa física e seus dados primários."""
    nome_completo: Optional[str] = Field(None, description="Nome completo da pessoa explicitamente citada")
    nome_pais: Optional[List[str]] = Field(None, description="Nome completo dos pais (se citado)")
    data_nascimento: Optional[str] = Field(None, description="Data de nascimento no formato DD/MM/AAAA")
    cpf: Optional[str] = Field(None, description="Número do CPF com ou sem pontuação")
    rg: Optional[str] = Field(None, description="Número do RG")
    data_obito: Optional[str] = Field(None, description="Data de óbito no formato DD/MM/AAAA, caso haja informação")

class PropertyInfo(BaseModel):
    """Representa dados identificadores de um imóvel."""
    inscricao_municipal: Optional[str] = Field(None, description="Inscrição municipal ou número do cadastro na prefeitura")
    matricula_imovel: Optional[str] = Field(None, description="Número da matrícula do imóvel")
    endereco_completo: Optional[str] = Field(None, description="Endereço completo do imóvel")
    cep: Optional[str] = Field(None, description="CEP do imóvel")

# ─────────────────────────────────────────────────────────
# Modelos Específicos por Documento
# ─────────────────────────────────────────────────────────

class IdentityDocument(BaseModel):
    """1. Documento de Identidade (RG)"""
    tipo: Literal["RG"] = "RG"
    pessoa: Person = Field(..., description="Dados da pessoa do RG")
    orgao_emissor: Optional[str] = Field(None, description="Órgão emissor do RG (ex: SSP, DETRAN)")
    uf_emissor: Optional[str] = Field(None, description="Estado (UF) emissor do RG")
    data_emissao: Optional[str] = Field(None, description="Data de emissão do documento")

class CNHDocument(BaseModel):
    """2. CNH - Carteira Nacional de Habilitação"""
    tipo: Literal["CNH"] = "CNH"
    pessoa: Person = Field(..., description="Dados do motorista (nome e CPF apenas)")

class CTPSDocument(BaseModel):
    """3. CTPS - Carteira de Trabalho"""
    tipo: Literal["CTPS"] = "CTPS"
    pessoa: Person = Field(..., description="Dados do trabalhador (nome, pais, cpf, rg, nascimento)")

class CPFDocument(BaseModel):
    """4. Comprovante de Cadastro de Pessoa Física (CPF)"""
    tipo: Literal["CPF"] = "CPF"
    pessoa: Person = Field(..., description="Dados da pessoa cadastrada")

class MarriageCertificate(BaseModel):
    """5. Certidão de Casamento / União Estável"""
    tipo: Literal["CASAMENTO"] = "CASAMENTO"
    conjuges: List[Person] = Field(..., description="Dados de ambos os cônjuges")
    data_casamento: Optional[str] = Field(None, description="Data da celebração do casamento")
    regime_bens: Optional[str] = Field(None, description="Regime de bens (ex: Comunhão Parcial)")
    cartorio: Optional[str] = Field(None, description="Nome ou identificação do cartório")

class BirthCertificate(BaseModel):
    """6. Certidão de Nascimento"""
    tipo: Literal["NASCIMENTO"] = "NASCIMENTO"
    pessoa: Person = Field(..., description="Dados da criança registrada")
    cartorio: Optional[str] = Field(None, description="Nome ou identificação do cartório / Ofício de Registro Civil")
    matricula: Optional[str] = Field(None, description="Número da matrícula da certidão (formato longo de 32 dígitos se houver)")
    livro: Optional[str] = Field(None, description="Número do livro de registro")
    folha: Optional[str] = Field(None, description="Número da folha")
    termo: Optional[str] = Field(None, description="Número do termo")
    naturalidade: Optional[str] = Field(None, description="Município e UF de nascimento")
    avos_paternos: Optional[List[str]] = Field(None, description="Nomes dos avós paternos")
    avos_maternos: Optional[List[str]] = Field(None, description="Nomes dos avós maternos")

class DeathCertificate(BaseModel):
    """7. Certidão de Óbito"""
    tipo: Literal["OBITO"] = "OBITO"
    pessoa: Person = Field(..., description="Dados do falecido (deve incluir data_obito)")
    matricula_certidao: Optional[str] = Field(None, description="Número da matrícula da certidão")
    cartorio: Optional[str] = Field(None, description="Nome ou identificação do cartório")

class PurchaseDeed(BaseModel):
    """8. Escrituras de Compra e Venda"""
    tipo: Literal["ESCRITURA"] = "ESCRITURA"
    compradores: List[Person] = Field(default_factory=list, description="Partes compradoras")
    vendedores: List[Person] = Field(default_factory=list, description="Partes vendedoras")
    imovel: PropertyInfo = Field(..., description="Dados do imóvel negociado")
    cartorio: Optional[str] = Field(None, description="Cartório onde foi lavrada a escritura")

class IPTUDocument(BaseModel):
    """9. IPTU"""
    tipo: Literal["IPTU"] = "IPTU"
    contribuinte: Person = Field(..., description="Dados do contribuinte (nome, cpf)")
    imovel: PropertyInfo = Field(..., description="Dados do imóvel tarifado")

class PropertyCertificate(BaseModel):
    """10. Certidões de Imóveis (Ônus reais, inteiro teor, etc)"""
    tipo: Literal["CERTIDAO_IMOVEL"] = "CERTIDAO_IMOVEL"
    imovel: PropertyInfo = Field(..., description="Dados do imóvel certificado")
    proprietarios: List[Person] = Field(default_factory=list, description="Proprietários listados na certidão")
    onus_gravacoes: Optional[str] = Field(None, description="Resumo de ônus ou gravações, se houver")

class TituloEleitorDocument(BaseModel):
    """11. Título de Eleitor (Justiça Eleitoral / TSE)"""
    tipo: Literal["TITULO_ELEITOR"] = "TITULO_ELEITOR"
    pessoa: Person = Field(..., description="Dados do eleitor (nome completo, data de nascimento, filiação)")
    numero_titulo: Optional[str] = Field(None, description="Número de inscrição eleitoral (12 dígitos numéricos)")
    zona: Optional[str] = Field(None, description="Número da Zona Eleitoral (ex: 001, 123)")
    secao: Optional[str] = Field(None, description="Número da Seção Eleitoral (ex: 0045, 0123)")
    municipio: Optional[str] = Field(None, description="Município do domicílio eleitoral")
    uf: Optional[str] = Field(None, description="Estado (UF) do domicílio eleitoral")
    data_emissao: Optional[str] = Field(None, description="Data de emissão ou alistamento eleitoral no formato DD/MM/AAAA")

class IdentidadeMilitarFuncionalDocument(BaseModel):
    """12. Identidade Militar, Funcional ou de Conselho de Classe / Órgão Público"""
    tipo: Literal["IDENTIDADE_FUNCIONAL"] = "IDENTIDADE_FUNCIONAL"
    pessoa: Person = Field(..., description="Dados do titular (nome completo, CPF, RG se houver, data de nascimento, filiação)")
    orgao_emissor: str = Field(..., description="Nome do órgão, corporação ou conselho emissor (ex: Exército Brasileiro, Marinha, Aeronáutica, Polícia Militar, Polícia Civil, Polícia Federal, OAB, CRM, CREA, CRO, CRC, Ministério Público, Poder Judiciário)")
    categoria_funcional: Optional[str] = Field(None, description="Categoria: 'MILITAR', 'POLICIAL', 'CONSELHO_PROFISSIONAL', 'ORGAO_PUBLICO' ou 'OUTRO'")
    numero_registro: Optional[str] = Field(None, description="Número de registro funcional, identidade militar, matrícula ou carteira profissional (ex: CRM 12345/SP, OAB 99999/RJ, Matrícula Militar)")
    posto_graduacao_cargo: Optional[str] = Field(None, description="Posto militar, patente, graduação, cargo público ou profissão (ex: Capitão, Tenente, Sargento, Soldado, Delegado, Advogado, Médico, Engenheiro)")
    uf_emissor: Optional[str] = Field(None, description="Estado (UF) expedidor ou do conselho regional")
    data_expedicao: Optional[str] = Field(None, description="Data de expedição no formato DD/MM/AAAA")
    data_validade: Optional[str] = Field(None, description="Data de validade do documento no formato DD/MM/AAAA, se houver")

class CertificadoEscolarDocument(BaseModel):
    """13. Certificado de Conclusão de Curso, Ensino Médio ou Diploma Acadêmico"""
    tipo: Literal["CERTIFICADO_DIPLOMA"] = "CERTIFICADO_DIPLOMA"
    pessoa: Person = Field(..., description="Dados do aluno / concluinte / diplomado (nome completo, CPF, RG, nascimento, filiação)")
    instituicao_ensino: str = Field(..., description="Nome da escola, colégio, faculdade, universidade ou instituição emissora")
    nivel_ensino: Optional[str] = Field(None, description="Nível de ensino: 'ENSINO_MEDIO', 'ENSINO_FUNDAMENTAL', 'TECNICO', 'GRADUACAO', 'POS_GRADUACAO', 'CURSO_LIVRE' ou 'OUTRO'")
    curso: Optional[str] = Field(None, description="Nome do curso ou habilitação (ex: Ensino Médio, Técnico em Edificações, Direito, Administração, Medicina)")
    data_conclusao: Optional[str] = Field(None, description="Data de conclusão do curso no formato DD/MM/AAAA")
    data_emissao: Optional[str] = Field(None, description="Data de expedição / emissão do certificado ou colação de grau no formato DD/MM/AAAA")
    registro_diploma: Optional[str] = Field(None, description="Número de registro do diploma/certificado, livro, folha ou autenticação no MEC/SEEDUC")
    cidade_instituicao: Optional[str] = Field(None, description="Município e UF da instituição de ensino")

class CINDocument(BaseModel):
    """14. Carteira de Identidade Nacional (CIN - Novo Padrão Nacional / Lei 14.534/2023)"""
    tipo: Literal["CIN"] = "CIN"
    pessoa: Person = Field(..., description="Dados do cidadão (CPF é o número de identificação único nacional, nome completo, filiação, nascimento)")
    nome_social: Optional[str] = Field(None, description="Nome social adotado pelo cidadão, se houver")
    sexo: Optional[str] = Field(None, description="Sexo ('M', 'F' ou 'IGNORADO')")
    nacionalidade: Optional[str] = Field(None, description="Nacionalidade (ex: 'Brasileira')")
    naturalidade: Optional[str] = Field(None, description="Município e Estado de nascimento")
    orgao_emissor: Optional[str] = Field(None, description="Órgão emissor (ex: 'Polícia Civil', 'DETRAN', 'Secretaria de Segurança Pública')")
    uf_emissor: Optional[str] = Field(None, description="Estado (UF) emissor da CIN")
    data_emissao: Optional[str] = Field(None, description="Data de emissão no formato DD/MM/AAAA")
    data_validade: Optional[str] = Field(None, description="Data de validade da CIN no formato DD/MM/AAAA ou 'INDETERMINADA'")
    registro_geral_antigo: Optional[str] = Field(None, description="Número de RG antigo estadual, se ainda constar no verso")
    tipo_sanguineo_fator_rh: Optional[str] = Field(None, description="Tipo sanguíneo e fator RH (ex: 'O+', 'A-'), se citado")
    codigo_mrz: Optional[str] = Field(None, description="Linhas de leitura mecânica MRZ da ICAO presentes no verso da CIN")

class PassportDocument(BaseModel):
    """15. Passaporte Brasileiro (Polícia Federal / Padrão ICAO)"""
    tipo: Literal["PASSAPORTE"] = "PASSAPORTE"
    pessoa: Person = Field(..., description="Dados do titular (nome completo, data de nascimento, filiação, CPF, naturalidade)")
    numero_passaporte: str = Field(..., description="Número do passaporte (composto de 2 letras seguidas de 6 dígitos numéricos, ex: 'BR123456', 'FU123456')")
    tipo_passaporte: Optional[str] = Field(None, description="Tipo de passaporte: 'COMUM' (P), 'OFICIAL' (PO), 'DIPLOMATICO' (PD) ou 'EMERGENCIA'")
    pais_emissor: Optional[str] = Field("BRA", description="Código do país emissor (BRA - Brasil)")
    nacionalidade: Optional[str] = Field(None, description="Nacionalidade do titular (ex: 'Brasileira')")
    sexo: Optional[str] = Field(None, description="Sexo ('M' ou 'F')")
    autoridade_emissora: Optional[str] = Field(None, description="Autoridade expedidora (ex: 'DPF', 'Polícia Federal', 'Consulado do Brasil')")
    data_emissao: Optional[str] = Field(None, description="Data de emissão no formato DD/MM/AAAA")
    data_validade: Optional[str] = Field(None, description="Data de expiração/validade no formato DD/MM/AAAA")
    codigo_mrz: Optional[str] = Field(None, description="Código de leitura mecânica MRZ (duas linhas de 44 caracteres)")

class ProfessionalOrderDocument(BaseModel):
    """16. Carteira de Ordem ou Conselho Profissional (OAB, CRM, CREA, CRO, CRC, CRP, CAU, etc.)"""
    tipo: Literal["CARTEIRA_CONSELHO"] = "CARTEIRA_CONSELHO"
    pessoa: Person = Field(..., description="Dados do profissional (nome completo, CPF, RG, filiação, nascimento)")
    orgao_conselho: str = Field(..., description="Sigla do conselho ou ordem (ex: 'OAB', 'CRM', 'CREA', 'CRC', 'CRO', 'CRP', 'CAU', 'COFEN')")
    numero_registro: str = Field(..., description="Número de registro ou inscrição profissional (ex: '123456', '99999/RJ')")
    seccional_uf: Optional[str] = Field(None, description="Seccional regional / Estado (UF) do conselho (ex: 'RJ', 'SP', 'MG')")
    tipo_inscricao: Optional[str] = Field(None, description="Categoria de inscrição: 'ADVOGADO', 'ESTAGIARIO', 'MEDICO', 'ENGENHEIRO', 'DEFINITIVA', 'PROVISORIA', 'SUPLEMENTAR')")
    profissao_cargo: Optional[str] = Field(None, description="Profissão ou título (ex: 'Advogado', 'Médico', 'Engenheiro Agrônomo')")
    data_expedicao: Optional[str] = Field(None, description="Data de emissão/expedição no formato DD/MM/AAAA")
    data_validade: Optional[str] = Field(None, description="Data de validade da carteira no formato DD/MM/AAAA ou 'INDETERMINADA'")

class MilitaryReservistDocument(BaseModel):
    """17. Certificado Militar / Reservista / Alistamento (CAM, CDI, CR - Ministério da Defesa)"""
    tipo: Literal["CERTIFICADO_RESERVISTA"] = "CERTIFICADO_RESERVISTA"
    pessoa: Person = Field(..., description="Dados do cidadão alistado/reservista (nome completo, CPF, RG, data de nascimento, filiação, naturalidade)")
    numero_ra: Optional[str] = Field(None, description="Número do RA (Registro de Alistamento Militar - composto por 12 dígitos)")
    numero_certificado: Optional[str] = Field(None, description="Número de série ou registro do certificado")
    tipo_documento_militar: Optional[str] = Field(None, description="Tipo: 'DISPENSA_INCORPORACAO_CDI', 'RESERVISTA_1_CATEGORIA', 'RESERVISTA_2_CATEGORIA', 'ALISTAMENTO_CAM' ou 'ISENCAO'")
    forca_armada: Optional[str] = Field(None, description="Força Armada ou Órgão: 'EXERCITO', 'MARINHA', 'AERONAUTICA', 'JUNTA_SERVICO_MILITAR'")
    circunscricao_militar: Optional[str] = Field(None, description="CSM (Circunscrição de Serviço Militar) ou JSM (Junta de Serviço Militar) e Município/UF")
    situacao_militar: Optional[str] = Field(None, description="Situação: 'Dispensado de Incorporação', 'Reservista', 'Alistado'")
    data_expedicao: Optional[str] = Field(None, description="Data de emissão/expedição no formato DD/MM/AAAA")

class SUSDocument(BaseModel):
    """18. Cartão Nacional de Saúde (Cartão do SUS - Ministério da Saúde)"""
    tipo: Literal["CARTAO_SUS"] = "CARTAO_SUS"
    pessoa: Person = Field(..., description="Dados do usuário do SUS (nome completo, CPF se constar, data de nascimento)")
    numero_cns: str = Field(..., description="Número do Cartão Nacional de Saúde (CNS - 15 dígitos numéricos)")
    sexo: Optional[str] = Field(None, description="Sexo ('M' ou 'F')")
    municipio_cadastro: Optional[str] = Field(None, description="Município de cadastro do usuário")
    data_cadastro: Optional[str] = Field(None, description="Data de expedição ou cadastro no SUS no formato DD/MM/AAAA")

class StudentCardDocument(BaseModel):
    """19. Documento Nacional do Estudante (DNE / CIE - Carteira de Identificação Estudantil)"""
    tipo: Literal["CARTEIRA_ESTUDANTE_DNE"] = "CARTEIRA_ESTUDANTE_DNE"
    pessoa: Person = Field(..., description="Dados do estudante (nome completo, CPF, RG, data de nascimento)")
    codigo_uso_dne: Optional[str] = Field(None, description="Código de uso do DNE / Certificação digital da carteira")
    instituicao_ensino: str = Field(..., description="Nome da instituição de ensino (Escola, Colégio, Faculdade, Universidade)")
    curso: Optional[str] = Field(None, description="Curso em andamento (ex: 'Ensino Médio', 'Medicina', 'Direito')")
    nivel_escolaridade: Optional[str] = Field(None, description="Grau: 'ENSINO_FUNDAMENTAL', 'ENSINO_MEDIO', 'ENSINO_SUPERIOR', 'POS_GRADUACAO', 'TECNICO')")
    matricula_estudante: Optional[str] = Field(None, description="Número de matrícula na instituição")
    entidade_emissora: Optional[str] = Field(None, description="Entidade emissora oficial (ex: 'UNE', 'UBES', 'ANPG', 'DCE', 'Centro Acadêmico')")
    data_validade: Optional[str] = Field(None, description="Data de validade do documento estudantil (formato DD/MM/AAAA - padrão 31/03 do ano seguinte)")

class ExtraField(BaseModel):
    chave: str
    valor: str

class GenericDocument(BaseModel):
    """Fallback: Formulários variados ou não reconhecidos"""
    # [Opus - v1.0 Multi-Doc]: tipo flexível como str para acomodar rótulos livres e fallback
    tipo: str = "GENERICO"
    titulo: Optional[str] = None
    pessoa: Optional[Person] = None
    pessoas_citadas: List[Person] = Field(default_factory=list, description="Qualquer pessoa detectada")
    imoveis_citados: List[PropertyInfo] = Field(default_factory=list, description="Qualquer imóvel detectado")
    campos_extras: List[ExtraField] = Field(default_factory=list, description="Outros campos chave-valor encontrados")

# ─────────────────────────────────────────────────────────
# Wrapper Final (O que a API vai retornar)
# ─────────────────────────────────────────────────────────

DocumentType = Union[
    IdentityDocument,
    CNHDocument,
    CTPSDocument,
    CPFDocument,
    MarriageCertificate,
    BirthCertificate,
    DeathCertificate,
    PurchaseDeed,
    IPTUDocument,
    PropertyCertificate,
    TituloEleitorDocument,
    IdentidadeMilitarFuncionalDocument,
    CertificadoEscolarDocument,
    CINDocument,
    PassportDocument,
    ProfessionalOrderDocument,
    MilitaryReservistDocument,
    SUSDocument,
    StudentCardDocument,
    GenericDocument
]

class ExtractedDocument(BaseModel):
    """
    Schema root fornecido ao Gemini para forçar a classificação e
    extração estruturada. O Gemini vai escolher o modelo correto
    dentro da união DocumentType.
    """
    # [LEGACY]: discriminator='tipo' gerava 'oneOf' e 'discriminator' no JSON Schema,
    # o que causava ValidationError no validador interno do SDK google-genai (que rejeita discriminator/oneOf).
    # [GEMINI - CORREÇÃO SCHEMA]: Mantido Union sem discriminator para gerar 'anyOf', perfeitamente aceito pelo Gemini.
    documento: DocumentType = Field(
        ..., 
        description="O documento extraído e tipado corretamente"
    )
    confianca: int = Field(
        ..., 
        ge=0, le=100,
        description="Grau de confiança na extração (0-100)"
    )
    observacoes: Optional[str] = Field(
        None, 
        description="Avisos sobre legibilidade, dados faltantes ou rasurados"
    )
