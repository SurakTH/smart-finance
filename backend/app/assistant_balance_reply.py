"""Grounded last resort if a model requests tools even in the final text-only call."""
LIMIT_MESSAGE='ฉันค้นข้อมูลครบขอบเขตแล้ว แต่ยังสรุปคำตอบจากผลที่ได้ไม่สำเร็จค่ะ ไม่ได้บันทึกหรือแก้ข้อมูล ลองระบุสิ่งที่ต้องการดูเพิ่มเติมได้ค่ะ'

def fallback(cache):
    for (name,_),result in reversed(list(cache.items())):
        if name!='lookup_workspace':continue
        for row in reversed(result.get('results',[])):
            total=row.get('summary')
            if row.get('resource')!='balances' or not total or not total.get('complete'):continue
            def money(value):
                sign='-' if value<0 else '';value=abs(value)
                return f'{sign}฿{value//100:,}.{value%100:02d}'
            scope=total['scope'];label='บัญชีที่ค้นพบ' if scope.get('q') or scope.get('kind') else 'workspace นี้'
            return (f"ยอดคงเหลือจากรายการที่บันทึกแล้วใน{label} ({total['account_count']} บัญชี) ค่ะ\n\n"
                    f"- เงินในบัญชีสินทรัพย์: **{money(total['assets_satang'])}**\n"
                    f"- หนี้สิน: **{money(total['liabilities_satang'])}**\n"
                    f"- ยอดสุทธิหลังหักหนี้: **{money(total['net_satang'])}**\n\nยอดนี้รวมทุกบัญชีตามตัวกรองแล้ว ไม่ได้เปลี่ยนข้อมูลค่ะ")
    return None
