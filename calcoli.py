{
 "cells": [
  {
   "cell_type": "code",
   "execution_count": null,
   "id": "6dc5f0d8-ebfc-4392-878c-aa2ac617acf8",
   "metadata": {},
   "outputs": [],
   "source": [
    "import pandas as pd\n",
    "\n",
    "# Carichiamo i dati una volta sola\n",
    "df_tutti = pd.read_csv(\"effemeridi_1980_2000.xlsx\")\n",
    "\n",
    "def calcola_pianeti_da_df(\n",
    "    df_tutti,\n",
    "    giorno: int,\n",
    "    mese: int,\n",
    "    anno: int,\n",
    "    colonne_extra=('Nodo', 'Lilith')\n",
    "):\n",
    "    \"\"\"\n",
    "    Ritorna (valori_raw, valori_norm)\n",
    "    \"\"\"\n",
    "    r = df_tutti[\n",
    "        (df_tutti['Giorno'] == giorno) &\n",
    "        (df_tutti['Mese'] == mese) &\n",
    "        (df_tutti['Anno'] == anno)\n",
    "    ]\n",
    "    if r.empty:\n",
    "        raise ValueError(\"Nessun dato per la data richiesta nel df_tutti.\")\n",
    "    row = r.iloc[0]\n",
    "\n",
    "    exclude = {'Giorno', 'Mese', 'Anno'}\n",
    "    valori_raw = {}\n",
    "    valori_norm = {}\n",
    "\n",
    "    for col in df_tutti.columns:\n",
    "        if col in exclude:\n",
    "            continue\n",
    "        try:\n",
    "            v_raw = float(row[col])\n",
    "        except Exception:\n",
    "            continue\n",
    "\n",
    "        valori_raw[col] = v_raw\n",
    "        valori_norm[col] = abs(v_raw)\n",
    "\n",
    "    ordine = ['Sole','Luna','Mercurio','Venere','Marte','Giove',\n",
    "              'Saturno','Urano','Nettuno','Plutone']\n",
    "    for extra in colonne_extra:\n",
    "        if extra in valori_raw and extra not in ordine:\n",
    "            ordine.append(extra)\n",
    "    for c in valori_raw.keys():\n",
    "        if c not in ordine:\n",
    "            ordine.append(c)\n",
    "\n",
    "    valori_raw = {k: valori_raw[k] for k in ordine if k in valori_raw}\n",
    "    valori_norm = {k: valori_norm[k] for k in ordine if k in valori_norm}\n",
    "\n",
    "    return valori_raw, valori_norm"
   ]
  }
 ],
 "metadata": {
  "kernelspec": {
   "display_name": "Python [conda env:base] *",
   "language": "python",
   "name": "conda-base-py"
  },
  "language_info": {
   "codemirror_mode": {
    "name": "ipython",
    "version": 3
   },
   "file_extension": ".py",
   "mimetype": "text/x-python",
   "name": "python",
   "nbconvert_exporter": "python",
   "pygments_lexer": "ipython3",
   "version": "3.13.5"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 5
}
