"""Guardrail do `reply` que o LLM redige. Funcao pura: `check_reply(...) -> violacoes`. Reprovou, o orquestrador usa o template do passo.

O que ele GARANTE (mecanicamente): o texto nao carrega dinheiro, prazo, promessa de desconto nem garantia de cobertura; todo numero esta
num fato citado ou foi escrito pelo lead; todo termo de cobertura/plano/carencia pertence a um fato que o LLM declarou usar; nenhuma
cobertura e atribuida ao plano errado; nenhuma negacao recai sobre um desses termos; nenhum plano que nao existe; nenhum link, canal de pagamento nem pedido de dado sensivel;
nenhuma promessa de que um humano vai fazer algo; nenhuma revelacao das instrucoes; nenhuma alegacao de ser uma pessoa.
O que NAO garante: que uma frase montada so com termos autorizados seja verdadeira, nem que uma paráfrase inedita de uma promessa nao escape de uma lista de palavras. Esse residuo
fica com o prompt, com a leitura humana do smoke-llm e com o orquestrador (que so deixa o texto do modelo chegar ao lead enquanto faltam dados, ver `orchestrator._converse`); ver docs/PLAN.md, secao 6.
Na duvida, reprova: o custo de um falso positivo e cair num template.

ENDURECIMENTO DA ETAPA 4 (2026-10-21): um modelo hostil passando por GuardedLLM e orquestrador entregava 50 de 68 frases hostis ao lead (prazo em palavras, "plano Diamante", "metade do preco",
link, PIX, "seu seguro esta aprovado", letras separadas, zero-width, cirilico). As regras abaixo fecham FAMILIAS, nao frases: palavras de dinheiro/preco, numeros por extenso, unidades de tempo,
verbos de promessa de contato, beneficios, aprovacao, canais; e o texto e normalizado antes (NFKC, sem invisiveis, so alfabeto latino, letras separadas e leet colapsados).
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from . import budgets
from .facts import COVERAGE_IDS, FactBase, strip_accents


@dataclass(frozen=True)
class Violation:
    rule: str
    detail: str  # nome do padrao/termo; nunca o trecho do texto


_R1_DINHEIRO = {"simbolo": r"r\$", "reais": r"\breais\b", "us": r"us\$", "mensalidade": r"\bmensalidade", "mensal": r"\bmensa(l|is)\b", "parcela": r"\bparcela",
                "premio": r"\bpremio\b", "valor_decimal": r"[0-9][0-9.]*,[0-9]{2}\b", "por_mes": r"\bpor mes\b", "simbolo_de_moeda": r"[$€£¥]"}
_R3_PRAZO = {"amanha": r"\bamanha\b", "em_breve": r"\bem breve\b", "em_instantes": r"\bem instantes?\b", "daqui_a_pouco": r"\bdaqui a pouco\b",
             "imediato": r"\bimediat", "em_ate": r"\bem ate [0-9]+", "dias_uteis": r"\bdias uteis\b", "horas": r"\bhoras?\b",
             "minutos": r"\bminutos?\b", "contato": r"\bentrar em contato\b", "ligar": r"\bliga(r|mos)\b|\bte ligo\b|\bligo para\b",
             "chamar": r"\bte chamar\b|\bchamo voce\b", "mesmo_chat": r"\bneste mesmo chat\b", "retorno": r"\bretorn",
             "ainda_hoje": r"\bainda hoje\b", "logo_mais": r"\blogo mais\b", "proximas": r"\bnas proximas\b"}
_R4_CONDICAO = {"desconto": r"\bdescont", "promocao": r"\bpromoc", "abatimento": r"\babatimento", "preco_especial": r"preco especial",
                "condicao_especial": r"condicao especial", "melhor_preco": r"melhor preco", "igualamos": r"\bigualamos\b|\bcobrimos\b",
                "cortesia": r"\bcortesia\b", "gratis": r"\bgratis\b|\bgratuit", "sem_custo": r"sem custo", "isencao": r"\bisencao\b|\bisent[oa]\b"}
_R5_GARANTIA = {"cobre_tudo": r"cobre tudo", "sem_carencia": r"\bsem carencia\b", "garantia": r"\bgarant", "cem_por_cento": r"100 ?%",
                "qualquer": r"\bqualquer (dano|situacao|acidente|coisa)\b"}
# Links, canais de pagamento e dado sensivel; instrucoes, "ignore" e "sou uma pessoa": valem para QUALQUER texto, inclusive template.
_R8_CANAL = {"link": r"https?:|www\.|\.(com|br|net|org|app|io)\b|\blink\b|\bsite\b|\burl\b", "arroba": r"@", "pagamento": r"\b(pix|boleto|cartao|debito|credito|transferencia)\b",
             "dado_sensivel": r"\b(cpf|rg|cnh|senha|e-?mail|codigo de seguranca|chave)\b",
             "pedido_de_documento": r"\b(envie|envia|mande|manda|anexe|tire)\b.{0,25}\b(foto|documento|comprovante|selfie|print)\b"}
_R9_VAZAMENTO = {"instrucoes": r"\b(prompt|instruc(ao|oes)|system|regras internas|regras do sistema|diretrizes?|politicas? internas?|fui instruid[oa]|programad[oa] para)\b",
                 "central": r"\bcentral de\b", "ignorar": r"\bignor(ei|o|ar|e|amos)\b",
                 "ser_pessoa": r"\b(sou|somos) (uma |um )?(pessoa|humano|humana)\b|\bpessoa de verdade\b|\bnao sou (um |uma )?(robo|bot|ia|assistente virtual)\b"}

# FAMILIAS (Etapa 4): vocabulario inteiro de uma promessa, para barrar a parafrase e nao so a frase conhecida. Valem para o texto do LLM, que escreve livremente. Os TEMPLATES (revisados
# por gente) podem citar essas palavras de proposito ("o sistema que calcula os valores", "um consultor vai dar continuidade"); o teste de templates fixa quais citam e quais familias.
_F1_DINHEIRO = {"moeda_por_nome": r"\b(dolar(es)?|usd|euros?|pilas?|grana|dinheiro|dinheirinho|centavos?)\b",
                "palavra_de_preco": r"\b(precos?|valor(es)?|tarifas?|taxas?|custa(m|r|ra|ria)?|custos?|cobra(mos|r|do)?|cobro|baratos?|baratas?|pechincha|investimento|orcamento|"
                                    r"paga|pagas|pago|pagar|pagara|pague|pagamentos?|precinh\w*|price[sd]?|costs?|cheap)\b|%",
                "numero_por_extenso": r"\b(dez|vinte|trinta|quarenta|cinquenta|sessenta|setenta|oitenta|noventa|cem|cento|duzent[oa]s|trezent[oa]s|quatrocent[oa]s|quinhent[oa]s|"
                                      r"seiscent[oa]s|setecent[oa]s|oitocent[oa]s|novecent[oa]s|mil|milhao|milhoes|dollars?)\b"}
_F3_PRAZO = {"quantidade_de_tempo": r"\b(um|uma|dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez|onze|doze|quinze|vinte|trinta|meia?)\s+(dias?|semanas?|mes(es)?|horas?|minutos?|segundos?)\b",
             "hoje_mesmo": r"\b(hoje mesmo|ja hoje|desde hoje|a partir de hoje|desde agora|a partir de agora|rapidinho|assim que possivel|o quanto antes|logo logo|mesmo dia)\b",
             "semana": r"\b(proxima semana|semana que vem|(esta|essa|nesta|nessa) semana|fim de semana|dia util)\b",
             "humano": r"\b(consultor(a|es)?|atendentes?|especialistas?|corretor(a|es)?|gerentes?|vendedor(a|es)?|equipe|nosso time|humano|humana)\b",
             "promessa_de_contato": r"\b(entra(r|ra|remos|mos)? em contato|contatar|retornar|retornaremos|responderemos|respondemos|falamos|falaremos|falara|chamaremos|mandaremos|mandamos|"
                                    r"entregamos|entregaremos|enviaremos|enviamos|encaminharemos|encaminhamos|avisaremos|avisamos|procuraremos|escreveremos)\b",
             "te_verbo": r"\bte (respondo|retorno|ligo|chamo|aviso|mando|envio|escrevo|procuro|contato)\b",
             "vou_verbo": r"\b(vou|vamos|iremos|irei|ira|irao|vao)\s+(te\s+)?(enviar|mandar|ligar|chamar|avisar|retornar|responder|procurar|contatar|encaminhar|passar|transferir|"
                          r"falar|entrar|escrever)\b",
             "liga": r"\bliga\b"}
_F4_CONDICAO = {"metade_dobro": r"\b(metade|dobro|triplo)\b", "por_menos": r"\bpor menos\b|\bmais barat[oa]\b|\bem conta\b",
                "brinde_bonus": r"\b(brindes?|cashback|bonus|bonificacao|cupom|cupons|voucher|sorteio|vantagens?|ofertas?|imperdivel|discount|free|coupon|deal)\b",
                "graca": r"\bgraca\b", "negociar": r"\bnegoci\w*", "condicoes": r"\bcondic\w*", "amigo": r"\bde amigo\b",
                "menos": r"\b(paga|pague|pagar|pagara|fica|sai|custa)\s+(bem\s+)?menos\b|\ba menos\b", "codigo_promocional": r"\b(com o|use o|usando o) codigo\b"}
_F5_GARANTIA = {"aprovacao": r"\b(aprovad[oa]s?|aprovacao|proposta|apolice|emitid[oa]s?|contratacao)\b",
                "ja_esta_coberto": r"\b(ja )?est(a|ara|ao) (coberto|coberta|segurado|segurada|protegido|protegida|valendo)\b",
                "tudo_coberto": r"\btudo (coberto|incluso|incluido|garantido)\b", "tranquilidade": r"\b(tranquil[oa]|sem preocupa\w*|pode confiar)\b",
                "carencia_falsa": r"\b(desde o primeiro dia|desde ja|ja val(e|em)|sem espera|sem periodo de espera)\b", "cobertura_imediata": r"\bcobertura (imediata|total)\b", "no_seguro": r"\b(ja )?(esta|fica|ficou|ficara) no seguro\b"}
_NEGACAO = re.compile(r"\b(nao|nunca|jamais|sem|nenhum|nenhuma|nem)\b")
_MARKUP = re.compile(r"[<>{}\[\]`]")
_SENTENCE_SPLIT = re.compile(r"[.!?;\n]+")


def _compile(d: dict[str, str]) -> dict[str, re.Pattern[str]]:
    return {k: re.compile(v) for k, v in d.items()}


_CORE_RULES = (("R1_dinheiro", _compile(_R1_DINHEIRO)), ("R3_prazo_ou_contato", _compile(_R3_PRAZO)), ("R4_desconto_ou_condicao", _compile(_R4_CONDICAO)),
               ("R5_garantia_de_cobertura", _compile(_R5_GARANTIA)), ("R8_link_ou_canal", _compile(_R8_CANAL)), ("R9_vazamento_ou_identidade", _compile(_R9_VAZAMENTO)))
_FAMILY_RULES = (("R1_dinheiro", _compile(_F1_DINHEIRO)), ("R3_prazo_ou_contato", _compile(_F3_PRAZO)), ("R4_desconto_ou_condicao", _compile(_F4_CONDICAO)),
                 ("R5_garantia_de_cobertura", _compile(_F5_GARANTIA)))

_PLAN_WORD = re.compile(r"\b(?:plano|planos|pacote|pacotes|combo|categoria|nivel|nível|linha|seguro)\s+(?:o\s+|a\s+)?([A-ZÀ-Ý][\wÀ-ÿ]+)")
_NAMED_PERSONA = re.compile(r"\b(?:[Ss]ou|[Aa]qui [eé]) (?:o|a) (?!AutoSeguro\b)[A-ZÀ-Ý][a-zà-ÿ]{2,}")
_SPACED_LETTERS = re.compile(r"(?<![a-z0-9])(?:[a-z0-9][ .\-_*·]){3,}[a-z0-9](?![a-z0-9])")
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
_LEET_INSIDE_WORD = re.compile(r"(?<=[a-z])[013457@$](?=[a-z])")
_ORDINAL_SIGNS = {"MASCULINE ORDINAL INDICATOR", "FEMININE ORDINAL INDICATOR"}


def _digit_runs(text: str) -> set[str]:
    """Sequencias de digitos de `text` e as juncoes ("01310-100" -> 01310, 100 e 01310100)."""
    runs = set(re.findall(r"[0-9]+", text))
    for m in re.finditer(r"[0-9][0-9.\-/ ]*[0-9]", text):
        runs.add(re.sub(r"\D", "", m.group()))
    return runs


def _form_violations(reply: str) -> list[Violation]:
    """Forma: o que um texto de WhatsApp em portugues nao tem. Invisiveis e controles (zero-width, NUL, BEL, bidi) e letras de outro alfabeto (cirilico, grego) servem so para
    esconder uma palavra de uma lista; reprova-se o recurso, nao a palavra."""
    out = []
    if any(unicodedata.category(c) in ("Cc", "Cf") and c not in "\n\t" for c in reply):
        out.append(Violation("R6_forma", "caractere_invisivel"))
    if any(c.isalpha() and not unicodedata.name(c, "").startswith("LATIN") and unicodedata.name(c, "") not in _ORDINAL_SIGNS for c in reply):
        out.append(Violation("R6_forma", "alfabeto_nao_latino"))
    return out


def _variants(reply: str) -> list[str]:
    """O texto como as regras o leem: NFKC (largura total vira ASCII), sem invisiveis, sem acentos, minusculo; e as versoes com letras separadas colapsadas ("d e s c o n t o") e com
    leet dentro de palavra ("desc0nto"). Cada regra roda em todas."""
    base = strip_accents(unicodedata.normalize("NFKC", "".join(c for c in reply if unicodedata.category(c) not in ("Cc", "Cf") or c in "\n\t"))).lower()
    collapsed = _SPACED_LETTERS.sub(lambda m: re.sub(r"[ .\-_*·]", "", m.group()), base)
    leet = lambda t: _LEET_INSIDE_WORD.sub(lambda m: m.group().translate(_LEET), t)  # noqa: E731
    return list(dict.fromkeys([base, collapsed, leet(base), leet(collapsed)]))


def _unknown_plans(reply: str, base: FactBase) -> list[Violation]:
    """Plano que nao existe: "plano Diamante", "pacote Gold", "seguro Platinum" e a variante de um plano que existe ("Premium Plus")."""
    text = unicodedata.normalize("NFKC", reply)
    known = {strip_accents(p.pattern.replace("\\b", "")).lower() for p in base.plan_patterns.values()}
    out = [Violation("R7_plano_inexistente", "nome") for m in _PLAN_WORD.finditer(text) if strip_accents(m.group(1)).lower() not in known]
    for pat in base.plan_patterns.values():
        for m in re.finditer(pat.pattern + r"\s+([A-ZÀ-Ý][\wÀ-ÿ]+)", text):
            if strip_accents(m.group(1)).lower() not in known:
                out.append(Violation("R7_plano_inexistente", "variante"))
    return out


def check_reply(reply: str, *, facts_used: Sequence[str], base: FactBase, lead_texts: Sequence[str], author: str = "llm") -> tuple[Violation, ...]:
    """`lead_texts`: o que o LEAD escreveu (mensagem atual e janela de historico). So numeros daqui, ou de fatos citados, podem ecoar.
    `author`: "llm" (o padrao: o texto de um modelo que escreve livremente, com as FAMILIAS de vocabulario) ou "template" (texto do produto: so o nucleo; usado pelos testes de templates)."""
    v: list[Violation] = []
    reply = unicodedata.normalize("NFKC", reply)
    plain = _variants(reply)[0]

    if not reply.strip():
        v.append(Violation("R6_forma", "vazio"))
    if len(reply.split()) > budgets.REPLY_HARD_MAX_WORDS:
        v.append(Violation("R6_forma", "palavras_demais"))
    if _MARKUP.search(reply):
        v.append(Violation("R6_forma", "marcacao"))
    v.extend(_form_violations(reply))

    seen: set[tuple[str, str]] = set()
    for variant in _variants(reply):
        for rule, patterns in _CORE_RULES + (_FAMILY_RULES if author == "llm" else ()):
            for name, rx in patterns.items():
                if rx.search(variant) and (rule, name) not in seen:
                    seen.add((rule, name))
                    v.append(Violation(rule, name))
    v.extend(_unknown_plans(reply, base))
    if _NAMED_PERSONA.search(reply):
        v.append(Violation("R9_vazamento_ou_identidade", "persona_nomeada"))

    unknown = [f for f in facts_used if f not in base.facts]
    v.extend(Violation("R7_fato_inexistente", "id") for _ in unknown)
    cited = [base.facts[f] for f in facts_used if f in base.facts]

    allowed_numbers = set().union(*(f.numbers for f in cited)) if cited else set()
    for t in lead_texts:
        allowed_numbers |= _digit_runs(unicodedata.normalize("NFKC", t))
    v.extend(Violation("R2_numero_nao_permitido", "numero") for n in sorted(set(re.findall(r"[0-9]+", reply)) - allowed_numbers))

    allowed_terms = set().union(*(f.terms for f in cited)) if cited else set()
    v.extend(Violation("R7_termo_sem_fato", term) for term in sorted(base.find_terms(reply) - allowed_terms))

    for sentence in _SENTENCE_SPLIT.split(reply):
        terms = base.find_terms(sentence)
        if terms and _NEGACAO.search(strip_accents(sentence).lower()):
            v.append(Violation("R7_negacao_sobre_fato", "negacao"))
        coverages = terms & COVERAGE_IDS
        for plan in (t for t in terms if t in base.plan_coverages):
            v.extend(Violation("R7_cobertura_no_plano_errado", f"{plan}:{c}") for c in sorted(coverages - base.plan_coverages[plan]))
    return tuple(v)
