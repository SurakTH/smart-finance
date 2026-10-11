"""Static validation metadata only; never include model input or unknown keys."""
FIELDS={'queries','resource','q','kind','month','cursor','limit','operation','start','end','account_id','category_id','other_account_id','amount','intent','description','occurred_on','transactions','attachment_id','reply','toolkit','operations','changes','entry_id','reason','name','target','due_on','rationale'}
CODES={'missing','extra_forbidden','string_type','string_too_long','literal_error','uuid_parsing','int_type','greater_than','less_than_equal','greater_than_equal','string_pattern_mismatch','date_from_datetime_parsing','json_invalid','model_type'}

def issues(error):
    result=[]
    for issue in error.errors(include_input=False,include_url=False)[:5]:
        path=[p for p in issue['loc'] if isinstance(p,str) and p in FIELDS]
        result.append({'field':'.'.join(path) or 'arguments','code':issue['type'] if issue['type'] in CODES else 'invalid'})
    return result

def valid_issues(values):
    if not isinstance(values,list):return []
    return [dict(field=v['field'],code=v['code']) for v in values[:5] if isinstance(v,dict) and isinstance(v.get('field'),str) and all(p in FIELDS|{'arguments'} for p in v['field'].split('.')) and isinstance(v.get('code'),str) and v.get('code') in CODES|{'invalid','unsupported_filter','unknown_reference'}]
