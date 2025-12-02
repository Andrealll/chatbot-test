# astrobot_core/ai_diyana_qa.py

import os
import json
from typing import Optional, List, Dict, Any
from uuid import uuid4

from pydantic import BaseModel, Field
from anthropic import Anthropic, APIStatusError

# ============================================================
# CONFIG & CLIENT CLAUDE
# ============================================================

ANTHROPIC_MODEL_DYANA_QA = os.getenv(
    "ANTHROPIC_MODEL_DYANA_QA",
    "claude-3-5-haiku-20241022"
)
ANTHROPIC_MODEL_DYANA_TAGGER = os.getenv(
    "ANTHROPIC_MODEL_DYANA_TAGGER",
    "claude-3-5-haiku-20241022"
)

_anthropic_client: Optional[Anthropic] = None


def get_anthropic_client() -> Anthropic:
    global _anthropic_client
    if _anthropic_client is not None:
        return _anthropic_client

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY non impostata nell'ambiente")

    _anthropic_client = Anthropic(api_key=api_key)
    return _anthropic_client


# ============================================================
# Pydantic MODELS usati dalla route
# ============================================================

class ReadingModel(BaseModel):
    """
    Contesto della lettura su cui DYANA deve rispondere.
    Non vincoliamo la struttura del payload.
    reading_text = testo completo mostrato sul sito.
    """
    reading_id: Optional[str] = Field(
        None,
        description="ID lettura (da AstroBot o dal sito)"
    )
    reading_type: str = Field(
        ...,
        description='es. "oroscopo_weekly", "tema_natale", "sinastria"'
    )
    reading_label: Optional[str] = Field(
        None,
        description="Titolo mostrato sul sito"
    )
    reading_text: str = Field(
        ...,
        description="Testo completo mostrato sul sito (fonte primaria)"
    )
    # Any per non esplodere se arriva stringa JSON da Typebot
    reading_payload: Optional[Any] = Field(
        None,
        description="JSON grezzo generato da AstroBot o stringa JSON (opzionale)"
    )
    kb_tags: List[str] = Field(
        default_factory=list,
        description="Tag statici associati alla lettura (da AstroBot/sito)"
    )


class QaAnswerRequest(BaseModel):
    user_id: str
    session_id: Optional[str] = None
    reading: ReadingModel
    user_question: str
    previous_qas: Optional[List[Dict[str, str]]] = Field(
        default=None,
        description="Lista di Q/A precedenti nella stessa sessione (opzionale)"
    )
    question_origin: Optional[str] = Field(
        default=None,
        description='"included" | "extra" (per logging/analytics)'
    )
    question_tags: Optional[List[str]] = Field(
        default=None,
        description="Tag della domanda (se già calcolati dal client; altrimenti li deriva il backend)"
    )


class ErrorPayload(BaseModel):
    code: str
    message: str


class QaAnswerMeta(BaseModel):
    reading_id: Optional[str] = None
    reading_type: str
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    model: Optional[str] = None
    kb_docs_used: int = 0
    reading_tags: List[str] = []
    question_tags: List[str] = []


class QaAnswerResponse(BaseModel):
    status: str
    ai_answer: Optional[str]
    meta: Optional[QaAnswerMeta]
    error: Optional[ErrorPayload]


# ============================================================
# STUB KB RETRIEVAL (poi collegherai Supabase o altro)
# ============================================================

def kb_retrieve_for_dyana(
    reading_tags: List[str],
    question_tags: List[str],
    max_docs: int = 5
) -> List[str]:
    """
    In futuro: query su Supabase / vettoriale.
    Ora: stub che mostra quali tag userebbe.
    """
    combined: List[str] = []
    for tag in (question_tags + reading_tags):
        if tag not in combined:
            combined.append(tag)

    docs: List[str] = []
    for tag in combined:
        docs.append(f"[KB doc simulato per tag={tag}]")
        if len(docs) >= max_docs:
            break

    return docs


