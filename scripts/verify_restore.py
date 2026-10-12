"""Restore a dump to a uniquely named disposable DB; never overwrite production."""
from pathlib import Path
import subprocess
import uuid

root=Path(__file__).resolve().parents[1]
dumps=sorted((root/'backups').glob('finance-*.dump'))
if not dumps: raise SystemExit('Run sh scripts/backup.sh first')
name='sf_restore_test_'+uuid.uuid4().hex[:12]
prefix=['docker','compose','exec','-T','postgres']
def run(args,**kwargs):
    return subprocess.run(prefix+args,cwd=root,check=True,capture_output=True,**kwargs)
created=False
try:
    run(['createdb','-U','finance',name]);created=True
    with dumps[-1].open('rb') as data:
        run(['pg_restore','-U','finance','-d',name],stdin=data)
    for table in ('users','workspaces','accounts','entries','lines','attachments','proposals','providers','ai_settings','budgets','entry_revisions','goals','goal_movements','recurring_rules','recurring_occurrences','memberships','invitations','membership_events','conversations','messages','jobs','chat_generations','telegram_deliveries','chat_preferences','chat_actions','assistant_changes','email_tokens','assistant_preferences','ai_usage_policies','ai_usage'):
        sql=f'SELECT count(*) FROM {table}'
        live=run(['psql','-U','finance','-d','finance','-Atc',sql]).stdout
        restored=run(['psql','-U','finance','-d',name,'-Atc',sql]).stdout
        if live!=restored: raise RuntimeError('Row count mismatch; stop writes before verifying a fresh backup')
    query='SELECT count(*) FROM (SELECT entry_id FROM lines GROUP BY entry_id HAVING sum(signed_amount)<>0) unbalanced'
    if run(['psql','-U','finance','-d',name,'-Atc',query]).stdout.strip()!=b'0': raise RuntimeError('Unbalanced restored ledger')
    allocations='SELECT workspace_id,goal_id,sum(signed_amount) FROM goal_movements GROUP BY workspace_id,goal_id ORDER BY workspace_id,goal_id'
    if run(['psql','-U','finance','-d','finance','-Atc',allocations]).stdout!=run(['psql','-U','finance','-d',name,'-Atc',allocations]).stdout: raise RuntimeError('Restored goal allocation mismatch')
    schedules='SELECT id,next_on,paused FROM recurring_rules ORDER BY id'
    occurrences='SELECT rule_id,scheduled_on,proposal_id,account_id,category_id FROM recurring_occurrences ORDER BY rule_id,scheduled_on'
    members='SELECT user_id,workspace_id,role FROM memberships ORDER BY workspace_id,user_id'
    invites='SELECT id,workspace_id,email,status,mode,token_hash,expires FROM invitations ORDER BY id'
    privacy='SELECT user_id,workspace_id,retention_days FROM chat_preferences ORDER BY user_id,workspace_id'
    chats='SELECT id,title,privacy,temporary,created_at,updated_at,capture_context FROM conversations ORDER BY id'
    profiles='SELECT id,email,name,email_verified_at,password FROM users ORDER BY id'
    actions='SELECT id,workspace_id,conversation_id,user_id,code,payload,status,expires,entry_id FROM chat_actions ORDER BY id'
    spaces='SELECT id,name,archived_at,version,ai_epoch FROM workspaces ORDER BY id'
    email_links='SELECT token_hash,user_id,purpose,expires,used,delivery,encrypted_payload,attempts,next_attempt FROM email_tokens ORDER BY token_hash'
    ai_options='SELECT workspace_id,cloud_enabled,demo_fallback,max_attempted_providers FROM ai_settings ORDER BY workspace_id'
    ai_providers='SELECT id,workspace_id,kind,model,task,priority,encrypted_key,name,endpoint,enabled,timeout_seconds,retries,max_tokens,temperature,reasoning_effort,supports_images FROM providers ORDER BY id'
    assistant_changes='SELECT id,workspace_id,user_id,action_id,summary,payload,created_at FROM assistant_changes ORDER BY id'
    memory='SELECT user_id,workspace_id,"values",version FROM assistant_preferences ORDER BY user_id,workspace_id'
    usage_policy='SELECT workspace_id,monthly_limit,prices FROM ai_usage_policies ORDER BY workspace_id'
    usage='SELECT id,workspace_id,provider_id,model,task,month,input_tokens,output_tokens,cost,estimated,status,created_at FROM ai_usage ORDER BY id'
    generations='SELECT job_id,conversation_id,stop_requested FROM chat_generations ORDER BY job_id'
    diagnostics='SELECT id,diagnostics,diagnostics_expires FROM jobs ORDER BY id'
    evidence='SELECT id,"references" FROM messages ORDER BY id'
    for snapshot in (diagnostics,generations,memory,usage_policy,usage,evidence,assistant_changes,ai_options,ai_providers,email_links,schedules,occurrences,members,invites,privacy,chats,profiles,actions,spaces):
        if run(['psql','-U','finance','-d','finance','-Atc',snapshot]).stdout!=run(['psql','-U','finance','-d',name,'-Atc',snapshot]).stdout: raise RuntimeError('Restored schedule or membership snapshot mismatch')
    print('Restore verified in disposable database: row counts, goal allocations and recurring, membership and AI configuration snapshots match; journals balance.')
finally:
    if created: run(['dropdb','-U','finance',name])
