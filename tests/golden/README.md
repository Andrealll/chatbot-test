# Golden master AstroBot


Obiettivo: congelare una baseline affidabile per tema, sinastria e oroscopi (daily/weekly/monthly/annual) e intercettare regressioni con pytest.


Tolleranze:
- Angoli: ±0,5° (con differenza circolare)
- Intensità: ±10% (relativa)
- PNG: RMSE ≤ 0,03


Workflow
1) Definisci i casi in `cases.yml`.
2) Implementa gli adapter in `adapters.py` per mappare i tuoi metodi.
3) Genera i golden: `python tests/golden/generate_golden.py --overwrite`.
4) Lancia i test: `pytest -k golden -q`.
5) (Opzionale) Aggiungi a CI.
