"""Evidence links are assembled from scoped ledger reads, never model-supplied URLs."""
def collect(job,result):
    if result.get('source')!='ledger_backend':return
    refs=list(getattr(job,'_finance_refs',[]))
    filters={k:result[k] for k in ('start','end','month','account_id','category_id','kind') if result.get(k)}
    if 'income' in result:
        refs.append(dict(type='summary',label='ยอดจริงจากบัญชี',income=result['income'],expense=result['expense'],filters=filters))
    for row in result.get('categories',[])[:8]:
        category=row.get('id') or row.get('category_id')
        if category:refs.append(dict(type='category',label=row['name'],amount=row['amount'],filters={**filters,'category_id':category,'kind':'expense'}))
    for item in result.get('items',[])[:10]:
        refs.append(dict(type='entry',label=item['description'],amount=item['amount'],date=item['occurred_on'],filters={**filters,'entry_id':item['id']}))
    unique={str((r['type'],r['filters'])):r for r in refs}
    job._finance_refs=list(unique.values())[-24:]
