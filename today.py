"""
Renders dark_mode.svg and light_mode.svg: a neofetch-style GitHub profile card
with live GitHub stats. Inspired by https://github.com/Andrew6rant/Andrew6rant

Env:
    ACCESS_TOKEN  GitHub token (classic: repo, read:user / fine-grained: read Contents, Metadata)
    USER_NAME     GitHub login (defaults to 'aymericzip')

Run with --offline to re-render from cache/stats.json without calling the API.
"""
import datetime
import json
import os
import sys
import textwrap
import time
from html import escape

import requests
from dateutil import relativedelta

USER_NAME = os.environ.get('USER_NAME', 'aymericzip')
TOKEN = os.environ.get('ACCESS_TOKEN', '')
HEADERS = {'authorization': 'token ' + TOKEN}
AFFILIATIONS = ['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER']

# Set to a datetime.datetime(YYYY, M, D) to show your age as "Uptime".
# When None, Uptime counts from the GitHub account creation date.
BIRTHDAY = None

STATS_FILE = 'cache/stats.json'
LOC_FILE = 'cache/loc.json'

WIDTH = 60  # characters per line in the info panel
ART_SHARE = 0.35  # fraction of the card width taken by the ASCII art

ABOUT = (
    'I’m aymericzip, a developer who believes the best ideas happen by pushing again and again. '
    'When I’m not chasing git push dopamine, you’ll find me turning thoughts into scalable code '
    'and writing docs that (hopefully) make future developers smile.'
)

ASCII_ART = r"""
=*++*+++++++++=++++=+=+=++=========+========================-=
+++++++++++++++++++++++++++=+===================-=============
+++++++++++++++++++++++=+++=====+============================-
+++++++++++++++++++++++=+=++++=+==+====================-=--===
+*+++++++++++++++++=++++++++++++=+=+=+=========+======-====-==
*++*++++++++++++++++++=++++*%*#+##+==+==================-=====
+++++**++++++++++++#%%*%%%##%%#%#%%%*++*+==================-==
+++*+++*+++++*+++#*##%%%%%%@%@%%@%#%%#*#***++=+=====-=====-===
++*+*++++*+++++%*%#%@@@%%%%%%%@%%@%@@%%%####*+##++======-=====
++++*+++++++*#%%%%%#@@@@@@%%%@@@@%@@@@@@%%##*+*#*%=======-==-=
*++++*+++**##%#@%%@@@@%@@@%@%@@@%@%@@@@@@@@###%%%#*=-=========
++++**+*+#**##%%@@%%%%%@@%@%@@@@@@%%@@@@@@@%%%#%##*======--===
*+++++*+**#%%#%@%@@@@@@@@@%%%%@@@%@@@@#@@@@%%#%%%%#+=======-=-
++*++++*+##%@@@@%@@%#%%%%%%%@@%@#%%%%@@@@%%%@@@%#%%===========
***++**++*#%%%@%%@@%#**##*%%#%##**+%%%%#####@@@##%%+==-======-
+***+++++*##%%%@@@%*++===+*****+==++**#+**+**%@@@%#*==+====-==
*+****++++*#%%@@%#*==============-+=+++=+=+++*%%@%%+==========
*+**+***++*++%@@#*+==========-----=++=+====+++#%%%#+==========
+******+++*+*%%%*++===-------:--:::----====++*#%%#======+=====
*****++++++++*%@%*++=-----::::::-:------===++*#%%=============
*******++*+++++%%***+=+++#+--:=:=-==*####*#*##*%#====+==+=====
**+***+++++++++@%###*==+**+*=-:--+++*+=++*+=+**%=+==+========+
+******+++++++++%#++%=%@%-+=*+--=*+==:#@#***=+*#==============
*******+*+++*+++#++++===---++=====++=----=-==++*===+=++=+=====
********++*+++*+**+==----===++=-=++=====-==-==*++=====+=+==+=+
************+*+*.*+==------=+=--==++-------===+.=====+===+++=+
************+**+.++=-----::+==::--==+::-----==+.=++===+++=+=++
***************+*#+=---::--+=+---*+++---:::-==*++==+=+++=++=++
******************+=------=-=-=---====+=-=---++++=++==+=+++=++
*******************+=--=++====-:::-=+*==+==-=*#=++=+=+++++++++
*********************----*++==---===+*#=---=+*++++++++++++++++
#********************=----=+++=:::**+=+----**+++++++++++++++++
********************+*==----==----=++====-++*+*+++++++++++++++
********************++*+----=-=-=-====-=+###*++*++**+++*++++++
*****#*************=++**#=------------=+***##********+*+**++++
#######**********+=+++==*#+----:::---=#++***=***********+**+**
#######*******:==-:%++===**#=-==--==*=++++*%====**************
*####==--+*----.=-.=+++==+*++===+=*++=====+#-:=:=:+*********+*
##=---=-:==-:---.:=-++=--=++++===+===--===+*--=+::=:=#********
:-:-:::-=-:-:==:-.*.+++=-==-======-----===+*-..-===-::=**#****
=====+*:::=-+-=:.:=:==+==-=-=------------=++----::==--=:-==***
=====-=.-==+=::=---:+==+=-==-=---=------===.---=-::-::=--::-+-
::::==:--==-.--..==:.+=+=-==-==--------=-=..=-::.=:--==.=-+-:=
-::==::::+::.-=:-:=:.+=+=--=----==-------..====:.=-++=::-:---:
:=-=::.:+=-:-::...-:..+=+-=---=---==-=-=...:..---:=-=.-=-=::::
""".strip('\n').split('\n')

