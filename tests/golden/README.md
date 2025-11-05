# Golden master AstroBot

Obiettivo: congelare una baseline affidabile per **tema**, **sinastria** e **oroscopi** (daily/weekly/monthly/annual) e intercettare regressioni con pytest.

## Tolleranze
- **Angoli**: ±0,5° (differenza circolare)
- **Intensità**: ±10% (tolleranza relativa)
- **Immagini PNG**: soglia RMSE ≤ 0,03 (normalizzata su 0–1)

## Workflow
1. Definisci/aggiorna i casi in `cases.yml` (incluso il `natal`).
2. Implementa eventuali adattamenti in `adapters.py` per collegarti ai metodi reali di `astrobot_core` o del service.
3. Genera i golden:  
   ```bash
   python tests/golden/generate_golden.py --overwrite
   ```
4. Esegui i test:  
   ```bash
   pytest -k golden -q
   ```
5. (Opzionale) Integra in CI con GitHub Actions.

> Nota: se cambi volontariamente l’algoritmo o la versione delle effemeridi, **rigenera i golden** e committa i nuovi file in `tests/golden/data/`.
