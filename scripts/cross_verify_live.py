import sys
sys.path.insert(0, 'C:\\Users\\neil-\\Projects\\Publication-AID-Project')
import json, urllib.request, uuid
from database.connection import get_supabase_client
from scrapers.mjl import _direct_post_mjl, _parse_mjl_response
from processors.issn import normalize_issn

client = get_supabase_client()

# Sample 5 mismatched + Academic Pediatrics + SAGE dual
samples = [
    ('BOUNDARY VALUE PROBLEMS', '4ec29321-9336-4ba6-819b-1b7232550957', '1687-2770', '1687-2770'),
    ('AMERICAN JOURNAL OF MATHEMATICS', '0744c7b8-37d2-4d9c-8c7f-0f0e0e0e0000', None, None),
    ('ACADEMIC PEDIATRICS', '7eee5e22-dc7c-44a1-b4a3-0e0a355da3cb', '1876-2859', '1876-2867'),
]

# Fetch actual journal IDs for samples from DB
samples = []
# Get 5 mismatched from previous run
ids = ['4ec29321-9336-4ba6-819b-1b7232550957', '7eee5e22-dc7c-44a1-b4a3-0e0a355da3cb'] 
# Actually fetch real mismatched
# Let's get 5 journals from cross_verify mismatches
journals = client.table('journals').select('id, title, print_issn, e_issn').limit(5).execute()
for j in journals.data:
    samples.append((j['title'], j['id'], j['print_issn'], j['e_issn']))

print(f"Live MJL cross-verify for {len(samples)} samples:", flush=True)
for title, jid, p_issn, e_issn in samples:
    norm_p = normalize_issn(p_issn or "")
    norm_e = normalize_issn(e_issn or "")
    db_mjl = client.table('mjl_results').select('mjl_index, mjl_status, mjl_issn_used').eq('journal_id', jid).execute()
    db_idx = db_mjl.data[0]['mjl_index'] if db_mjl.data else 'no data'
    db_status = db_mjl.data[0]['mjl_status'] if db_mjl.data else 'no data'
    # Live fetch via direct POST for both ISSNs
    live_idx = 'no data'
    live_status = 'Unable to Verify'
    for issn_raw, label in [(p_issn, 'P'), (e_issn, 'E')]:
        if not issn_raw or normalize_issn(issn_raw)=='no data':
            continue
        norm = normalize_issn(issn_raw)
        fmt = f"{norm[:4]}-{norm[4:8]}" if len(norm)>=8 else norm
        raw = _direct_post_mjl(fmt)
        if raw:
            status, idx, match, src = _parse_mjl_response(raw, norm)
            if status=='Found':
                live_idx = idx
                live_status = status
                break
            else:
                live_idx = idx
                live_status = status
    match = 'OK' if db_idx==live_idx else 'MISMATCH'
    print(f"{title[:40]:40} | DB: {db_idx:20} | Live: {live_idx:20} | {match} (DB {db_status} / Live {live_status}) ISSN P:{p_issn} E:{e_issn}", flush=True)

# Also APC live check via files vs DB
print("\nAPC live check (files vs DB) for same samples:", flush=True)
from scrapers.apc import verify_apc_indexing
from models import CFRJournal
# Need to re-run APC verification for these journals via files (fast, no network)
# Build CFRJournal objects
cfr_journals = []
for title, jid, p_issn, e_issn in samples:
    j = client.table('journals').select('publisher').eq('id', jid).limit(1).execute()
    pub = j.data[0]['publisher'] if j.data else ''
    cfr_journals.append(CFRJournal(sl_no=jid[:6], journal_title=title, print_issn=p_issn, e_issn=e_issn, publisher=pub, country=''))

# verify_apc_indexing expects list of CFRJournal, but we can call internal
from scrapers.apc import _build_issn_map, _fetch_elsevier_gpoa_issns
# Instead just check DB apc vs what _build_issn_map would give from files
# Check DB apc
for title, jid, p_issn, e_issn in samples[:3]:
    db_apcs = client.table('apc_results').select('publisher, apc_value, apc_currency, has_gpoa_discount').eq('journal_id', jid).execute()
    print(f"{title[:30]:30} DB APC: {db_apcs.data if db_apcs.data else 'none'}", flush=True)
