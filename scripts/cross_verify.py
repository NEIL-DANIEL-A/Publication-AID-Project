from database.connection import get_supabase_client
from database.hash import build_hash_input, compute_data_hash, _normalize_value
from processors.issn import normalize_issn as _n2
import time

client = get_supabase_client()
print('Bulk fetching journals + children...', flush=True)
t0=time.time()

# Fetch all journals
limit=1000
offset=0
all_journals=[]
while True:
    r=client.table('journals').select('id, title, print_issn, e_issn, publisher, country, data_hash').range(offset, offset+limit-1).execute()
    if not r.data: break
    all_journals.extend(r.data)
    if len(r.data)<limit: break
    offset+=limit
print(f'Journals: {len(all_journals)} in {time.time()-t0:.1f}s')

# Bulk fetch child maps via repository helpers
from database.repository import bulk_get_child_map, bulk_get_apc_map

jids=[j['id'] for j in all_journals]
cfr_map=bulk_get_child_map('cfr_results', jids)
scopus_map=bulk_get_child_map('scopus_results', jids)
mjl_map=bulk_get_child_map('mjl_results', jids)
scimago_map=bulk_get_child_map('scimago_results', jids)
apc_map=bulk_get_apc_map(jids)
print(f'Maps: cfr {len(cfr_map)} scopus {len(scopus_map)} mjl {len(mjl_map)} scimago {len(scimago_map)} apc groups {len(apc_map)}')

def _compute_apc_aggregate(entries):
    if not entries: return ''
    sorted_entries=sorted(entries, key=lambda e: (_normalize_value(e.get('publisher','')), _normalize_value(e.get('apc_currency','')), _normalize_value(e.get('apc_value',''))))
    parts=[]
    for e in sorted_entries:
        pub=_normalize_value(e.get('publisher',''))
        cur=_normalize_value(e.get('apc_currency',''))
        val=_normalize_value(e.get('apc_value',''))
        gpoa=_normalize_value(str(e.get('has_gpoa_discount', False)))
        orig=_normalize_value(str(e.get('original_apc_value','')))
        disc=_normalize_value(str(e.get('discounted_apc_value','')))
        parts.append(f"{pub}:{cur}:{val}:gpoa={gpoa}:orig={orig}:disc={disc}")
    return '|'.join(parts)

def _compute_apc_mode(entries):
    if not entries: return ''
    modes=sorted(set(_normalize_value(e.get('apc_mode_normalized','') or e.get('mode_raw','')) for e in entries if _normalize_value(e.get('apc_mode_normalized','') or e.get('mode_raw',''))))
    return '|'.join(modes)

mismatch=0
ok=0
samples=[]
for j in all_journals:
    jid=j['id']
    old_cfr=cfr_map.get(jid,{})
    old_scopus=scopus_map.get(jid,{})
    old_mjl=mjl_map.get(jid,{})
    old_scimago=scimago_map.get(jid,{})
    old_apc=apc_map.get(jid,[])
    hp=_n2(j.get('print_issn',''))
    he=_n2(j.get('e_issn',''))
    if hp=='no data': hp=''
    if he=='no data': he=''
    mjl_match=old_mjl.get('mjl_match_type','')
    hi=build_hash_input(
        journal_title=j.get('title',''),
        print_issn=hp, e_issn=he,
        publisher=j.get('publisher',''),
        country=j.get('country',''),
        cfr_sl_no=old_cfr.get('sl_no',''),
        scopus_status=old_scopus.get('scopus_status',''),
        scopus_match_type=old_scopus.get('match_type',''),
        scopus_source_title=old_scopus.get('source_title',''),
        scopus_sourcerecord_id=old_scopus.get('sourcerecord_id',''),
        scopus_publisher=old_scopus.get('scopus_publisher',''),
        scopus_coverage=old_scopus.get('scopus_coverage',''),
        scopus_issn=old_scopus.get('scopus_issn',''),
        scopus_eissn=old_scopus.get('scopus_eissn',''),
        scopus_raw_active=old_scopus.get('raw_active_status',''),
        scopus_raw_discontinued=old_scopus.get('raw_discontinued_flag',''),
        mjl_status=old_mjl.get('mjl_status',''),
        mjl_index=old_mjl.get('mjl_index',''),
        mjl_issn_used=old_mjl.get('mjl_issn_used',''),
        mjl_match_type=mjl_match,
        mjl_source_title=old_mjl.get('mjl_source_title',''),
        scimago_status=old_scimago.get('scimago_status',''),
        scimago_journal_id=old_scimago.get('journal_id_external',''),
        scimago_matched_issn=old_scimago.get('matched_issn',''),
        sjr=old_scimago.get('sjr',''),
        quartile=old_scimago.get('quartile',''),
        h_index=old_scimago.get('h_index',''),
        scimago_coverage=old_scimago.get('coverage',''),
        scimago_url=old_scimago.get('url',''),
        apc_aggregate=_compute_apc_aggregate(old_apc),
        apc_mode_aggregate=_compute_apc_mode(old_apc),
        has_gpoa_discount=str(any(a.get('has_gpoa_discount') for a in old_apc)),
        original_apc_value=str(old_apc[0].get('original_apc_value','') if old_apc else ''),
        discounted_apc_value=str(old_apc[0].get('discounted_apc_value','') if old_apc else ''),
        discount_percent=str(old_apc[0].get('discount_percent',0) if old_apc else '0'),
    )
    recomputed=compute_data_hash(hi)
    if recomputed!=j.get('data_hash',''):
        mismatch+=1
        if len(samples)<5:
            samples.append((j['title'][:40], jid[:8], j.get('data_hash','')[:12], recomputed[:12]))
    else:
        ok+=1

print(f'Hash check: OK {ok} / MISMATCH {mismatch} / total {len(all_journals)}')
if samples:
    print('Sample mismatches:')
    for s in samples:
        print(s)
else:
    print('All hashes consistent - DB vs recomputed match')

# Also check APC hash vs DB: sample journals where hash includes APC but DB apc may be stale
# Check journals with APC vs without
print(f'APC groups: {len(apc_map)} journals have APC, {len(all_journals)-len(apc_map)} have no APC')
