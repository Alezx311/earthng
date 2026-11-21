"""FoliMesh (folimesh.com) models for the flora of a region, through its MCP endpoint.

FoliMesh is a procedural vegetation generator: a species, a seed (the variant), an age and a
style make one model with four levels of detail, photo textures and wind data, the same file
every time. Its server speaks MCP over plain HTTP (JSON-RPC 2.0, a JSON reply, no session):
list_species, describe_params and get_stats are free, export_glb costs one download from the
account's balance (the same species, seed, age and style again is free).

The key is the user's own: FOLIMESH_KEY, or one line in data/folimesh.key. It is never written
anywhere else. Every exported GLB is kept in data/folimesh/, with a line in its log.jsonl, so a
model is paid for once.

The licence (folimesh.com/license, 4b) forbids the models in an open repository: data/ is not
in Git, and the repository holds only the recipe (earthng/flora/<region>.json).

    python earthng/folimesh.py balance
    python earthng/folimesh.py species --category trees
    python earthng/folimesh.py params oak
    python earthng/folimesh.py stats oak --seed 2 --age 60
    python earthng/folimesh.py fetch --region ukraine --limit 20 [--dry-run]
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ENDPOINT = 'https://folimesh.com/api/mcp'
CACHE = ROOT / 'data' / 'folimesh'
KEY_FILE = ROOT / 'data' / 'folimesh.key'
RECIPES = HERE / 'flora'
# builds a minute on the smallest plan (folimesh.com/mcp): one every PACE seconds
PACE = 16
AGENT = 'EarthNG-flora/1'


class FoliMeshError(RuntimeError):
    pass


def key():
    """The account's API key, or None: the environment first, then data/folimesh.key."""
    value = os.environ.get('FOLIMESH_KEY', '').strip()
    if not value and KEY_FILE.exists():
        for line in KEY_FILE.read_text(encoding='utf8').splitlines():
            line = line.strip().strip('"\'')
            if line and not line.startswith('#'):
                value = line.split()[-1] if line.lower().startswith('bearer') else line
                break
    return value or None


