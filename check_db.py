#!/usr/bin/env python3
from database.connection import get_supabase_client

client = get_supabase_client()

# Get Elsevier APC records with GPOA
res = client.table('apc_results').select('*').eq('publisher', 'Elsevier').eq('has_gpoa_discount', True).execute()
print(f'Elsevier GPOA records: {len(res.data)}')
for r in res.data[:5]:
    print(f"  journal_id={r['journal_id']}: apc_value={r['apc_value']}, original={r['original_apc_value']}, discounted={r['discounted_apc_value']}, discount_pct={r['discount_percent']}")