# The art is drawn for light-on-dark; swap the density ramp for dark-on-light.
INVERT = str.maketrans('.:-=*#%@', '@%#*=-:.')

THEMES = {
    'dark': {'bg': '#161b22', 'text': '#c9d1d9', 'key': '#ffa657', 'value': '#a5d6ff',
             'add': '#3fb950', 'del': '#f85149', 'cc': '#616e7f', 'invert': False},
    'light': {'bg': '#f6f8fa', 'text': '#24292f', 'key': '#953800', 'value': '#0a3069',
              'add': '#1a7f37', 'del': '#cf222e', 'cc': '#c2cfde', 'invert': True},
}

QUERY_COUNT = 0


class GraphQLError(Exception):
    def __init__(self, status, text):
        super().__init__('GraphQL request failed', status, text)
        self.status = status


def graphql(query, variables, retries=4, rate_limit_waits=5):
    global QUERY_COUNT
    QUERY_COUNT += 1
    attempt = 0
    while True:
        response = requests.post('https://api.github.com/graphql',
                                 json={'query': query, 'variables': variables}, headers=HEADERS)
        # Partial errors (e.g. 'additions count unavailable' on huge commits) still return usable data
        if response.status_code == 200 and response.json().get('data'):
            return response.json()['data']
        if response.status_code in (403, 429) and 'rate limit' in response.text and rate_limit_waits > 0:
            rate_limit_waits -= 1
            wait = int(response.headers.get('retry-after', 60))
            print(f'   rate limited, waiting {wait}s', flush=True)
            time.sleep(wait)
            continue
        attempt += 1
        if response.status_code in (502, 503, 504) and attempt < retries:
            time.sleep(2 ** attempt)
            continue
        raise GraphQLError(response.status_code, response.text)


def get_user():
    data = graphql('''
    query($login: String!) {
        user(login: $login) { id createdAt followers { totalCount } }
    }''', {'login': USER_NAME})['user']
    return data['id'], data['createdAt'], data['followers']['totalCount']


def get_repos(affiliations):
    """All repositories for the given affiliations, with star and commit counts."""
    repos, cursor = [], None
    while True:
        data = graphql('''
        query($login: String!, $affiliations: [RepositoryAffiliation], $cursor: String) {
            user(login: $login) {
                repositories(first: 60, after: $cursor, ownerAffiliations: $affiliations) {
                    nodes {
                        nameWithOwner
                        isFork
                        stargazerCount
                        defaultBranchRef { target { ... on Commit { history { totalCount } } } }
                    }
                    pageInfo { endCursor hasNextPage }
                }
            }
        }''', {'login': USER_NAME, 'affiliations': affiliations, 'cursor': cursor})
        page = data['user']['repositories']
        repos += page['nodes']
        if not page['pageInfo']['hasNextPage']:
            return repos
        cursor = page['pageInfo']['endCursor']


