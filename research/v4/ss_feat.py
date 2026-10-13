# StockScans point-in-time panels -> (date x isin) matrices, forward-filled from each snapshot until the next one.
import json, os
from swing import *
def sym2isin():
    ev = rs2.results_events(); m = dict(zip(ev['symbol'].astype(str), ev['isin']))
    return m
def panel(fname, field, max_age_days=70):
    path = f'{rs2.S}/data/ssp/{fname}'
    if not os.path.exists(path): return None
    m = sym2isin(); rows = {}
    for line in open(path):
        r = json.loads(line); cid = str(r['row'].get('companyId', ''))
        sym = cid.split(':', 1)[-1]; isin = m.get(sym)
        v = r['row'].get(field)
        if isin is None or isin not in ISINS or v is None: continue
        rows.setdefault(pd.Timestamp(r['d']), {})[isin] = v
    snap = pd.DataFrame(rows).T.sort_index().reindex(columns=ISINS)
    snap = snap.apply(pd.to_numeric, errors='coerce')
    # snapshot dated d is known at the close of d: align to trading days, carry forward
    M = snap.reindex(DATES.union(snap.index)).ffill(limit=None).reindex(DATES)
    last = pd.Series(snap.index, index=snap.index).reindex(DATES.union(snap.index)).ffill().reindex(DATES)
    age = (DATES.to_series() - last).dt.days
    ok = np.repeat((age.values <= max_age_days)[:, None], M.shape[1], axis=1)
    return M.where(ok)
