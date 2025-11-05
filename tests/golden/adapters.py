from dataclasses import dataclass
# ... import dei tuoi metodi come sopra ...


@dataclass
class Natal:
when: datetime
place: dict # {lat, lon, name}


# --- helper per ottenere angoli di un datetime ---


def _angles_at(when: datetime) -> Dict[str, float]:
return calcola_pianeti_da_df(
df_tutti, when.day, when.month, when.year, colonne_extra=("Nodo","Lilith")
)




def compute_oroscopo_daily(when: datetime, place: Place, natal: Natal, png_path: Path) -> Dict[str, Any]:
angles_transit = _angles_at(when)
angles_natal = _angles_at(natal.when)


# Se hai una funzione reale di transiti tra due date, usala qui
intensities = None
if transiti_su_due_date is not None:
try:
# TODO: adatta ai parametri reali della tua funzione di transiti
# Esempio: transiti_su_due_date(natal.when, when, place.lat, place.lon, ...)
trans = transiti_su_due_date # placeholder, chiama davvero la tua funzione
# intensities = extract_intensities(trans)
except Exception:
pass


if intensities is None:
# Fallback deterministico basato sui gradi dei transiti rispetto al natal
# (qui usiamo solo angles_transit per semplicità; puoi migliorare con differenze angolari)
intensities = _mock_intensities_from_angles(angles_transit)


# Grafico a barre delle intensità
import matplotlib.pyplot as plt
fig = plt.figure()
ax = fig.add_subplot(111)
ax.bar(list(intensities.keys()), list(intensities.values()))
ax.set_ylim(0, 1)
ax.set_title(f"{when.isoformat()} — natal @ {natal.when.date()}")
png_path.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(png_path, bbox_inches='tight')
plt.close(fig)


return {
"angles_transit": angles_transit,
"angles_natal": angles_natal,
"intensities": intensities,
}




def compute_oroscopo_period(samples: List[datetime], place: Place, natal: Natal, png_path: Path) -> Dict[str, Any]:
chunks = []
tmp = png_path.with_name("__tmp.png")
for dt in samples:
r = compute_oroscopo_daily(dt, place, natal, tmp)
chunks.append(r["intensities"])
# media per categoria
agg = {k: float(sum(d[k] for d in chunks)/len(chunks)) for k in CATEGORIES}


# chart aggregato
import matplotlib.pyplot as plt
fig = plt.figure()
ax = fig.add_subplot(111)
ax.bar(list(agg.keys()), list(agg.values()))
ax.set_ylim(0, 1)
ax.set_title(f"Aggregazione su {len(samples)} campioni — natal @ {natal.when.date()}")
png_path.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(png_path, bbox_inches='tight')
plt.close(fig)


return {"intensities": agg, "n_samples": len(samples)}