def repo_loc(name_with_owner, owner_id):
    """
    Walks my commits on the default branch (filtered server-side), summing additions/deletions.
    Pages of huge commits can time out (502), so the page size shrinks on failure.
    """
    owner, name = name_with_owner.split('/')
    additions = deletions = my_commits = 0
    cursor, page_size = None, 100
    while True:
        try:
            data = history_page(owner, name, owner_id, cursor, page_size)
        except GraphQLError as error:
            if error.status not in (502, 503, 504) or page_size <= 5:
                raise
            page_size //= 2
            continue
        branch = data['repository']['defaultBranchRef']
        if branch is None:
            return 0, 0, 0
        history = branch['target']['history']
        for commit in history['nodes']:
            if commit:
                my_commits += 1
                additions += commit['additions'] or 0
                deletions += commit['deletions'] or 0
        if not history['pageInfo']['hasNextPage']:
            return additions, deletions, my_commits
        cursor = history['pageInfo']['endCursor']
        page_size = min(100, page_size * 2)


def history_page(owner, name, author_id, cursor, page_size):
    time.sleep(0.5)  # stay under GitHub's secondary (burst) rate limit
    return graphql('''
    query($owner: String!, $name: String!, $cursor: String, $size: Int!, $author: ID!) {
        repository(owner: $owner, name: $name) {
            defaultBranchRef { target { ... on Commit {
                history(first: $size, after: $cursor, author: {id: $author}) {
                    nodes { additions deletions }
                    pageInfo { endCursor hasNextPage }
                }
            } } }
        }
    }''', {'owner': owner, 'name': name, 'cursor': cursor, 'size': page_size, 'author': author_id}, retries=2)


def commit_count(repo):
    branch = repo['defaultBranchRef']
    return branch['target']['history']['totalCount'] if branch else 0


def loc_stats(repos, owner_id):
    """
    Lines of code and commits authored by me, across every repo I can access.
    Only repos whose commit count changed since the last run are re-scanned (cache/loc.json).
    """
    cache = load_json(LOC_FILE, {})
    fresh = {}
    try:
        for repo in repos:
            name, total = repo['nameWithOwner'], commit_count(repo)
            cached = cache.get(name)
            if cached and cached['total'] == total:
                fresh[name] = cached
            else:
                print('   scanning', name, flush=True)
                additions, deletions, mine = repo_loc(name, owner_id) if total else (0, 0, 0)
                fresh[name] = {'total': total, 'commits': mine, 'add': additions, 'del': deletions}
    finally:
        # Save partial progress so a rate-limited run can resume next time
        save_json(LOC_FILE, {**cache, **fresh} if len(fresh) < len(repos) else fresh)
    return {
        'loc_add': sum(r['add'] for r in fresh.values()),
        'loc_del': sum(r['del'] for r in fresh.values()),
        'commits': sum(r['commits'] for r in fresh.values()),
    }


def active_days(start, end):
    """Days between start and end (at most one year apart) with at least one contribution."""
    data = graphql('''
    query($login: String!, $from: DateTime!, $to: DateTime!) {
        user(login: $login) { contributionsCollection(from: $from, to: $to) {
            contributionCalendar { weeks { contributionDays { contributionCount } } }
        } }
    }''', {'login': USER_NAME, 'from': start.isoformat() + 'Z', 'to': end.isoformat() + 'Z'})
    weeks = data['user']['contributionsCollection']['contributionCalendar']['weeks']
    return sum(1 for week in weeks for day in week['contributionDays'] if day['contributionCount'])


def activity_stats():
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, microsecond=0)
    return {
        'days_last_365': active_days(now - datetime.timedelta(days=365), now),
        'days_by_year': {
            str(year): active_days(datetime.datetime(year, 1, 1), min(now, datetime.datetime(year, 12, 31, 23, 59, 59)))
            for year in range(now.year - 2, now.year + 1)
        },
    }


