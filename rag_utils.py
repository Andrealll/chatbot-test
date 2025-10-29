# rag_utils.py — AstroBot v10
import os
import glob
from typing import List, Tuple
from ai_utils import export_to_chunks

# ======================================================
# PATH DI DEFAULT
# ======================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_PATH = os.path.join(BASE_DIR, "knowledge")

# ======================================================
# CARICAMENTO FILE
# ======================================================

def load_text_files(path: str = KNOWLEDGE_PATH) -> List[Tuple[str, str]]:
    """
    Legge tutti i file .txt nella cartella /knowledge
    Restituisce [(nome_file, contenuto)]
    """
    files = glob.glob(os.path.join(path, "*.txt"))
    texts = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                content = fh.read().strip()
            name = os.path.basename(f)
            texts.append((name, content))
        except Exception as e:
            print(f"[ERRORE] Impossibile leggere {f}: {e}")
    return texts


# ======================================================
# DIVISIONE TESTI IN CHUNK
# ======================================================

def chunk_knowledge_files(chunk_size: int = 500) -> List[Tuple[str, str]]:
    """
    Divide tutti i testi caricati in blocchi (chunk).
    Restituisce lista [(nome_file, chunk_testuale)]
    """
    all_chunks = []
    for name, text in load_text_files():
        chunks = export_to_chunks([text], chunk_size)
        for ch in chunks:
            all_chunks.append((name, ch))
    return all_chunks


# ======================================================
# RICERCA SIMULATA (in attesa del vero embedding)
# ======================================================

def get_relevant_chunks(query: str, top_k: int = 3) -> List[Tuple[str, float]]:
    """
    Restituisce i chunk più pertinenti (placeholder, ricerca full-text semplificata).
    """
    chunks = chunk_knowledge_files()
    query_lower = query.lower()
    matches = []
    for name, ch in chunks:
        score = 0.0
        for word in query_lower.split():
            if word in ch.lower():
                score += 1.0
        if score > 0:
            matches.append((f"{name}: {ch[:250]}...", min(1.0, score / 5)))
    if not matches:
        return [("Nessun testo rilevante trovato nella knowledge base locale.", 0.0)]
    matches = sorted(matches, key=lambda x: x[1], reverse=True)[:top_k]
    return matches
