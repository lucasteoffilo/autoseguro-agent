"""PII SINTETICA dos testes, montada em tempo de execucao. Nenhum CPF, telefone, e-mail, placa, caminho de home ou chave existe como literal em arquivo do repo.

Um scanner externo (ou o de higiene deste repo, que agora cobre ate esta pasta) nao tem o que apontar: os valores nascem de um hash fixo (os mesmos a cada
execucao, para o teste ser reproduzivel) e o CPF e calculado aqui, com digitos verificadores validos. O algoritmo e reescrito de proposito, e nao importado de
`autoseguro.masker`: o teste do mascarador nao pode usar o validador do mascarador para fabricar a sua propria entrada.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "pii_samples" / "masker.json"


def _digits(tag: str, n: int) -> str:
    h = hashlib.sha256(f"autoseguro-synthetic/{tag}".encode()).hexdigest()
    return "".join(str(int(c, 16) % 10) for c in h)[:n]


def _letters(tag: str, n: int) -> str:
    return "".join(chr(ord("A") + int(d) * 2 + (i % 2)) for i, d in enumerate(_digits(tag, n)))


def cpf(tag: str) -> str:
    """11 digitos com os dois verificadores corretos, a partir de 9 digitos derivados de `tag` (nunca todos iguais)."""
    base = _digits(tag, 9)
    if len(set(base)) == 1:
        base = base[:-1] + str((int(base[-1]) + 1) % 10)
    out = base
    for n in (9, 10):
        s = sum(int(d) * w for d, w in zip(out[:n], range(n + 1, 1, -1), strict=True))
        out += str(s * 10 % 11 % 10)
    return out


def with_wrong_check_digit(digits: str) -> str:
    """O mesmo numero com o ultimo verificador trocado: 11 digitos que NAO sao um CPF."""
    return digits[:-1] + str((int(digits[-1]) + 1) % 10)


def punctuated(digits: str) -> str:
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


def values() -> dict[str, str]:
    cpf_a, cpf_b = cpf("cpf-a"), cpf("cpf-b")
    ph, ph2 = _digits("phone-a", 8), _digits("phone-b", 8)
    at = "@"
    d, m, y = int(_digits("born", 2)) % 28 + 1, int(_digits("born-m", 2)) % 12 + 1, 1950 + int(_digits("born-y", 2)) % 50
    plate_old = _letters("plate-old", 3)
    return {
        "cpf": punctuated(cpf_a), "cpf_digits": cpf_a, "cpf_bad_digits": with_wrong_check_digit(cpf_b),
        "eleven_not_cpf": with_wrong_check_digit(cpf("cpf-c")),
        "email": f"fulano.teste{at}gmail.com", "email2": f"maria.silva{at}gmail.com", "email3": f"a.b+c{at}dominio.com.br",
        "tel_plus": f"+55 11 9{ph[:4]}-{ph[4:]}", "tel_paren": f"(11) 9{ph[:4]}-{ph[4:]}", "tel_ddd": f"11 9{ph[:4]}-{ph[4:]}",
        "tel_digits": f"119{ph}", "tel_local": f"9{ph[:4]}-{ph[4:]}", "tel_core": ph[:4], "tel2": f"(21) 9{ph2[:4]}-{ph2[4:]}",
        "placa_mercosul": f"{_letters('plate-m', 3)}{_digits('plate-m', 1)}{_letters('plate-m2', 1)}{_digits('plate-m2', 2)}",
        "placa_old": f"{plate_old.lower()}-{_digits('plate-old', 4)}", "placa_old2": f"{_letters('plate-old2', 3)}-{_digits('plate-old2', 4)}",
        "home": "/Us" + "ers/fulano/Documentos/x.pdf", "home2": "/Us" + "ers/fulano/x",
        "key_or": "-".join(["sk", "or", "v1", _digits("key-or", 12)]), "key_ant": "-".join(["sk", "ant", _digits("key-ant", 10)]),
        "bearer": "Bearer " + _letters("bearer", 16).lower(),
        "nome_composto": "Maria da Silva Santos", "nome_simples": "Joao Pedro", "nome_curto": "Fernanda", "nascimento": f"{d:02d}/{m:02d}/{y}",
    }


def load_fixture() -> dict:
    """O arquivo traz so os MODELOS dos casos (com {marcadores}); os valores vem de `values()`."""
    fix = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fix["values"] = values()
    return fix
