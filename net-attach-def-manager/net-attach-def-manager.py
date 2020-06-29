#!/usr/bin/env python3

from datetime import datetime
import json
import subprocess
from time import sleep
import traceback
import yaml


def log(msg):
    msg = str(msg)
    timestamp = datetime.now().strftime('[%Y-%m-%d %H:%M:%S]')
    print(timestamp + ' ' + msg, flush=True)


def apply(net_attach_defs):
    if not net_attach_defs:
        return
    for net_attach_def in net_attach_defs:
        metadata = net_attach_def.setdefault('metadata', {})
        labels = metadata.setdefault('labels', {})
        labels['charm-multus-net-attach-def-manager'] = 'true'
    with open('/tmp/net-attach-defs.yaml', 'w') as f:
        yaml.safe_dump_all(net_attach_defs, f)
    subprocess.call(['kubectl', 'apply', '-f', '/tmp/net-attach-defs.yaml'])


def prune(net_attach_defs):
    current_net_attach_defs = set()
    for net_attach_def in net_attach_defs:
        metadata = net_attach_def['metadata']
        namespace = metadata['namespace']
        name = metadata['name']
        current_net_attach_defs.add((namespace, name))

    try:
        output = subprocess.check_output([
            'kubectl', 'get', 'net-attach-def',
            '--all-namespaces',
            '-l', 'charm-multus-net-attach-def-manager=true',
            '-o', 'json'
        ])
    except subprocess.CalledProcessError:
        log(traceback.format_exc())
        return

    existing_net_attach_defs = json.loads(output)['items']
    for net_attach_def in existing_net_attach_defs:
        metadata = net_attach_def['metadata']
        namespace = metadata['namespace']
        name = metadata['name']
        if (namespace, name) not in current_net_attach_defs:
            log('Deleting NetworkAttachmentDefinition %s/%s'
                % (namespace, name))
            subprocess.call([
                'kubectl', 'delete', 'net-attach-def', '-n', namespace, name,
                '--ignore-not-found'
            ])


def main():
    log('Starting main loop')
    while True:
        log('Applying changes')
        with open('/config/manifest.yaml') as f:
            net_attach_defs = list(yaml.safe_load_all(f))
        apply(net_attach_defs)
        prune(net_attach_defs)
        sleep(10)


main()