def fetch_stats():
    owner_id, created_at, followers = get_user()
    owned = get_repos(['OWNER'])
    accessible = get_repos(AFFILIATIONS)
    stats = {
        'created_at': created_at,
        'repos': len(owned),
        'contributed': len(accessible),
        'stars': sum(r['stargazerCount'] for r in owned),
        'followers': followers,
    }
    # Forks carry mostly other people's history; skip them for LOC and commits
    stats.update(loc_stats([r for r in accessible if not r['isFork']], owner_id))
    stats.update(activity_stats())
    return stats


def uptime(since):
    diff = relativedelta.relativedelta(datetime.datetime.today(), since)
    plural = lambda n, unit: f"{n} {unit}{'' if n == 1 else 's'}"
    cake = ' 🎂' if BIRTHDAY and diff.months == 0 and diff.days == 0 else ''
    return f"{plural(diff.years, 'year')}, {plural(diff.months, 'month')}, {plural(diff.days, 'day')}{cake}"


# ---------------------------------------------------------------- rendering

def kv(keys, value, width, value_class='value'):
    """'. Key.Sub: ....... value' as styled segments, padded with dots to `width` chars."""
    segments = [('cc', '. ')]
    for i, key in enumerate(keys):
        if i:
            segments.append((None, '.'))
        segments.append(('key', key))
    segments.append((None, ':'))
    used = length(segments) + len(value)
    segments.append(('cc', dots(width - used)))
    segments.append((value_class, value))
    return segments


def dots(n):
    if n <= 2:
        return [' ', ' ', '. '][max(n, 0)]
    return ' ' + '.' * (n - 2) + ' '


def length(segments):
    return sum(len(text) for _, text in segments)


def then(left, keys, value):
    """Appends ' | Key: .... value' to `left`, justified so the whole line is WIDTH chars."""
    right = kv(keys, value, WIDTH - length(left) - 3 + 2)[1:]  # drop the leading '. '
    return left + [(None, ' | ')] + right


def paragraph(text, highlight=None):
    """Wraps text to the panel width, one row per line, with `highlight` drawn as a key."""
    rows = []
    for line in textwrap.wrap(text, WIDTH - 2):
        row = [('cc', '. ')]
        parts = line.split(highlight) if highlight else [line]
        for i, part in enumerate(parts):
            if i:
                row.append(('key', highlight))
            if part:
                row.append((None, part))
        rows.append(row)
    return rows


def header(title):
    return [(None, title + ' -' + '—' * (WIDTH - len(title) - 5) + '-—-')]


def build_rows(stats):
    fmt = '{:,}'.format
    since = BIRTHDAY or datetime.datetime.strptime(stats['created_at'][:10], '%Y-%m-%d')
    loc_total = stats['loc_add'] - stats['loc_del']
    loc_tail = [(None, ' ( '), ('add', fmt(stats['loc_add']) + '++'), (None, ', '),
                ('del', fmt(stats['loc_del']) + '--'), (None, ' )')]

    return [
        header('aymeric@pineau'),
        kv(['OS'], 'macOS, Linux', WIDTH),
        kv(['Uptime'], uptime(since), WIDTH),
        kv(['Host'], 'Intlayer', WIDTH),
        kv(['Kernel'], 'Founder & Software Engineer', WIDTH),
        kv(['IDE'], 'VSCode, Cursor', WIDTH),
        [('cc', '. ')],
        kv(['Languages', 'Programming'], 'JS, TS, React, Solid, Svelte, Vue, Angular', WIDTH),
        kv(['Languages', 'Real'], 'French, English', WIDTH),
        kv(['Techno', 'Ops'], 'Docker, K8S', WIDTH),
        None,
        header('- About me'),
        *paragraph(ABOUT, highlight='aymericzip'),
        None,
        header('- Contact'),
        kv(['Website'], 'intlayer.org', WIDTH),
        kv(['LinkedIn'], 'aymericpineau', WIDTH),
        kv(['X'], '@aymericzip', WIDTH),
        kv(['YouTube'], '@aymeric_zip', WIDTH),
        None,
        header('- GitHub Stats'),
        then(kv(['Repos'], fmt(stats['repos']), 14)
             + [(None, ' {'), ('key', 'Contributed'), (None, ': '), ('value', fmt(stats['contributed'])), (None, '}')],
             ['Stars'], fmt(stats['stars'])),
        then(kv(['Commits'], fmt(stats['commits']), 33), ['Followers'], fmt(stats['followers'])),
        kv(['Lines of Code'], fmt(loc_total), WIDTH - length(loc_tail)) + loc_tail,
    ] + ([kv(['Committed'], f"{stats['days_last_365']} days / last 365", WIDTH)] if 'days_last_365' in stats else []) + [
        kv(['Committed'], f'{days} days in {year}', WIDTH)
        for year, days in sorted(stats.get('days_by_year', {}).items(), reverse=True)
    ]