# ============================================================
# LAYER LLM: 1) TAGGER, 2) ANSWER
# ============================================================

def claude_derive_question_tags(
    reading_type: str,
    user_question: str,
    max_tags: int = 4
) -> List[str]:
    """
    Usa Claude per derivare tag tematici dalla domanda.
    Ritorna una lista di stringhe (es. ["amore_relazioni", "crescita_personale"]).
    """
    client = get_anthropic_client()

    system_msg = (
        "Sei un classificatore di domande per un assistente astrologico chiamato DYANA.\n"
        "Dato il testo di una domanda e il tipo di lettura (tema natale, oroscopo, sinastria, ecc.),\n"
        "devi restituire una lista JSON di tag tematici sintetici e stabili.\n\n"
        "Regole:\n"
        "- Rispondi SOLO con JSON nel formato: {\"tags\": [\"tag1\", \"tag2\", ...]}.\n"
        "- Usa tag brebrevi in snake_case, es:\n"
        "  amore_relazioni, lavoro_carriera, denaro_risorse, famiglia_radici,\n"
        "  benessere_salute, crescita_personale, spiritualita, amicizie_rete,\n"
        "  casa_cambiamenti, crisi_trasformazione, studio_viaggi, autostima_identita, generico.\n"
        f"- Max {max_tags} tag.\n"
    )

    user_msg = (
        f"Tipo di lettura: {reading_type}\n\n"
        f"Domanda dell'utente:\n\"{user_question}\"\n\n"
        "Scegli i tag più pertinenti."
    )

    resp = client.messages.create(
        model=ANTHROPIC_MODEL_DYANA_TAGGER,
        max_tokens=256,
        temperature=0.1,
        system=system_msg,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = resp.content[0].text.strip()

    try:
        data = json.loads(raw)
        tags = data.get("tags", [])
        if not isinstance(tags, list):
            return ["generico"]
        tags = [str(t).strip() for t in tags if str(t).strip()]
        if not tags:
            return ["generico"]
        return tags
    except Exception:
        return ["generico"]


def claude_generate_dyana_answer(
    reading: ReadingModel,
    kb_docs: List[str],
    user_question: str,
    previous_qas: Optional[List[Dict[str, str]]] = None
) -> Dict[str, Any]:
    """
    Chiamata principale a Claude per generare la risposta di DYANA.
    """
    client = get_anthropic_client()

    system_msg = (
        "Sei DYANA, un assistente astrologico evoluto.\n"
        "RUOLO:\n"
        "- Approfondisci e chiarisci letture astrologiche (oroscopi, temi natali, sinastrie)\n"
        "  che sono già state mostrate all'utente sul sito.\n\n"
        "REGOLE:\n"
        "- Usa come fonte principale il testo della lettura fornita.\n"
        "- Usa eventuali dati strutturati e documenti di knowledge base come supporto,\n"
        "  senza inventare nuovi calcoli o cambiare il significato di base.\n"
        "- Se la domanda è molto ampia, puoi dare una risposta articolata.\n"
        "- Se la domanda è molto specifica, rispondi in modo focalizzato.\n"
        "- Sii chiaro, empatico, concreto.\n"
        "- Rispondi SEMPRE in italiano.\n"
        "- NON parlare di prezzi, crediti o piani: sono gestiti dal sito, non da te.\n"
    )

    parts: List[str] = []

    # Info base
    parts.append(f"Tipo di lettura: {reading.reading_type}")
    if reading.reading_label:
        parts.append(f"Titolo mostrato sul sito: {reading.reading_label}")

    # Testo principale
    parts.append("\n=== LETTURA MOSTRATA ALL'UTENTE ===\n")
    parts.append(reading.reading_text)

    # Payload strutturato (qualsiasi cosa sia)
    if reading.reading_payload is not None:
        try:
            payload_str = json.dumps(reading.reading_payload, ensure_ascii=False)[:4000]
        except TypeError:
            payload_str = str(reading.reading_payload)[:4000]
        parts.append("\n=== DATI STRUTTURATI (OPZIONALI) ===\n")
        parts.append(payload_str)

    # Q/A precedenti
    if previous_qas:
        parts.append("\n=== DOMANDE E RISPOSTE PRECEDENTI NELLA SESSIONE ===")
        for i, qa in enumerate(previous_qas, start=1):
            q = qa.get("question", "")
            a = qa.get("answer", "")
            parts.append(f"\n[{i}] Domanda precedente: {q}\nRisposta data: {a}")

    # KB
    if kb_docs:
        parts.append("\n=== DOCUMENTI DI KNOWLEDGE BASE RILEVANTI ===")
        for doc in kb_docs:
            parts.append("- " + doc)

    # Domanda attuale
    parts.append("\n=== DOMANDA ATTUALE DELL'UTENTE ===")
    parts.append(user_question)

    # Istruzioni finali
    parts.append(
        "\n=== ISTRUZIONI PER LA RISPOSTA ===\n"
        "- Collega la risposta alla lettura fornita.\n"
        "- Se utile, collega anche i documenti di KB ma senza contraddire la lettura.\n"
        "- Non rifare i calcoli astrologici: lavora su ciò che ti è stato dato.\n"
        "- Rispondi in italiano, tono caldo ma professionale.\n"
    )

    user_msg = "\n".join(parts)

    resp = client.messages.create(
        model=ANTHROPIC_MODEL_DYANA_QA,
        max_tokens=1024,
        temperature=0.5,
        system=system_msg,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = resp.content[0].text
    usage = getattr(resp, "usage", None)
    tokens_in = getattr(usage, "input_tokens", None) if usage else None
    tokens_out = getattr(usage, "output_tokens", None) if usage else None

    return {
        "text": text,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "model": resp.model,
    }


# ============================================================
# FUNZIONE DI SERVIZIO USATA DALLA ROUTE
# ============================================================

def process_diyana_qa(req: QaAnswerRequest) -> QaAnswerResponse:
    """
    Logica completa: tagger → KB → risposta Claude → meta.
    Usata dalla route FastAPI.
    """
    reading = req.reading

    # reading_id minimo per logging
    reading_id = reading.reading_id or f"inline_{uuid4().hex}"
    reading.reading_id = reading_id

    # 1) Derivazione question_tags (se non fornite)
    if req.question_tags is not None:
        question_tags = req.question_tags
    else:
        try:
            question_tags = claude_derive_question_tags(
                reading_type=reading.reading_type,
                user_question=req.user_question,
            )
        except (APIStatusError, Exception):
            question_tags = ["generico"]

    # 2) Retrieval KB
    kb_docs = kb_retrieve_for_dyana(
        reading_tags=reading.kb_tags,
        question_tags=question_tags,
        max_docs=5
    )

    # 3) Risposta Claude
    try:
        llm_res = claude_generate_dyana_answer(
            reading=reading,
            kb_docs=kb_docs,
            user_question=req.user_question,
            previous_qas=req.previous_qas
        )
    except (APIStatusError, Exception):
        return QaAnswerResponse(
            status="error",
            ai_answer=None,
            meta=None,
            error=ErrorPayload(
                code="LLM_ERROR",
                message="Errore nella generazione della risposta di DYANA"
            )
        )

    # 4) TODO: logging persistente (DB) se vuoi

    return QaAnswerResponse(
        status="ok",
        ai_answer=llm_res["text"],
        meta=QaAnswerMeta(
            reading_id=reading_id,
            reading_type=reading.reading_type,
            tokens_in=llm_res["tokens_in"],
            tokens_out=llm_res["tokens_out"],
            model=llm_res["model"],
            kb_docs_used=len(kb_docs),
            reading_tags=reading.kb_tags,
            question_tags=question_tags,
        ),
        error=None
    )
