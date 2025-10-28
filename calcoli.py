import pandas as pd

# Carica i dati
df_tutti = pd.read_csv("data/pianeti.csv")

def calcola_pianeti_da_df(
    df_tutti,
    giorno: int,
    mese: int,
    anno: int,
    colonne_extra=('Nodo', 'Lilith')
):
    """
    Ritorna (valori_raw, valori_norm)

    - valori_raw: {nome: valore} con negativi preservati (retrogrado)
    - valori_norm: {nome: valore} = abs(valori_raw)
    """
    r = df_tutti[
        (df_tutti['Giorno'] == giorno) &
        (df_tutti['Mese'] == mese) &
        (df_tutti['Anno'] == anno)
    ]
    if r.empty:
        raise ValueError("Nessun dato per la data richiesta nel df_tutti.")
    row = r.iloc[0]

    exclude = {'Giorno', 'Mese', 'Anno'}
    valori_raw = {}
    valori_norm = {}

    for col in df_tutti.columns:
        if col in exclude:
            continue
        try:
            v_raw = float(row[col])
        except Exception:
            continue

        valori_raw[col] = v_raw
        valori_norm[col] = abs(v_raw)

    ordine = ['Sole','Luna','Mercurio','Venere','Marte','Giove',
              'Saturno','Urano','Nettuno','Plutone']
    for extra in colonne_extra:
        if extra in valori_raw and extra not in ordine:
            ordine.append(extra)
    for c in valori_raw.keys():
        if c not in ordine:
            ordine.append(c)

    valori_raw = {k: valori_raw[k] for k in ordine if k in valori_raw}
    valori_norm = {k: valori_norm[k] for k in ordine if k in valori_norm}

    return valori_raw, valori_norm
