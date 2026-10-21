"""As saidas GRAVADAS do modelo real (os dois smokes de 2026-10-20) e o conjunto das que o guardrail aprovava ANTES do endurecimento da Etapa 4.

O conjunto e fixo (nao recalculado com o codigo atual): e o que permite provar que uma regra nova nao barrou uma frase que o modelo real escreveu e que era boa."""
from __future__ import annotations

from pathlib import Path

REPLAY = Path(__file__).parent / "fixtures" / "smoke_replay"

# (arquivo, msg_id, repeticao) aprovados pelo guardrail de 2026-10-21 (commit 7da70d3): 50 das 59 saidas gravadas com reply
APPROVED_BEFORE_HARDENING = [
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm01_saudacao_pergunta_preco', 1),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm02_ano_direto', 1),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm03_idade_direta', 1),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm05_varios_dados_de_uma_vez', 1),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm06_idade_aproximada', 1),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm07_correcao', 1),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm08_ano_versus_modelo', 1),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm09_ano_de_nascimento', 1),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm10_duvida_de_carencia', 1),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm11_objecao_de_preco', 1),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm12_quer_humano', 1),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm13_sinistro', 1),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm14_injecao_de_prompt', 1),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm15_emoji_e_incerteza', 1),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm01_saudacao_pergunta_preco', 2),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm02_ano_direto', 2),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm03_idade_direta', 2),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm04_cep_direto', 2),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm06_idade_aproximada', 2),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm07_correcao', 2),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm08_ano_versus_modelo', 2),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm09_ano_de_nascimento', 2),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm11_objecao_de_preco', 2),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm12_quer_humano', 2),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm13_sinistro', 2),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm14_injecao_de_prompt', 2),
    ('dots-3-note-preview-2026-10-20-rerun.json', 'm15_emoji_e_incerteza', 2),
    ('dots-3-note-preview-2026-10-20.json', 'm01_saudacao_pergunta_preco', 1),
    ('dots-3-note-preview-2026-10-20.json', 'm02_ano_direto', 1),
    ('dots-3-note-preview-2026-10-20.json', 'm03_idade_direta', 1),
    ('dots-3-note-preview-2026-10-20.json', 'm05_varios_dados_de_uma_vez', 1),
    ('dots-3-note-preview-2026-10-20.json', 'm06_idade_aproximada', 1),
    ('dots-3-note-preview-2026-10-20.json', 'm07_correcao', 1),
    ('dots-3-note-preview-2026-10-20.json', 'm08_ano_versus_modelo', 1),
    ('dots-3-note-preview-2026-10-20.json', 'm10_duvida_de_carencia', 1),
    ('dots-3-note-preview-2026-10-20.json', 'm11_objecao_de_preco', 1),
    ('dots-3-note-preview-2026-10-20.json', 'm12_quer_humano', 1),
    ('dots-3-note-preview-2026-10-20.json', 'm13_sinistro', 1),
    ('dots-3-note-preview-2026-10-20.json', 'm14_injecao_de_prompt', 1),
    ('dots-3-note-preview-2026-10-20.json', 'm01_saudacao_pergunta_preco', 2),
    ('dots-3-note-preview-2026-10-20.json', 'm02_ano_direto', 2),
    ('dots-3-note-preview-2026-10-20.json', 'm03_idade_direta', 2),
    ('dots-3-note-preview-2026-10-20.json', 'm06_idade_aproximada', 2),
    ('dots-3-note-preview-2026-10-20.json', 'm07_correcao', 2),
    ('dots-3-note-preview-2026-10-20.json', 'm08_ano_versus_modelo', 2),
    ('dots-3-note-preview-2026-10-20.json', 'm09_ano_de_nascimento', 2),
    ('dots-3-note-preview-2026-10-20.json', 'm10_duvida_de_carencia', 2),
    ('dots-3-note-preview-2026-10-20.json', 'm11_objecao_de_preco', 2),
    ('dots-3-note-preview-2026-10-20.json', 'm12_quer_humano', 2),
    ('dots-3-note-preview-2026-10-20.json', 'm13_sinistro', 2),
]
