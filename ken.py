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


def redistribute_supply(daily_net, daily_last_time):
    """
    Calculate daily water supply based on net cumulative values and record times.
    For each pair of consecutive data dates, calculate hourly rate and distribute
    the total flow proportionally across all days in the interval, accounting for
    the actual record time on boundary dates.
    
    hourly_rate = (net_cum[B] - net_cum[A]) / (last_time[B] - last_time[A]) in hours
    Day A share: hourly_rate * (24 - hour_fraction_of_A)
    Missing full days: hourly_rate * 24
    Day B share: hourly_rate * hour_fraction_of_B
    Returns dict of date -> daily_supply for all dates covered by net_cum.
    """
    net_dates = sorted(daily_net.keys())
    result = {}

    for i in range(len(net_dates) - 1):
        curr = net_dates[i]
        next_date = net_dates[i + 1]
        gap = (next_date - curr).days

        t_curr = daily_last_time[curr]
        t_next = daily_last_time[next_date]
        time_gap_hours = (t_next - t_curr).total_seconds() / 3600
        total_flow = daily_net[next_date] - daily_net[curr]
        hourly_rate = total_flow / time_gap_hours

        curr_frac = t_curr.hour + t_curr.minute / 60.0 + t_curr.second / 3600.0
        remaining_curr = 24 - curr_frac
        if remaining_curr > 0:
            result[curr] = result.get(curr, 0) + round(hourly_rate * remaining_curr, 2)

        d = curr + timedelta(days=1)
        while d < next_date:
            result[d] = round(hourly_rate * 24, 2)
            d += timedelta(days=1)

        next_frac = t_next.hour + t_next.minute / 60.0 + t_next.second / 3600.0
        result[next_date] = result.get(next_date, 0) + round(hourly_rate * next_frac, 2)

    return result


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
    all_gaps = []
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

        # Build average 2-4am flow per date
        daily_avg_flow = {}
        for d, flows in daily_flows.items():
            if flows:
                daily_avg_flow[d] = sum(flows) / len(flows)
        
        daily_net = {}
        daily_last_time = {}
        for r in sorted(records, key=lambda x: x['dt']):
            daily_net[r['date']] = r['net_cum']
            daily_last_time[r['date']] = r['dt']
        
        # Redistribute supply across gaps using hourly rate
        redistributed = redistribute_supply(daily_net, daily_last_time)

        # Collect gap info for log file
        net_dates_log = sorted(daily_net.keys())
        
        # Check for gap at start of target range
        if net_dates_log and net_dates_log[0] > start_target_date:
            first_data_date = net_dates_log[0]
            gap_days = (first_data_date - start_target_date).days
            if gap_days > 0:
                affected = []
                dt = start_target_date
                while dt <= first_data_date:
                    affected.append(fmt_date(dt))
                    dt += timedelta(days=1)
                all_gaps.append({
                    'meter': addr,
                    'from': fmt_date(start_target_date),
                    'to': fmt_date(first_data_date),
                    'span_days': gap_days + 1,
                    'time_gap_hours': round(gap_days * 24, 2),
                    'total_supply': round(daily_net[first_data_date], 2),
                    'hourly_rate': 0,
                    'daily_supply': 0,
                    'affected_dates': ' | '.join(affected),
                })
        
        # Check gaps between existing data dates
        for gi in range(len(net_dates_log) - 1):
            gc = net_dates_log[gi]
            gn = net_dates_log[gi + 1]
            if (gn - gc).days > 1:
                t_gc = daily_last_time[gc]
                t_gn = daily_last_time[gn]
                time_gap_hours = (t_gn - t_gc).total_seconds() / 3600
                total_gap = daily_net[gn] - daily_net[gc]
                hourly_gap = total_gap / time_gap_hours
                daily_gap = round(hourly_gap * 24, 2)
                span_gap = (gn - gc).days + 1
                affected = []
                dt = gc
                while dt <= gn:
                    affected.append(fmt_date(dt))
                    dt += timedelta(days=1)
                all_gaps.append({
                    'meter': addr,
                    'from': fmt_date(gc),
                    'to': fmt_date(gn),
                    'span_days': span_gap,
                    'time_gap_hours': round(time_gap_hours, 2),
                    'total_supply': round(total_gap, 2),
                    'hourly_rate': round(hourly_gap, 2),
                    'daily_supply': daily_gap,
                    'affected_dates': ' | '.join(affected),
                })
        
        # Check for gap at end of target range
        if net_dates_log and net_dates_log[-1] < end_target_date:
            last_data_date = net_dates_log[-1]
            gap_days = (end_target_date - last_data_date).days
            if gap_days > 0:
                affected = []
                dt = last_data_date
                while dt <= end_target_date:
                    affected.append(fmt_date(dt))
                    dt += timedelta(days=1)
                all_gaps.append({
                    'meter': addr,
                    'from': fmt_date(last_data_date),
                    'to': fmt_date(end_target_date),
                    'span_days': gap_days + 1,
                    'time_gap_hours': round(gap_days * 24, 2),
                    'total_supply': 0,
                    'hourly_rate': 0,
                    'daily_supply': 0,
                    'affected_dates': ' | '.join(affected),
                })
        
        matched_days = [d for d in daily_flows.keys() if start_target_date <= d <= end_target_date]
        data_date_count = len(matched_days)
        # Generate full date range for the target window
        full_range = []
        d = start_target_date
        while d <= end_target_date:
            full_range.append(d)
            d += timedelta(days=1)

        # Identify dates with redistributed supply (filled by gap redistribution)
        orig_supply_dates = set()
        net_sorted = sorted(daily_net.items())
        for i in range(1, len(net_sorted)):
            if (net_sorted[i][0] - net_sorted[i-1][0]).days == 1:
                orig_supply_dates.add(net_sorted[i][0])


        filled_supply_dates = [d for d in full_range if d in redistributed and d not in orig_supply_dates]

        print('     目标范围内有效天数:', data_date_count, '天')
        if len(full_range) > data_date_count:
            if filled_supply_dates:
                print('     补齐明细（日期: 日供水量）:')
                for fd in filled_supply_dates:
                    print(f'       {fmt_date(fd)}: {redistributed[fd]:.2f}')
        
        for d in full_range:
            all_rows.append({
                '时间': fmt_date(d),
                '地址': addr,
                '瞬时流量': round(daily_avg_flow.get(d, 0), 2),
                '日供水量': round(redistributed.get(d, 0), 2),
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

    # 生成缺失数据日志
    log_path = 'data_log.txt'
    try:
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write('=' * 60 + '\n')
            f.write('上海肯特漏水控制管理平台 - 数据补齐日志\n')
            f.write('=' * 60 + '\n')
            f.write(f'执行日期: {fmt_date(datetime.now().date())}\n')
            f.write(f'目标范围: {fmt_date(start_target_date)} ~ {fmt_date(end_target_date)}\n')
            f.write('\n')
            
            f.write('=' * 60 + '\n')
            f.write('一、补齐逻辑说明\n')
            f.write('=' * 60 + '\n')
            f.write('1. 原始数据获取:\n')
            f.write('   - 从平台获取每个监测点的瞬时流量和净累积量数据\n')
            f.write('   - 瞬时流量: 取凌晨2-4点的平均值\n')
            f.write('   - 日供水量: 基于净累积量差值计算\n')
            f.write('\n')
            f.write('2. 数据补齐规则:\n')
            f.write('   - 对于连续日期(gap=1): 日供水量 = 次日净累积量 - 当日净累积量\n')
            f.write('   - 对于有缺口的日期(gap>1): 使用小时平均流量进行插值补齐\n')
            f.write('     公式: hourly_rate = (净累积量B - 净累积量A) / 时间差(小时)\n')
            f.write('     公式: 补齐日供水量 = hourly_rate * 24\n')
            f.write('   - 边界日期: 根据记录时间计算部分时段供水量\n')
            f.write('\n')
            f.write('3. 缺失判定:\n')
            f.write('   - 目标范围内无原始数据的日期视为缺失\n')
            f.write('   - 有原始数据但凌晨2-4点无流量记录的日期,瞬时流量记为0\n')
            f.write('\n')
            
            f.write('=' * 60 + '\n')
            f.write('二、各监测点数据明细与补齐对比\n')
            f.write('=' * 60 + '\n')
            
            meter_data = {}
            for row in all_rows:
                addr = row['地址']
                if addr not in meter_data:
                    meter_data[addr] = []
                meter_data[addr].append(row)
            
            for addr, rows in meter_data.items():
                f.write(f'\n监测点: {addr}\n')
                f.write('-' * 50 + '\n')
                f.write(f'{"日期":<12} {"状态":<8} {"原值(瞬时流量)":<16} {"补齐后(瞬时流量)":<20} {"原值(日供水量)":<16} {"补齐后(日供水量)":<20}\n')
                f.write('-' * 50 + '\n')
                
                for row in rows:
                    has_original_flow = row['瞬时流量'] > 0
                    has_original_supply = row['日供水量'] > 0
                    
                    if has_original_flow and has_original_supply:
                        status = '原始数据'
                        orig_flow = row['瞬时流量']
                        filled_flow = row['瞬时流量']
                        orig_supply = row['日供水量']
                        filled_supply = row['日供水量']
                    elif has_original_supply:
                        status = '部分补齐'
                        orig_flow = '-'
                        filled_flow = row['瞬时流量']
                        orig_supply = row['日供水量']
                        filled_supply = row['日供水量']
                    elif row['日供水量'] > 0:
                        status = '补齐数据'
                        orig_flow = '-'
                        filled_flow = row['瞬时流量']
                        orig_supply = '-'
                        filled_supply = row['日供水量']
                    else:
                        status = '数据缺失'
                        orig_flow = '-'
                        filled_flow = '-'
                        orig_supply = '-'
                        filled_supply = '-'
                    
                    f.write(f'{row["时间"]:<12} {status:<8} ')
                    if orig_flow == '-':
                        f.write(f'{orig_flow:<16} ')
                    else:
                        f.write(f'{orig_flow:<16.2f} ')
                    if filled_flow == '-':
                        f.write(f'{filled_flow:<20} ')
                    else:
                        f.write(f'{filled_flow:<20.2f} ')
                    if orig_supply == '-':
                        f.write(f'{orig_supply:<16} ')
                    else:
                        f.write(f'{orig_supply:<16.2f} ')
                    if filled_supply == '-':
                        f.write(f'{filled_supply:<20}\n')
                    else:
                        f.write(f'{filled_supply:<20.2f}\n')
            
            f.write('\n')
            f.write('=' * 60 + '\n')
            f.write('三、缺失数据缺口详情\n')
            f.write('=' * 60 + '\n')
            
            if all_gaps:
                for g in all_gaps:
                    f.write(f'\n监测点: {g["meter"]}\n')
                    f.write(f'  缺失日期范围: {g["from"]} ~ {g["to"]}\n')
                    f.write(f'  涵盖天数: {g["span_days"]} 天\n')
                    f.write(f'  受影响日期: {g["affected_dates"]}\n')
                    if g["hourly_rate"] > 0:
                        f.write(f'\n  补齐逻辑:\n')
                        f.write(f'    时间跨度: {g["time_gap_hours"]} 小时\n')
                        f.write(f'    缺口时段总供水量: {round(g["total_supply"], 2)}\n')
                        f.write(f'    平均小时流量: {round(g["hourly_rate"], 2)} (计算公式: 总供水量 / 时间跨度)\n')
                        f.write(f'    折合整日日供水量: {round(g["daily_supply"], 2)} (计算公式: 平均小时流量 * 24)\n')
                        f.write(f'\n  补齐公式:\n')
                        f.write(f'    hourly_rate = (净累积量[{g["to"]}] - 净累积量[{g["from"]}]) / {g["time_gap_hours"]}小时\n')
                        f.write(f'    每日补齐值 = hourly_rate * 24\n')
                    else:
                        f.write(f'  状态: 此缺口位于目标范围边界，无原始数据可用于插值计算\n')
            
            f.write('\n')
            f.write('=' * 60 + '\n')
            f.write(f'共 {len(all_gaps)} 个数据缺口\n')
            f.write('=' * 60 + '\n')
        print(f'  日志文件已生成: {log_path}')
    except Exception as e:
        print(f'  生成日志文件失败: {e}')
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