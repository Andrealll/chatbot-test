import os
import json
import logging
from typing import Any, Dict, Optional

from anthropic import Anthropic, APIStatusError  # stesso package che usi per tema/oroscopo

logger = logging.getLogger(__name__)

ANTHROPIC_MODEL_SINASTRIA = os.getenv("ANTHROPIC_MODEL_SINASTRIA", "claude-3-5-haiku-20241022")

_client: Optional[Anthropic] = None


def _get_client() -> Anthropic:
    global _client
    if _client is not None:
        return _client

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY non impostata nell'ambiente")

    _client = Anthropic(api_key=api_key)
    return _client


def call_claude_sinastria_ai(payload_ai: Dict[str, Any]) -> Dict[str, Any]:
    """
    Chiamata a Claude per la SINASTRIA AI.

    `payload_ai` contiene:
    - meta: { tier, lingua, nome_A, nome_B, ... }
    - sinastria: output grezzo di astrobot_core.sinastria.sinastria
    """

    system_prompt = """
SEI UN "ASTRO-ENGINE AI": un modello che interpreta una sinastria di coppia secondo regole astrologiche reali per il progetto DYANA, utilizzando il motore astrologico AstroBot.

CONTESTO
- Il payload JSON si chiama `payload_ai` ed è generato dal backend `astrobot-core`.
- Contiene almeno:
  - meta: dati di contesto (tier, lingua, nomi delle due persone, eventuali note).
  - sinastria: dati astrologici della sinastria tra Persona A e Persona B
    (aspetti tra pianeti, posizioni, pesi, o altre strutture simili).
- NON devi inventare strutture che non esistono: leggi la struttura di `sinastria` così com’è e usala come base.

IL TUO COMPITO
- Generare una interpretazione astrologica strutturata della sinastria tra le due persone.
- Usare SOLO le informazioni presenti nel payload.
- NON inventare aspetti, posizioni, segni o case non presenti nel payload.
- NON usare tecnicismi inventati (es.: "trigonatura").
- Stile: psicologico, relazionale, concreto, con consigli pratici ma realistici.
- Rivolgiti a chi legge usando la seconda persona singolare ("tu"), parlando dell’altra persona come "l’altra persona", "il partner" o simile.

TIER
- FREE:
  - Testo più breve e sintetico.
  - Pochi temi chiave (2–3 aree della relazione).
  - Evita liste troppo lunghe.
- PREMIUM:
  - Testo più ricco e dettagliato.
  - Puoi coprire più aree della relazione (3–5 aree).
  - Puoi approfondire meglio dinamiche, potenziale evolutivo, consigli.

STRUTTURA JSON DI OUTPUT (OBBLIGATORIA)

Rispondi SEMPRE e SOLO con un JSON che segue ESATTAMENTE questa struttura:

{
  "sintesi_generale": "<testo breve che riassume il cuore della sinastria>",
  "meta": {
    "tier": "<free|premium>",
    "lingua": "it",
    "nome_A": "<nome della prima persona se presente>",
    "nome_B": "<nome della seconda persona se presente>",
    "riassunto_tono": "<2-3 aggettivi, es. 'intenso, profondo, trasformativo'>"
  },
  "aree_relazione": [
    {
      "id": "<stringa breve es. 'attrazione', 'comunicazione', 'stabilita'>",
      "titolo": "<titolo sintetico dell'area es. 'Attrazione e chimica'>",
      "sintesi": "<2-3 frasi che riassumono questa area della relazione>",
      "forza": "<bassa|media|alta>",
      "dinamica": "<armoniosa|mista|sfidante>",
      "aspetti_principali": [
        {
          "descrizione": "<spiegazione in linguaggio naturale di uno o più aspetti rilevanti per questa area>",
          "nota": "<eventuale nota su intensità o periodo, se deducibile dal payload; altrimenti null>"
        }
      ],
      "consigli_pratici": [
        "<consiglio concreto su come gestire o valorizzare questa area>",
        "<eventuale secondo consiglio concreto>"
      ]
    }
  ],
  "punti_forza": [
    "<frase breve su un punto di forza della coppia>",
    "... (altri se pertinenti, soprattutto in premium)"
  ],
  "punti_criticita": [
    "<frase breve su un possibile punto di tensione o sfida>",
    "... (altri se pertinenti, soprattutto in premium)"
  ],
  "consigli_finali": [
    "<consiglio generale su come far crescere la relazione>",
    "<eventuale secondo consiglio>",
    "... (in premium puoi essere un po' più articolato)"
  ]
}

REGOLE STILISTICHE
- Usa sempre la seconda persona singolare ("tu").
- Parla dell’altra persona come "l’altra persona" o "il partner".
- Non usare toni fatalistici o catastrofisti.
- Mantieni un equilibrio tra psicologico, simbolico e pratico.
- Adatta la ricchezza del testo al tier (free più breve, premium più articolato).
- Usa solo informazioni che puoi ragionevolmente dedurre dal payload.
    """.strip()

    user_prompt = (
        "Di seguito trovi il payload AI JSON per la SINASTRIA tra due persone.\n\n"
        "PAYLOAD_AI:\n"
        f"{json.dumps(payload_ai, ensure_ascii=False)}\n\n"
        "IMPORTANTE:\n"
        "- Usa SOLO le informazioni presenti nel payload.\n"
        "- NON inventare dati astrologici.\n"
        "- Rispondi SOLO con un JSON valido, SENZA testo extra, "
        "che rispetti ESATTAMENTE la struttura richiesta nel prompt di sistema.\n"
    )

    client = _get_client()

    try:
        resp = client.messages.create(
            model=ANTHROPIC_MODEL_SINASTRIA,
            max_tokens=1800,
            temperature=0.6,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": [{"type": "text", "text": user_prompt}],
                }
            ],
        )
    except APIStatusError as e:
        logger.error("[CLAUDE SINASTRIA ERROR] %s %s", e.status_code, e.response)
        raise

    text = ""
    if resp.content and len(resp.content) > 0:
        text = resp.content[0].text

    # Parse robusto del JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
        return json.loads(cleaned)
