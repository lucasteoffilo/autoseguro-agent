"""Perguntas e confirmacoes que sao DO PRODUTO, nao do LLM: texto fixo, montado so de dados que o lead escreveu e de fatos.

Duas razoes. (1) Uma confirmacao e a rede que impede um slot nao ancorado de virar preco; se o LLM a redigisse, ela herdaria os mesmos
erros que ela existe para pegar. (2) O texto do produto decide o que se pergunta: aqui o ano pedido e o ANO DO MODELO (o segundo ano do
documento, 2015/2016 -> 2016), e a confirmacao mostra "modelo 2016", para o lead ver qual dos dois anos esta valendo.

Funcoes puras sobre tipos primitivos (nada de importar o resto do pacote): `anchoring.py` e `templates.py` usam estas.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from .facts import FactBase

_WEEKDAYS = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")


def fmt_cep(digits: str) -> str:
    return f"{digits[:5]}-{digits[5:]}" if len(digits) == 8 else digits


def fmt_date(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.day:02d}/{d.month:02d}/{d.year} ({_WEEKDAYS[d.weekday()]})"


def fmt_value(slot: str, value: str) -> str:
    """Como o dado aparece numa pergunta ao lead. O ano e sempre o do MODELO."""
    return {
        "veiculo_ano": f"modelo {value}", "idade": f"{value} anos", "cep": f"CEP {fmt_cep(value)}", "data_inicio": fmt_date(value),
        "necessidade": value,
    }.get(slot, value)


# A dica dos dois anos so aparece quando o lead MANDOU mais de um ano (confirm, abaixo). Na abertura e nos demais "qual e o ano?" a pergunta e curta: a dica pesava em toda conversa e so serve a quem tem dois anos.
YEAR_HINT = "Se o documento mostra dois anos, como 2015/2016, vale o segundo."


def ask(slot: str, base: FactBase | None = None) -> str:
    """A pergunta do produto para cada dado. A de necessidade sai do fato `necessidades` (as opcoes vem dos planos, nao do codigo)."""
    if slot == "necessidade":
        options = base.facts["necessidades"].text.split(": ", 1)[1].rstrip(".") if base and "necessidades" in base.facts else "só roubo, furto e colisão, ou algo mais completo"
        return f"O que você quer cobrir? {options[0].upper()}{options[1:]}?"
    return {
        "veiculo_ano": "Qual é o ano do modelo do seu carro?",
        "idade": "Qual é a sua idade?",
        "cep": "Qual é o CEP de onde o carro dorme?",
        "data_inicio": "Em que dia você quer que o seguro comece a valer?",
    }[slot]


def _join(items: Sequence[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " e " + items[-1]


def confirm(slot: str, *, proposed: str | None = None, candidates: Sequence[str] = (), derived_from: str | None = None,
            base: FactBase | None = None) -> str:
    """Pergunta de confirmacao, em ordem de especificidade: um valor proposto (sim ou nao), varios candidatos (qual?), um dado derivado
    (pede o valor direto, nunca o calcula) ou nada para mostrar (repete a pergunta do produto)."""
    if proposed is not None:
        if slot == "data_inicio":
            return f"Só pra confirmar: o seguro começa em {fmt_value(slot, proposed)}?"
        return f"Só pra confirmar: {fmt_value(slot, proposed)}?"
    if derived_from is not None:
        return f"Você nasceu em {derived_from}. Quantos anos você tem hoje?"
    if len(candidates) > 1:
        shown = _join([fmt_value(slot, c) for c in candidates])
        return {
            "veiculo_ano": f"Você falou de mais de um ano ({shown}). Qual é o ano do modelo do carro? {YEAR_HINT}",
            "idade": f"Você falou de mais de uma idade ({shown}). Qual é a sua idade hoje?",
            "cep": f"Você falou de mais de um CEP ({shown}). Qual é o CEP de onde o carro dorme?",
            "data_inicio": f"Você falou de mais de uma data ({shown}). Em que dia o seguro deve começar?",
        }.get(slot, ask(slot, base))
    return ask(slot, base)


def echo(new: Mapping[str, str], plano_nome: str | None = None) -> str:
    """O reconhecimento do que o turno VERIFICOU ("Anotado: modelo 2021, 34 anos e CEP 30130-010."), montado so de valores verificados do ledger: nunca o que o modelo escreveu, e nunca preco.
    A necessidade aparece como o plano que ela escolhe ("cobertura do plano Completo"), pelo nome vindo do /planos."""
    parts = []
    for slot in ("veiculo_ano", "idade", "cep", "necessidade", "data_inicio"):
        if slot not in new:
            continue
        if slot == "necessidade":
            if plano_nome:
                parts.append(f"cobertura do plano {plano_nome}")
        else:
            parts.append(("início em " if slot == "data_inicio" else "") + fmt_value(slot, new[slot]))
    return "Anotado: " + _join(parts) + "." if parts else ""


def recap(verified: Mapping[str, str], plano_nome: str | None = None) -> str:
    """Os dados que entram na cotacao, para a mensagem de cotacao mostrar ao lead (rede VISIVEL: se algo estiver errado, ele ve)."""
    order = ("veiculo_ano", "idade", "cep", "data_inicio")
    parts = [("início em " if s == "data_inicio" else "") + fmt_value(s, verified[s]) for s in order if s in verified]
    if plano_nome:
        parts.append(f"plano {plano_nome}")
    return "Dados usados: " + _join(parts) + "." if parts else ""
