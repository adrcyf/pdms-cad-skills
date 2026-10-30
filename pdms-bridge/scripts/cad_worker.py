"""Session CAD worker: reuse readers/connections until the owning software session ends."""
import json
import sys
import os


def execute(request):
    name, args = request['name'], request['arguments']
    try:
        if name == 'cad_active_read':
            from cad_active import read_active
            result = read_active(**args)
        else:
            from cad_reader import reader_for
            reader = reader_for(args['path'], args.get('core_console'))
            if name == 'cad_summary':
                result = reader.summary()
            elif name == 'cad_preview':
                result = reader.preview(bbox=args.get('bbox'), layout=args.get('layout', 'Model'))
            elif name == 'cad_query':
                result = reader.query(**{key: value for key, value in args.items() if key not in ('path', 'core_console')})
            else:
                raise ValueError('Unknown CAD operation')
    except Exception as exc:
        result = {'ok': False, 'error': str(exc)}
    return result


def main():
    os.environ['CJ_CAD_SESSION'] = '1'
    for raw in sys.stdin.buffer:
        try:
            result = execute(json.loads(raw))
        except Exception as exc:
            result = {'ok': False, 'error': str(exc)}
        sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False) + '\n').encode('utf-8'))
        sys.stdout.buffer.flush()


if __name__ == '__main__':
    main()