def render(theme_name, rows):
    theme = THEMES[theme_name]
    line_height, top, art_x = 20, 30, 15
    info_w = int(WIDTH * 9.6)
    width = round((art_x + 25 + info_w + 20) / (1 - ART_SHARE))
    info_x = width - 20 - info_w
    # Shrink the art's font so it spans ART_SHARE of the width (9.6px per char at 16px).
    art_scale = ART_SHARE * width / (max(map(len, ASCII_ART)) * 9.6)
    art_line = line_height * art_scale
    height = top + round(max(art_line * (len(ASCII_ART) - 1), line_height * (len(rows) - 1))) + 20

    art = ASCII_ART
    if theme['invert']:
        art = [line.translate(INVERT) for line in art]

    out = [
        "<?xml version='1.0' encoding='UTF-8'?>",
        f'<svg xmlns="http://www.w3.org/2000/svg" font-family="ConsolasFallback,Consolas,monospace" '
        f'width="{width}px" height="{height}px" font-size="16px">',
        '<style>',
        "@font-face {\nsrc: local('Consolas'), local('Consolas Bold');\nfont-family: 'ConsolasFallback';\n"
        'font-display: swap;\n-webkit-size-adjust: 109%;\nsize-adjust: 109%;\n}',
        f".key {{fill: {theme['key']};}}",
        f".value {{fill: {theme['value']};}}",
        f".add {{fill: {theme['add']};}}",
        f".del {{fill: {theme['del']};}}",
        f".cc {{fill: {theme['cc']};}}",
        'text, tspan {white-space: pre;}',
        '</style>',
        f'<rect width="{width}px" height="{height}px" fill="{theme["bg"]}" rx="15"/>',
        f'<text x="{art_x}" y="{top}" fill="{theme["text"]}" font-size="{16 * art_scale:.2f}px" class="ascii">',
    ]
    for i, line in enumerate(art):
        out.append(f'<tspan x="{art_x}" y="{top + i * art_line:.1f}">{escape(line)}</tspan>')
    out.append('</text>')

    out.append(f'<text x="{info_x}" y="{top}" fill="{theme["text"]}">')
    for i, row in enumerate(rows):
        if row is None:
            continue
        y = top + i * line_height
        spans = []
        for j, (cls, text) in enumerate(row):
            attrs = (f' x="{info_x}" y="{y}"' if j == 0 else '') + (f' class="{cls}"' if cls else '')
            spans.append(f'<tspan{attrs}>{escape(text)}</tspan>')
        out.append(''.join(spans))
    out.append('</text>')
    out.append('</svg>')
    return '\n'.join(out) + '\n'


# ------------------------------------------------------------------ helpers

def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=1, sort_keys=True)
        f.write('\n')


if __name__ == '__main__':
    start = time.perf_counter()
    if '--offline' in sys.argv:
        stats = load_json(STATS_FILE, None)
        if stats is None:
            sys.exit(f'{STATS_FILE} not found; run once with ACCESS_TOKEN set.')
    else:
        if not TOKEN:
            sys.exit('ACCESS_TOKEN is not set.')
        stats = fetch_stats()
        save_json(STATS_FILE, stats)

    rows = build_rows(stats)
    for theme in THEMES:
        with open(f'{theme}_mode.svg', 'w', encoding='utf-8') as f:
            f.write(render(theme, rows))

    print(json.dumps(stats, indent=1))
    print(f'Done in {time.perf_counter() - start:.2f}s, {QUERY_COUNT} GraphQL calls')
