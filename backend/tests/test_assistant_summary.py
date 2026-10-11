import json
import pytest
from app.assistant_summary import parse,render,Summary
from test_assistant_finance import assistant,tool
from test_balance_summary import opening


def test_verified_balance_answer_in_one_call(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    opening(c,b,wallet,123456)
    state['responses']=[tool('answer_finance_summary',{'report':'balances'})]
    content=send('ตอนนี้ฉันมีเงินเท่าไร?')['content']
    assert '฿1,234.56' in content and len(state['calls'])==1
    assert c.get(b+'/transaction-report').json()['total']==1


def test_verified_monthly_answer_and_no_post(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000)
    state['responses']=[tool('answer_finance_summary',{'report':'monthly'})]
    content=send('เดือนนี้ใช้ไปเท่าไร')['content']
    assert '**80.00 บาท**' in content and '**-80.00 บาท**' in content
    assert len(state['calls'])==1 and c.get(b+'/transaction-report').json()['total']==1


@pytest.mark.parametrize('value',[{'report':'balances','month':'2026-10'},{'report':'monthly','month':'2026-99'},{'report':'monthly','account_id':'foreign'},{'report':'delete'}])
def test_summary_does_not_silently_ignore_scope(value):
    with pytest.raises(ValueError):parse(json.dumps(value))


def test_renderer_escapes_category_instructions_and_exact_cents():
    answer=render(Summary(report='monthly'),dict(month='2026-10',income=1,expense=100000000001,net=-100000000000,categories=[dict(name='[click](https://bad)\n<script>',amount=1)]))
    assert '1,000,000,000.01' in answer and '0.01' in answer
    assert '[click]' not in answer and '<script>' not in answer
