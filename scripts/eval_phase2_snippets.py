"""Source-bound snippet diagnostics retained from the dependent branch."""
import re
import unicodedata

def word_character(character):
    return bool(character) and (character.isalnum() or character == '_' or unicodedata.category(character).startswith('M'))

def inspect_excerpt(source, rendered):
    """Compare with captured source characters, not a guess from the display alone."""
    if source.startswith(rendered):
        body = rendered
    elif rendered.endswith('…') and source.startswith(rendered[:-1]):
        body = rendered[:-1]
    else:
        return {'valid_source_prefix': False, 'clipped': False, 'mid_word_end': False,
                'sentence_boundary': False, 'omitted': False}
    clipped = len(body) < len(source)
    broken = bool(clipped and body and word_character(body[-1]) and word_character(source[len(body)]))
    sentence = bool(re.search(r'''[.!?…。！？।]["'”’»\)\]]*$''', body))
    return {'valid_source_prefix': True, 'clipped': clipped, 'mid_word_end': broken,
            'sentence_boundary': sentence, 'omitted': not body.strip()}

def complete_word_prefix(source, rendered):
    """Do not count a cut-off final identifier as a complete query-word match."""
    body = rendered if source.startswith(rendered) else rendered.removesuffix('…')
    if inspect_excerpt(source, rendered)['mid_word_end']:
        end = len(body)
        while end and word_character(body[end - 1]):
            end -= 1
        body = body[:end]
    return body
