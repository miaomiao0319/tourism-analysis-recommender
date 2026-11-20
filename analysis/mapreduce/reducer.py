"""Streaming reducer; Hadoop streaming shuffle supplies sorted keys."""
import json
import sys


def aggregate(lines):
    previous = None
    count = 0
    for line in lines:
        key, separator, number = line.rstrip('\n').partition('\t')
        if not separator:
            raise ValueError('Reducer expected tab-separated key/value')
        dims = json.loads(key)
        if dims.get('scope') not in ('city', 'grade') or number != '1':
            raise ValueError('Unknown reducer key/value')
        if previous is not None and key < previous:
            raise ValueError('Unsorted reducer input')
        if key != previous:
            if previous is not None:
                yield f'{previous}\t{count}'
            previous, count = key, 0
        count += 1
    if previous is not None:
        yield f'{previous}\t{count}'


def main():
    for line in aggregate(sys.stdin):
        print(line)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'REDUCER ERROR: {exc}', file=sys.stderr)
        raise
