import re
import requests
import argparse
from collections import Counter
from datetime import datetime, timedelta
import sys

# ======================
# Script version
# ======================
VERSION = "2.3.2"

# ======================
# Регулярка для валидации украинских номеров
# ======================
PHONE_PATTERN = re.compile(
    r"^\+380(39|50|63|66|67|68|73|91|92|93|95|96|97|98|99)"
    r"(?!0000000|1111111|2222222|3333333|4444444|5555555|6666666|7777777|8888888|9999999)"
    r"\d{7}$"
)

# ======================
# Утилита: форматирование дат
# ======================
def format_dt(dt: datetime) -> str:
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{ms:03d}"

# ======================
# API
# ======================
def get_access_token(login, url):
    r = requests.post(url, json={"apiLogin": login}, headers={"Content-Type": "application/json"})
    r.raise_for_status()
    token = r.json().get("token")
    if not token:
        raise RuntimeError("Не удалось получить токен")
    return token

def get_organizations(token, url):
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    return r.json().get("organizations", [])

def get_deliveries(token, url, org_id, start, end):
    payload = {
        "organizationIds": [org_id],
        "deliveryDateFrom": start,
        "deliveryDateTo": end,
        "statuses": ["Closed"]
    }
    r = requests.post(url, json=payload,
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    r.raise_for_status()
    data = r.json()
    orders = []
    for batch in data.get("ordersByOrganizations", []):
        orders += batch.get("orders", [])
    return orders

# ======================
# Выбор организаций
# ======================
def select_orgs(orgs):
    print("\nОрганизации:")
    for i, o in enumerate(orgs, 1):
        print(f" {i}. {o.get('name') or o['id']} ({o['id']})")
    inp = input("Выберите через запятую: ")
    sel = []
    for p in inp.split(','):
        try:
            idx = int(p.strip()) - 1
            sel.append(orgs[idx])
        except:
            pass
    if not sel:
        sys.exit("Ничего не выбрано")
    return sel

# ======================
# Сбор по дням
# ======================
def fetch_orders(token, url, org_id, frm, to):
    start = datetime.strptime(frm, '%Y-%m-%d %H:%M:%S.%f')
    end   = datetime.strptime(to,  '%Y-%m-%d %H:%M:%S.%f')
    now   = datetime.now()
    if end > now:
        end = now
    cur = start
    all_orders = []
    while cur < end:
        nxt = min(cur + timedelta(days=1), end)
        s = format_dt(cur)
        e = format_dt(nxt)
        try:
            all_orders += get_deliveries(token, url, org_id, s, e)
        except requests.HTTPError:
            pass
        cur = nxt
    return all_orders

# ======================
# Сводка
# ======================
def summarize(orders):
    phones, invalid = [], []
    no_client = no_phone = zero = 0
    for o in orders:
        od = o.get('order') or o
        if not od.get('customer'):
            no_client += 1
            continue
        ph = od.get('phone')
        if not ph:
            no_phone += 1
            continue
        phones.append(ph)
        if not PHONE_PATTERN.match(ph):
            invalid.append(ph)
        if od.get('sum', 0) == 0:
            zero += 1

    cnt = Counter(phones)
    dup = {p: c for p, c in cnt.items() if c > 1}
    return {
        "total": len(orders),
        "no_client": no_client,
        "no_phone": no_phone,
        "invalid": sorted(set(invalid)),
        "inv_count": len(invalid),
        "zero": zero,
        "unique": len(cnt),
        "dup": dup
    }

# ======================
# Отчет
# ======================
def print_report(sumry, frm, to, orgs):
    print(f"\n=== Отчет {frm} — {to} ===")
    for o in orgs:
        print(f" - {o.get('name')} [{o['id']}]")
    print(f"Всего: {sumry['total']}, без клиента: {sumry['no_client']}, без телефона: {sumry['no_phone']}")
    print(f"Нулевых сумм: {sumry['zero']}, уникальных тел: {sumry['unique']}")
    print(f"Неверных номеров: {sumry['inv_count']}")
    for tel in sumry['invalid']:
        print(f"  ! {tel}")
    print(f"Дубли (>1): {len(sumry['dup'])}")
    for p, c in sumry['dup'].items():
        print(f"  * {p}: {c}")

# ======================
# Подробно
# ======================
def print_details(obj):
    od = obj.get('order') or {}
    FIELDS = [
        ('number','Номер'),
        ('phone','Телефон'),
        ('status','Статус'),
        ('whenCreated','Создан'),
        ('whenConfirmed','Подтвержден'),
        ('whenPrinted','Напечатан'),
        ('whenCookingCompleted','Готов'),
        ('whenSended','Отправлен'),
        ('whenDelivered','Доставлен'),
        ('whenClosed','Закрыт'),
        ('sum','Сумма'),
        ('deliveryDuration','Длительность (мин)'),
        ('deliveryZone','Зона'),
        ('comment','Комментарий')
    ]
    print("\n=== Детали ===")
    for key, label in FIELDS:
        val = od.get(key)
        print(f"{label}: {val}")
    if cust := od.get('customer'):
        print(f"Клиент: {cust.get('name')} {cust.get('surname')} (id={cust.get('id')})")
    if dp := od.get('deliveryPoint'):
        addr = dp.get('address', {})
        street = addr.get('street', {}).get('name')
        house  = addr.get('house')
        flat   = addr.get('flat')
        full_addr = " ".join(filter(None, [street, house, flat]))
        print(f"Адрес: {full_addr}")
    print("Позиции:")
    for it in od.get('items', []):
        name = it['product']['name']
        qty  = it['amount']
        total = it['resultSum']
        print(f" - {name} x{qty} = {total}")
    if pays := od.get('payments'):
        p = pays[0]
        print(f"Оплата: {p['paymentType']['name']} {p['sum']}")
    if discs := od.get('discounts'):
        for d in discs:
            print(f"Скидка: {d['discountType']['name']} {d['sum']}")

# ======================
# Выбор и показ
# ======================
def select_and_show(orders):
    if not orders:
        return
    for i, o in enumerate(orders, 1):
        od = o.get('order') or o
        print(f"{i}. №{od.get('number')} — {od.get('whenCreated')}")
    choice = input("Детали №: ").strip()
    try:
        idx = int(choice) - 1
        print_details(orders[idx])
    except:
        pass

# ======================
# Main
# ======================
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--login",    required=True, help="API Login")
    p.add_argument("--from",     dest="f",   required=True, help="Начало 'YYYY-MM-DD HH:MM:SS.SSS'")
    p.add_argument("--to",       dest="t",   required=True, help="Конец  'YYYY-MM-DD HH:MM:SS.SSS'")
    p.add_argument("--token-url", default="https://api-eu.syrve.live/api/1/access_token")
    p.add_argument("--orgs-url",  default="https://api-eu.syrve.live/api/1/organizations")
    p.add_argument("--deliv-url", default="https://api-eu.syrve.live/api/1/deliveries/by_delivery_date_and_status")
    args = p.parse_args()

    token = get_access_token(args.login, args.token_url)
    orgs  = get_organizations(token, args.orgs_url)
    sel   = select_orgs(orgs)

    all_orders = []
    for o in sel:
        all_orders += fetch_orders(token, args.deliv_url, o['id'], args.f, args.t)

    sumry = summarize(all_orders)
    print_report(sumry, args.f, args.t, sel)
    select_and_show(all_orders)

if __name__ == '__main__':
    main()
