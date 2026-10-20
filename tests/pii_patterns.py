"""Reexporta o detector de PII do produto (`autoseguro.pii`): os testes e o gate de envio usam os MESMOS padroes."""
from autoseguro.pii import EMAIL_OK_DOMAINS, PATTERNS, find_pii  # noqa: F401
