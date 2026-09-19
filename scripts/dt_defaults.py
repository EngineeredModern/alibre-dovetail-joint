# Sliding Dovetail user preferences. Independent of assembly joint metadata.
import json
import math
import os
import uuid

FACTORY = {'head_width': 0.75, 'depth': 0.25, 'angle': 60.0,
           'clearance': 0.006, 'distance': 2.0, 'min_wall': 0.06,
           'blend_radius': 0.03, 'length_mode': 0}

def validate(values):
    result = {}
    for key in FACTORY:
        if key not in values:
            raise ValueError('Missing default: ' + key)
        value = values[key]
        if isinstance(value, bool):
            raise ValueError('Invalid default: ' + key)
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            raise ValueError('Defaults must be finite numbers.')
        result[key] = value
    if result['length_mode'] not in (0, 1, 2):
        raise ValueError('Choose a valid Length Mode.')
    result['length_mode'] = int(result['length_mode'])
    if result['head_width'] <= 0 or result['depth'] <= 0:
        raise ValueError('Head Width and Depth must be greater than zero.')
    if not 0 < result['angle'] < 90:
        raise ValueError('Flank Angle must be between 0 and 90 degrees.')
    if result['distance'] <= 0:
        raise ValueError('Default Distance Length must be greater than zero.')
    if min(result['clearance'], result['min_wall'], result['blend_radius']) < 0:
        raise ValueError('Clearance, Minimum Wall and Blend Radius cannot be negative.')
    return result

def load(path):
    if not os.path.isfile(path):
        return dict(FACTORY), None
    try:
        with open(path, 'r') as handle:
            data = json.load(handle)
        if data.get('schema') != 1:
            raise ValueError('Unsupported defaults format.')
        return validate(data['defaults']), None
    except Exception as ex:
        return dict(FACTORY), 'Saved defaults could not be read; factory defaults are in use. ' + str(ex)

def save(path, values):
    # Validate before touching the existing file. Replace atomically on Windows.
    values = validate(values)
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    temporary = path + '.' + uuid.uuid4().hex + '.tmp'
    try:
        with open(temporary, 'w') as handle:
            json.dump({'schema': 1, 'defaults': values}, handle, indent=2, allow_nan=False)
            handle.flush()
        from System.IO import File
        # File.Replace is unreliable when called from IronPython on some
        # Windows user-profile locations. Copy with overwrite, then remove
        # the temporary file; the existing preferences remain valid if the
        # process stops before the copy completes.
        File.Copy(temporary, path, True)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return values
