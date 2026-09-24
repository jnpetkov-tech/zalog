"""ЗАДАЧА_НАЦИОНАЛНИ, части В (празни дни за 365 дни) и Г (цена). Нула API заявки -
чете validation/nacionalni_b_machove_20260924.csv, *_merged_full.csv и api_calls.log.
Пуска се от корена на проекта."""
import csv, re
from collections import Counter
import pandas as pd
LG = "bulgaria england germany spain france champions_league europa_league conference_league italy portugal france2 spain2 italy2 portugal2 bulgaria2 england2 germany2".split()
yth = lambda r: bool(re.search(r'U\d\d| W$|Women', r['home'] + ' ' + r['away']))
club = Counter()
for l in LG:
    for x in pd.read_csv(f'{l}_merged_full.csv', usecols=['date'])['date'].astype(str).str[:10]:
        club[x] += 1
R = [r for r in csv.DictReader(open('validation/nacionalni_b_machove_20260924.csv'))
     if r['status'] in ('FT', 'AET', 'PEN') and not yth(r)]
nat = Counter(r['date'][:10] for r in R)
rng = list(pd.date_range('2025-09-24', '2026-09-23').strftime('%Y-%m-%d'))
empty = [d for d in rng if club.get(d, 0) == 0]
print('В: дни', len(rng), 'празни за клубовете', len(empty), 'от тях с национални', sum(nat.get(d, 0) > 0 for d in empty),
      'национални мачове в тях', sum(nat.get(d, 0) for d in empty))
print('   празни по месец', sorted(Counter(d[:7] for d in empty).items()))
print('   запълнени по месец', sorted(Counter(d[:7] for d in empty if nat.get(d, 0) > 0).items()))
rows = [dict(date=d, club_matches=club.get(d, 0), national_senior_matches=nat.get(d, 0)) for d in rng]
w = csv.DictWriter(open('validation/nacionalni_v_prazni_dni_365_20260924.csv', 'w', newline=''), fieldnames=list(rows[0]))
w.writeheader(); w.writerows(rows)

# Г: разход по източник, 03-23.09.2026 (21 дни)
c = Counter(); perday = Counter()
for line in open('api_calls.log'):
    p = line.split()
    if len(p) < 3: continue
    d = p[0][:10]
    if '2026-09-03' <= d <= '2026-09-23':
        c[p[1] + ' ' + p[2]] += 1; perday[d] += 1
DAYS = 21
fixed = c['/fixtures fetch_upcoming_fixtures'] + c['/fixtures check_results'] + c['/fixtures main']
var = c['/odds fetch_fixture_odds'] + c['/injuries fetch_fixture_injuries'] + c['/fixtures/statistics fetch_fixture_stats'] + c['/fixtures/lineups fetch_lineups_available']
nclub = sum(v for d, v in club.items() if '2026-09-03' <= d <= '2026-09-23')
print('Г: заявки/ден среден', round(sum(perday.values()) / DAYS), 'макс', max(perday.values()), 'мин', min(perday.values()))
print('   постоянни на лига на ден', round(fixed / DAYS / 17, 1), '| на мач', round(var / nclub, 1), '(клубни мачове', nclub, ')')
for k, v in c.most_common(8):
    print(f'   {k:45s} {v:6d} /ден {v / DAYS:7.1f}')
