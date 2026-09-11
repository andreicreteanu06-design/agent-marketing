"""Instructiuni de regie video (Art Director) injectate in prompt-urile LLM.

Separat de ``engine.py`` (unde traiesc functiile ``build_*_system_prompt``) ca
sa tina intr-un singur loc regulile de regie video ale unui Lead Performance
Creative Director - reutilizabile daca apar prompt-uri noi pentru alte
formate video pe viitor.
"""

from __future__ import annotations

from ppc_agent.creative.video_models import (
    AudioTrack,
    Scene,
    Storyboard,
    TextOverlay,
    VideoCanvas,
)

ART_DIRECTOR_INSTRUCTIONS = """\
INSTRUCTIUNI DE REGIE (Lead Performance Creative Director):
1. Ritmul e semantic: introdu un reset vizual (b-roll sau schimbare de unghi) \
la fiecare 1.5-3.0 secunde, dar prelungeste cadrul daca incarcatura semantica \
e mare (o idee complexa are nevoie de mai mult timp pe ecran).
2. Foloseste A-roll (fata in camera) pentru incredere si emotie. Foloseste \
B-roll pentru a dovedi sau a vizualiza afirmatia.
3. Text critic, CTA-uri si logo-uri NU au voie in zonele de excludere UI \
(Sus 14%, Jos 35%, Laterale 10%). Ancora implicita: 'safe_center'.
4. Contrastul textului e obligatoriu: specifica intotdeauna 'adaptive_backplate' \
pentru fundaluri dinamice.
5. Nu evidentia fiecare cuvant ca la karaoke - evidentiaza doar mecanismul, \
rezultatul sau oferta (``highlight_words``).
6. O scena de tip 'hook' trebuie sa apara intre 0 si 2.5 secunde. O scena de \
tip 'cta' trebuie sa apara la final.\
"""

# Exemplu de FORMAT (nu de continut - "nu copia textul, copiaza structura"),
# construit prin instantierea reala a modelelor Pydantic: daca schema se
# schimba si acest exemplu nu mai e actualizat, constructia de mai jos pica
# la import/testare - nu poate deveni tacit inconsistenta cu Storyboard.
STORYBOARD_FORMAT_EXAMPLE = Storyboard(
    job_id="example",
    duration_seconds=22.0,
    canvas=VideoCanvas(),
    scenes=[
        Scene(
            id="scene_1_hook",
            start_time=0.0,
            end_time=2.5,
            purpose="hook",
            visual_broll_prompt=(
                "Zoom rapid pe produs, camera usor instabila - intrerupere de tipar"
            ),
            text_layers=[
                TextOverlay(
                    type="headline",
                    text="Nu mai face asta",
                    start_time=0.2,
                    duration=2.0,
                    anchor_position="safe_center",
                    highlight_words=["asta"],
                    contrast_mode="adaptive_backplate",
                )
            ],
            audio=[
                AudioTrack(
                    type="voiceover", asset_ref="vo_hook.wav", start_time=0.0, volume=1.0
                )
            ],
        ),
        Scene(
            id="scene_2_proof",
            start_time=2.5,
            end_time=16.0,
            purpose="proof",
            visual_broll_prompt="Split-screen inainte/dupa, prim-plan pe detaliu",
            text_layers=[
                TextOverlay(
                    type="caption",
                    text="Rezultatul se vede din prima zi",
                    start_time=4.0,
                    duration=1.5,
                    anchor_position="bottom_center",
                    highlight_words=["prima zi"],
                    contrast_mode="adaptive_backplate",
                )
            ],
            audio=[
                AudioTrack(
                    type="voiceover", asset_ref="vo_body.wav", start_time=2.5, volume=1.0
                )
            ],
        ),
        Scene(
            id="scene_3_cta",
            start_time=16.0,
            end_time=22.0,
            purpose="cta",
            visual_broll_prompt="Produsul in cadru static, logo vizibil",
            text_layers=[
                TextOverlay(
                    type="cta",
                    text="Comanda din link in bio",
                    start_time=17.0,
                    duration=5.0,
                    anchor_position="safe_center",
                    highlight_words=["Comanda"],
                    contrast_mode="adaptive_backplate",
                )
            ],
            audio=[
                AudioTrack(
                    type="voiceover", asset_ref="vo_cta.wav", start_time=16.0, volume=1.0
                )
            ],
        ),
    ],
)
