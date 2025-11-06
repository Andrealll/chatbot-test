@app.post("/tema", tags=["Tema"], summary="Calcolo tema natale + interpretazione")
async def tema(payload: TemaRequest):
    start = time.time()

    carta_base64 = None
    carta_error = None
    interpretazione = None
    interpretazione_error = None

    try:
        # 1) Parsing data/ora
        try:
            dt_nascita = datetime.strptime(
                f"{payload.data} {payload.ora}", "%Y-%m-%d %H:%M"
            )
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="Formato data/ora non valido. Usa data=YYYY-MM-DD e ora=HH:MM.",
            )

        # 2) ASC, MC, Case
        asc_mc_case = calcola_asc_mc_case(
            citta=payload.citta,
            anno=dt_nascita.year,
            mese=dt_nascita.month,
            giorno=dt_nascita.day,
            ora=dt_nascita.hour,
            minuti=dt_nascita.minute,
        )

        # 3) Pianeti (con fallback se la funzione non supporta colonne_extra)
        try:
            # versione “nuova”
            pianeti = calcola_pianeti_da_df(
                df_tutti,
                giorno=dt_nascita.day,
                mese=dt_nascita.month,
                anno=dt_nascita.year,
                colonne_extra=("Nodo", "Lilith"),
            )
        except TypeError:
            # versione “vecchia” senza colonne_extra
            pianeti = calcola_pianeti_da_df(
                df_tutti,
                giorno=dt_nascita.day,
                mese=dt_nascita.month,
                anno=dt_nascita.year,
            )

        pianeti_decod = decodifica_segni(pianeti)

        # 4) Grafico polare: prima prova la firma nuova, poi fallback a dati_tema
        try:
            try:
                # firma nuova (esplicita)
                carta_base64 = genera_carta_base64(
                    anno=dt_nascita.year,
                    mese=dt_nascita.month,
                    giorno=dt_nascita.day,
                    ora=dt_nascita.hour,
                    minuti=dt_nascita.minute,
                    lat=asc_mc_case["lat"],
                    lon=asc_mc_case["lon"],
                    fuso_orario=asc_mc_case["fuso_orario"],
                    sistema_case="placidus",
                    include_node=True,
                    include_lilith=True,
                    mostra_asc=True,
                    mostra_mc=True,
                    titolo=None,
                )
            except TypeError:
                # firma vecchia: genera_carta_base64(dati_tema, ...)
                dati_tema = {
                    "data": dt_nascita.strftime("%Y-%m-%d %H:%M"),
                    "pianeti": pianeti,
                    "pianeti_decod": pianeti_decod,
                    "asc_mc_case": asc_mc_case,
                }
                # uso la forma più compatibile possibile: solo dati_tema
                carta_base64 = genera_carta_base64(dati_tema)
        except Exception as e:
            carta_error = f"Errore genera_carta_base64: {e}"

        # 5) Interpretazione Groq: prima nuova firma, poi fallback “legacy”
        try:
            try:
                # firma nuova, completa
                interpretazione = interpreta_groq(
                    nome=payload.nome,
                    citta=payload.citta,
                    data_nascita=payload.data,
                    ora_nascita=payload.ora,
                    pianeti=pianeti_decod,
                    asc_mc_case=asc_mc_case,
                    domanda=payload.domanda,
                    scope=payload.scope or "tema",
                )
            except TypeError:
                # firma vecchia: ipotizzo ordine (pianeti, asc_mc_case, domanda, sco