def http(payload, api_key, timeout=180):
    """One JSON-RPC request to the endpoint; the decoded reply."""
    request = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode('utf8'), method='POST', headers={
        'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
        'Authorization': f'Bearer {api_key}', 'User-Agent': AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            body = reply.read().decode('utf8')
    except urllib.error.HTTPError as error:
        body = error.read().decode('utf8', 'replace')
        try:
            return json.loads(body)
        except ValueError:
            raise FoliMeshError(f'HTTP {error.code}: {body[:300]}') from None
    except (urllib.error.URLError, TimeoutError) as error:
        raise FoliMeshError(f'no reply from {ENDPOINT}: {error}') from None
    # a server may frame one reply as an event stream
    if body.lstrip().startswith(('event:', 'data:')):
        lines = [line[5:].strip() for line in body.splitlines() if line.startswith('data:')]
        body = lines[-1] if lines else '{}'
    try:
        return json.loads(body)
    except ValueError:
        raise FoliMeshError(f'not JSON: {body[:300]}') from None


def unwrap(reply):
    """The payload of a tools/call reply: its structured content, or its text decoded as JSON,
    or the text itself."""
    if not isinstance(reply, dict):
        raise FoliMeshError(f'unexpected reply: {reply!r}')
    if reply.get('error'):
        error = reply['error']
        raise FoliMeshError(str(error.get('message') if isinstance(error, dict) else error))
    result = reply.get('result')
    if not isinstance(result, dict):
        return result
    texts = [c.get('text', '') for c in result.get('content') or [] if isinstance(c, dict) and c.get('type') == 'text']
    if result.get('isError'):
        raise FoliMeshError(' '.join(texts) or 'the tool failed')
    if isinstance(result.get('structuredContent'), (dict, list)):
        return result['structuredContent']
    text = '\n'.join(texts).strip()
    try:
        return json.loads(text)
    except ValueError:
        return text


def find_url(value):
    """The download link in an export's reply, wherever the server put it."""
    if isinstance(value, str):
        match = re.search(r'https?://[^\s"\'<>)\]]+', value)
        return match.group(0).rstrip('.,') if match else None
    if isinstance(value, dict):
        for name in ('url', 'download_url', 'downloadUrl', 'link', 'href', 'glb', 'file'):
            found = find_url(value.get(name)) if name in value else None
            if found:
                return found
        value = list(value.values())
    if isinstance(value, list):
        for item in value:
            found = find_url(item)
            if found:
                return found
    return None


def slug_of(species, seed=None, age=None, style=None):
    """The cache name of one model: the species and what makes the variant."""
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', species):
        raise ValueError(f'not a species slug: {species!r}')
    parts = [species.replace('-', '_'), f's{int(seed if seed is not None else 1)}']
    if age is not None:
        parts.append(f'a{int(age)}')
    if style and style != 'real':
        parts.append(re.sub(r'[^a-z0-9]', '', style.lower()))
    return '_'.join(parts)


class Client:
    """The endpoint's five tools. send(payload, key) -> reply is injected in tests."""

    def __init__(self, api_key=None, send=http, cache=CACHE, pace=PACE, sleep=time.sleep, clock=time.monotonic):
        self.key, self.send, self.cache, self.pace = api_key or key(), send, Path(cache), pace
        self.sleep, self.clock, self.serial, self.last_build = sleep, clock, 0, None

    def call(self, tool, **arguments):
        if not self.key:
            raise FoliMeshError(f'no API key: set FOLIMESH_KEY or put it in {KEY_FILE} '
                                '(folimesh.com -> account -> API keys & MCP; a plan with MCP)')
        self.serial += 1
        arguments = {k: v for k, v in arguments.items() if v is not None}
        return unwrap(self.send({'jsonrpc': '2.0', 'id': self.serial, 'method': 'tools/call',
                                 'params': {'name': tool, 'arguments': arguments}}, self.key))

    def tools(self):
        self.serial += 1
        reply = self.send({'jsonrpc': '2.0', 'id': self.serial, 'method': 'tools/list', 'params': {}}, self.key)
        if reply.get('error'):
            raise FoliMeshError(str(reply['error'].get('message')))
        return reply.get('result', {}).get('tools', [])

    def species(self, category=None):
        return self.call('list_species', category=category)

    def params(self, species):
        return self.call('describe_params', species=species)

    def stats(self, species, seed=None, age=None, style=None):
        return self.call('get_stats', species=species, seed=seed, age=age, style=style)

    def balance(self):
        return self.call('get_balance')

    def path(self, species, seed=None, age=None, style=None):
        return self.cache / f'{slug_of(species, seed, age, style)}.glb'

    def export(self, species, seed=None, age=None, style=None, mode='server', download=None):
        """The model's GLB in the cache (one download from the balance the first time)."""
        target = self.path(species, seed, age, style)
        if target.exists() and target.stat().st_size > 20:
            return target, False
        if self.last_build is not None:
            wait = self.pace - (self.clock() - self.last_build)
            if wait > 0:
                self.sleep(wait)
        self.last_build = self.clock()
        reply = self.call('export_glb', species=species, seed=seed, age=age, style=style, mode=mode)
        url = find_url(reply)
        if not url:
            raise FoliMeshError(f'no download link in the reply: {str(reply)[:300]}')
        data = (download or fetch_bytes)(url)
        if data[:4] != b'glTF':
            raise FoliMeshError(f'{url} is not a GLB ({len(data)} bytes)')
        self.cache.mkdir(parents=True, exist_ok=True)
        part = target.with_suffix('.part')
        part.write_bytes(data)
        part.replace(target)
        with (self.cache / 'log.jsonl').open('a', encoding='utf8') as log:
            log.write(json.dumps({'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'file': target.name, 'species': species,
                                  'seed': seed, 'age': age, 'style': style or 'real', 'bytes': len(data),
                                  'sha256': hashlib.sha256(data).hexdigest(),
                                  'reply': reply if isinstance(reply, dict) else None}, ensure_ascii=False) + '\n')
        return target, True


def fetch_bytes(url, timeout=300):
    if not url.startswith('https://'):
        raise FoliMeshError(f'refusing a download that is not https: {url}')
    request = urllib.request.Request(url, headers={'User-Agent': AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return reply.read()
    except (urllib.error.URLError, TimeoutError) as error:
        raise FoliMeshError(f'download failed: {error}') from None


def recipe(region):
    path = RECIPES / f'{region}.json'
    if not path.exists():
        raise FoliMeshError(f'no recipe {path}')
    return json.loads(path.read_text(encoding='utf8'))


def wanted(region_recipe):
    """Every model of a recipe, the most needed first: (priority, order) then the species' own
    order of variants. Each: {name, species, seed, age, style, priority}."""
    out = []
    style = region_recipe.get('style', 'real')
    for order, (name, plant) in enumerate(region_recipe['species'].items()):
        for index, variant in enumerate(plant.get('variants') or [{}]):
            out.append({'name': name, 'species': plant['slug'], 'seed': variant.get('seed', index + 1),
                        'age': variant.get('age'), 'style': variant.get('style', style),
                        # a species' first model before any second one
                        'priority': (plant.get('priority', 2) + index, order, index)})
    out.sort(key=lambda m: m['priority'])
    return out


def balance_left(balance):
    """Downloads left, from whatever shape the server reports the balance in; None if unknown."""
    if isinstance(balance, dict):
        for name in ('downloads', 'downloads_left', 'downloadsLeft', 'remaining_downloads', 'download_credits'):
            value = balance.get(name)
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, dict):
                inner = balance_left(value) if any(isinstance(v, dict) for v in value.values()) else None
                for key_name in ('left', 'remaining', 'available', 'total'):
                    if isinstance(value.get(key_name), (int, float)):
                        return int(value[key_name])
                if inner is not None:
                    return inner
        for value in balance.values():
            found = balance_left(value) if isinstance(value, dict) else None
            if found is not None:
                return found
    if isinstance(balance, str):
        match = re.search(r'(\d+)\s+downloads?', balance)
        return int(match.group(1)) if match else None
    return None


def fetch(client, region, limit=None, reserve=0, dry=False, say=print):
    """Export the recipe's models that are not in the cache yet, the most needed first, while
    the balance stays above `reserve`. Returns (have, got, missing) lists of cache names."""
    models = wanted(recipe(region))
    have, missing = [], []
    for model in models:
        path = client.path(model['species'], model['seed'], model['age'], model['style'])
        (have if path.exists() else missing).append((model, path))
    say(f'{region}: {len(models)} models, {len(have)} in {client.cache}, {len(missing)} to export')
    got = []
    if dry or not missing:
        for model, path in missing:
            say(f'  would export {path.name} ({model["name"]})')
        return [p.name for _, p in have], got, [p.name for _, p in missing]
    left = balance_left(client.balance())
    say(f'downloads left: {left if left is not None else "unknown"}')
    budget = len(missing) if limit is None else min(limit, len(missing))
    if left is not None:
        budget = min(budget, max(0, left - reserve))
    for model, path in missing[:budget]:
        try:
            client.export(model['species'], model['seed'], model['age'], model['style'])
        except FoliMeshError as error:
            say(f'  {path.name}: {error}')
            if 'download' in str(error).lower() and 'left' in str(error).lower():
                break
            continue
        got.append(path.name)
        say(f'  {path.name} ({path.stat().st_size // 1024} KB)')
    still = [p.name for _, p in missing if p.name not in got]
    return [p.name for _, p in have], got, still


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('balance')
    sub.add_parser('tools')
    s = sub.add_parser('species')
    s.add_argument('--category')
    s = sub.add_parser('params')
    s.add_argument('species')
    for name in ('stats', 'export'):
        s = sub.add_parser(name)
        s.add_argument('species')
        s.add_argument('--seed', type=int)
        s.add_argument('--age', type=int)
        s.add_argument('--style')
    s = sub.add_parser('fetch')
    s.add_argument('--region', default='ukraine')
    s.add_argument('--limit', type=int)
    s.add_argument('--reserve', type=int, default=0, help='downloads to leave on the balance')
    s.add_argument('--dry-run', action='store_true')
    a = parser.parse_args()
    client = Client()
    try:
        if a.command == 'balance':
            out = client.balance()
        elif a.command == 'tools':
            out = client.tools()
        elif a.command == 'species':
            out = client.species(a.category)
        elif a.command == 'params':
            out = client.params(a.species)
        elif a.command == 'stats':
            out = client.stats(a.species, a.seed, a.age, a.style)
        elif a.command == 'export':
            path, fresh = client.export(a.species, a.seed, a.age, a.style)
            out = {'file': str(path), 'downloaded': fresh}
        else:
            have, got, missing = fetch(client, a.region, a.limit, a.reserve, a.dry_run)
            out = {'cached': len(have), 'exported': got, 'missing': missing}
    except FoliMeshError as error:
        raise SystemExit(f'FoliMesh: {error}')
    print(out if isinstance(out, str) else json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    main()
