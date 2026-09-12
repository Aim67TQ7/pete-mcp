"""Section adapter for the owner's indexed Markdown; not a scheduler or grant source."""
import argparse
import hashlib
import json
import re
from pathlib import Path

ANCHOR = re.compile(r'^<a id="([a-z0-9-]+)"></a>\s*$', re.M)


def load(path, requested=(), expected_sha256=None):
    raw = Path(path).read_bytes()
    if len(raw) > 262144:
        raise ValueError('Runbook exceeds 256 KB')
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError('Runbook hash mismatch')
    text = raw.decode('utf-8')
    matches = list(ANCHOR.finditer(text))
    names = [m[1] for m in matches]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate anchor')
    sections = {m[1]: text[m.end():matches[i+1].start() if i+1 < len(matches) else len(text)].strip()
                for i, m in enumerate(matches)}
    def rule(section, number):
        blocks = re.findall(r'```json\s*\n(.*?)\n```', sections.get(section, ''), re.S)
        if len(blocks) != 1:
            raise ValueError('Missing or ambiguous rule JSON')
        value = json.loads(blocks[0])
        if type(value.get('rule')) is not int or value['rule'] != number:
            raise ValueError('Wrong rule number')
        return value
    definition, index = rule('rule-0', 0), rule('rule-1', 1)
    for key in ('runbook_id', 'version'):
        if not definition.get(key) or definition[key] != index.get(key):
            raise ValueError('Runbook identity/version mismatch')
    indexed = [s['id'] for s in index['sections']]
    if len(indexed) != len(set(indexed)) or set(indexed) != set(names):
        raise ValueError('Index/anchor mismatch')
    wanted = list(dict.fromkeys(['rule-0', 'rule-1', *requested]))
    if any(s not in sections for s in wanted + index['load_order']):
        raise ValueError('Unknown section')
    return {'runbook_id': definition['runbook_id'], 'runbook_version': definition['version'],
            'runbook_sha256': digest, 'sections_loaded': wanted,
            'sections': {s: sections[s] for s in wanted},
            'authority_note': 'Owner supplied document; runtime grants and budgets remain independently enforced.',
            'rule_2_status': definition['rule_2']['status']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path')
    parser.add_argument('--section', action='append', default=[])
    parser.add_argument('--sha256')
    args = parser.parse_args()
    print(json.dumps(load(args.path, args.section, args.sha256), indent=2))
