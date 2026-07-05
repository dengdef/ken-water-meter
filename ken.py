import urllib.request
import urllib.parse
import http.cookiejar
import json
import csv
from datetime import datetime, timedelta


def aspnet_encode(s):
    result = ''
    for c in s:
        o = ord(c)
        if o > 127:
            result += '%%u%04X' % o
        elif c in '{}&:"%#,;=+@/<> ':
            result += '%%%02X' % o
        else:
            result += c
    return result


def urlopen_with_retry(req, timeout=30, retries=2):
    import time
    last_err = None
    for attempt in range(1 + retries):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except Exception as e:
            last_err = e
            print(f'  [retry {attempt + 1}/{1 + retries}] {e}')
            time.sleep(1)
    raise last_err


def login(base_url, username, password):
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    req = urllib.request.Request(base_url + '/Login')
    req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
    urlopen_with_retry(req, timeout=30)
    post_data = urllib.parse.urlencode({'username': username, 'password': password}).encode()
    req = urllib.request.Request(base_url + '/Login/UserLogin', data=post_data)
    req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    req.add_header('X-Requested-With', 'XMLHttpRequest')
    req.add_header('Referer', base_url + '/Login')
    resp = urlopen_with_retry(req, timeout=30)
    body = resp.read().decode('utf-8')
    data = json.loads(body)
    if data.get('PowerCode'):
        return data, opener
    return None, None


def build_cookie_header(login_data, username):
    ju = json.dumps({'ID': login_data['ID'], 'NickName': login_data['NickName'],
        'UserName': login_data['UserName'], 'PowerCode': login_data['PowerCode'],
        'CompanyID': login_data['CompanyID']}, ensure_ascii=False)
    return '; '.join([
        'PowerCode=' + login_data['PowerCode'],
        'UserName=' + username,
        'Nickname=' + urllib.parse.quote(login_data['NickName']),
        'jsonUser=' + aspnet_encode(ju)])


def fetch_meter_data(base_url, meter_id, begin, end, cookie_header):
    params = urllib.parse.urlencode({
        'MeterId': meter_id, 'BeginTime': begin, 'EndTime': end, 'Factor': '60'}).encode()
    req = urllib.request.Request(base_url + '/Analysis/GetYSTXHistoryDataBYFactor', data=params)
    req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    req.add_header('X-Requested-With', 'XMLHttpRequest')
    req.add_header('Cookie', cookie_header)
    resp = urlopen_with_retry(req, timeout=30)
    return json.loads(resp.read().decode('utf-8'))


def fmt_date(d):
    return d.strftime('%Y-%m-%d')


def main(params=None):
    base_url = 'http://www.shanghaikent.com:18601'
    username = 'scmy'
    password = '123456'
    print('=' * 60)
    print('上海肯特渗漏控制管理平台 - 数据获取')
    print('=' * 60)
    login_result, _ = login(base_url, username, password)
    if not login_result:
        print('登录失败')
        return {}
    print()
    print('  Login OK!')
    print('   PowerCode:', login_result['PowerCode'])
    print('   ID:', login_result['ID'])
    cookie_header = build_cookie_header(login_result, username)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=22)
    begin = fmt_date(start_date)
    end = fmt_date(end_date)
    print('  请求数据范围:', begin, 'to', end)
    meters = [
        ('45976', '显兴水厂门口'),
        ('49071', '富临精工'),
        ('49070', '天台食品城'),
        ('48681', '科技路'),
        ('49878', '三水厂一期'),
        ('46996', '三水厂二期'),
    ]
    today = datetime.now().date()
    start_target_date = today - timedelta(days=20)
    end_target_date = today - timedelta(days=1)
    print('  目标提取范围:', fmt_date(start_target_date), 'to', fmt_date(end_target_date))
    print('  预计提取天数:', (end_target_date - start_target_date).days + 1)
    all_rows = []
    for mid, addr in meters:
        raw = fetch_meter_data(base_url, mid, begin, end, cookie_header)
        if not raw:
            print('   -', addr, '- 无数据')
            continue
        records = []
        for item in raw:
            try:
                dt = datetime.strptime(item.get('数据时间', ''), '%Y-%m-%d %H:%M:%S')
                records.append({
                    'dt': dt, 'date': dt.date(), 'hour': dt.hour,
                    'flow': item.get('瞬时流量', 0) or 0,
                    'net_cum': item.get('净累积量', 0) or 0,
                })
            except:
                pass
        if not records:
            print('   -', addr, '- 解析后无数据')
            continue
        record_dates = sorted(set(r['date'] for r in records))
        print('   ~', addr, '- 原始数据日期:', len(record_dates), '天')
        print('     日期范围:', fmt_date(record_dates[0]), 'to', fmt_date(record_dates[-1]))
        
        daily_flows = {}
        for r in records:
            d = r['date']
            if 2 <= r['hour'] <= 4:
                daily_flows.setdefault(d, []).append(r['flow'])
        
        daily_net = {}
        for r in sorted(records, key=lambda x: x['dt']):
            daily_net[r['date']] = r['net_cum']
        
        net_sorted = sorted(daily_net.items())
        daily_supply = {}
        for i in range(1, len(net_sorted)):
            daily_supply[net_sorted[i][0]] = net_sorted[i][1] - net_sorted[i - 1][1]
        
        matched_days = [d for d in daily_flows.keys() if start_target_date <= d <= end_target_date]
        print('     目标范围内有效天数:', len(matched_days), '天')
        
        for d in matched_days:
            flows = daily_flows[d]
            all_rows.append({
                '时间': fmt_date(d),
                '地址': addr,
                '瞬时流量': round(sum(flows) / len(flows), 2),
                '日供水量': round(daily_supply.get(d, 0), 2),
            })
        print('   +', addr, '- OK')
    if not all_rows:
        print('未找到指定日期范围内的数据')
        return {}
    all_rows.sort(key=lambda r: (r['地址'], r['时间']))
    print('=' * 60)
    print('{:<6}{:<12}{:<10}{:<12}{:<12}'.format(
        '#', '日期', '地址', '瞬时流量', '日供水量'))
    print('=' * 60)
    for idx, row in enumerate(all_rows, 1):
        print('{:<6}{:<12}{:<10}{:<12.2f}{:<12.2f}'.format(
            idx, row['时间'], row['地址'], row['瞬时流量'], row['日供水量']))
    print('=' * 60)
    
    # 生成 CSV 文件
    csv_file_path = 'data.csv'
    try:
        with open(csv_file_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['时间', '地址', '瞬时流量', '日供水量'])
            for row in all_rows:
                writer.writerow([row['时间'], row['地址'], row['瞬时流量'], row['日供水量']])
        print(f'  CSV 文件已成功生成: {csv_file_path}')
    except Exception as e:
        print(f'  生成 CSV 文件失败: {e}')
        
    result = {}
    for idx, row in enumerate(all_rows, 1):
        result['dataPoint' + str(idx)] = row
    return result


def handler(req, context=None):
    return main(req if isinstance(req, dict) else {})


if __name__ == '__main__':
    r = main()
    print()
    print('Result:', json.dumps(r, ensure_ascii=False, indent=2))