from database.connection import get_supabase_client
client = get_supabase_client()
run_id='0b4c7f66-2f32-4d81-a3c5-63616753d00e'
chs = client.table('journal_changes').select('journal_id').eq('pipeline_run_id', run_id).limit(3).execute()
import json, glob
from processors.issn import normalize_issn
for ch in chs.data:
    jid=ch['journal_id']
    j=client.table('journals').select('title, print_issn, e_issn').eq('id', jid).execute()
    title=j.data[0]['title']
    pissn=j.data[0]['print_issn']
    eissn=j.data[0]['e_issn']
    apc_db=client.table('apc_results').select('publisher, apc_value, apc_currency, apc_mode_normalized, has_gpoa_discount, original_apc_value, discounted_apc_value, discount_percent').eq('journal_id', jid).execute()
    print(f"{title[:30]:30} P:{pissn} E:{eissn} -> DB APC {apc_db.data}")
    norm_p=normalize_issn(pissn)
    norm_e=normalize_issn(eissn)
    found=False
    for f in glob.glob('apc_cache/*.json'):
        try:
            data=json.load(open(f, encoding='utf-8'))
            for rec in data:
                issn=rec.get('issn','').replace('-','')
                if issn in (norm_p, norm_e):
                    print(f"  cache {f.split(chr(92))[-1]}: {rec.get('publisher')} {rec.get('apc_value')} {rec.get('apc_currency')} {rec.get('mode_raw')} gpoa={rec.get('has_gpoa_discount')}")
                    found=True
                    break
        except: pass
        if found: break
    if not found:
        print('  not in cache')
